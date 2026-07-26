from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone

from mcp.shared.memory import create_connected_server_and_client_session

from home_repair_agent.agent.huggingface_model import (
    HuggingFaceConfigurationError,
    HuggingFaceModelClient,
)
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.mock_model import RuleBasedRepairMockModel
from home_repair_agent.agent.models import ConversationSession, ToolTraceEntry
from home_repair_agent.agent.ports import ModelClient
from home_repair_agent.backend.models import (
    AvailableProviderSlot,
    ConsultationForm,
    FormOption,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server

DEMO_SERVICE_ID = 17
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
SCRIPTED_INPUTS = (
    "台北市大安區水龍頭漏水",
    "水龍頭漏水",
    "星期六下午",
)
DEMO_NOTICE_TEMPLATE = """\
修繕小隊長｜本機終端 Demo
模型：{model_label}
資料：記憶體 Demo 資料（不連 AWS、不寫資料庫、不建立案件）
用途：人工驗證 Agent → 四個唯讀 MCP Tools → Service Layer 的多輪閉環。
指令：/help、/reset、/quit
"""


class DemoReadRepository:
    """Small, explicitly synthetic repository used only by the local demo."""

    def __init__(self) -> None:
        self._service = ServiceSummary(
            service_id=DEMO_SERVICE_ID,
            service_vendor_id=11,
            vendor_name="Demo 修繕服務商",
            service_type="10",
            service_type_name="水電修繕",
            name="水電修繕",
            description="本機 Demo 用的合成服務資料。",
            aliases=["水電", "漏水", "水龍頭", "馬桶"],
        )
        self._locations = (
            ResolvedLocation(
                location_id="DEMO-63000030",
                county_name="臺北市",
                district_name="大安區",
                full_name="臺北市大安區",
            ),
            ResolvedLocation(
                location_id="DEMO-65000010",
                county_name="新北市",
                district_name="板橋區",
                full_name="新北市板橋區",
            ),
        )
        self._form = ConsultationForm(
            form_key="demo_repair_form_v1",
            service_id=DEMO_SERVICE_ID,
            version=1,
            name="Demo 水電修繕諮詢單",
            description="縮短過的合成表單，用來展示多輪追問；不是正式案件表單。",
            topics=[
                FormTopic(
                    topic_key="issue_category",
                    input_type="single_select",
                    title="需要處理的問題",
                    is_required=True,
                    sort_order=1,
                    options=[
                        FormOption(
                            option_key="leaking_faucet",
                            value="leaking_faucet",
                            label="水龍頭漏水",
                            sort_order=1,
                        ),
                        FormOption(
                            option_key="clogged_toilet",
                            value="clogged_toilet",
                            label="馬桶堵塞",
                            sort_order=2,
                        ),
                    ],
                ),
                FormTopic(
                    topic_key="preferred_time",
                    input_type="text",
                    title="希望服務時間",
                    is_required=True,
                    sort_order=2,
                ),
                FormTopic(
                    topic_key="notes",
                    input_type="text",
                    title="其他備註",
                    is_required=False,
                    sort_order=3,
                ),
            ],
        )
        self._slots = (
            AvailableProviderSlot(
                provider_id="SYN-PROVIDER-001",
                display_name="安心修繕 A 組",
                service_id=DEMO_SERVICE_ID,
                rating=4.8,
                completed_jobs=128,
                base_inspection_fee=300,
                location_id="DEMO-63000030",
                location_name="臺北市大安區",
                availability_id="SYN-SLOT-001",
                starts_at=datetime(2026, 8, 1, 13, tzinfo=TAIPEI_TIMEZONE),
                ends_at=datetime(2026, 8, 1, 17, tzinfo=TAIPEI_TIMEZONE),
            ),
            AvailableProviderSlot(
                provider_id="SYN-PROVIDER-002",
                display_name="城市水電 B 組",
                service_id=DEMO_SERVICE_ID,
                rating=4.6,
                completed_jobs=86,
                base_inspection_fee=250,
                location_id="DEMO-63000030",
                location_name="臺北市大安區",
                availability_id="SYN-SLOT-002",
                starts_at=datetime(2026, 8, 1, 14, tzinfo=TAIPEI_TIMEZONE),
                ends_at=datetime(2026, 8, 1, 18, tzinfo=TAIPEI_TIMEZONE),
            ),
        )

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        searchable_terms = (
            self._service.name,
            self._service.service_type_name or "",
            *self._service.aliases,
        )
        if query and not any(term in query for term in searchable_terms):
            return []
        return [self._service][:limit]

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        return [
            location
            for location in self._locations
            if (
                county_name == location.county_name
                or county_base == _without_suffix(location.county_name, ("縣", "市"))
            )
            and (
                district_name == location.district_name
                or district_base
                == _without_suffix(location.district_name, ("區", "鄉", "鎮", "市"))
            )
        ]

    def list_consultation_forms(
        self,
        *,
        service_id: int,
    ) -> list[ConsultationForm]:
        return [self._form] if service_id == DEMO_SERVICE_ID else []

    def list_available_provider_slots(
        self,
        *,
        service_id: int,
        location_id: str,
        preferred_start: datetime | None,
        preferred_end: datetime | None,
        candidate_limit: int,
    ) -> list[AvailableProviderSlot]:
        return [
            slot
            for slot in self._slots
            if slot.service_id == service_id
            and slot.location_id == location_id
            and (
                preferred_start is None
                or (
                    preferred_end is not None
                    and slot.starts_at < preferred_end
                    and slot.ends_at > preferred_start
                )
            )
        ][:candidate_limit]


async def run_demo(
    *,
    model_client: ModelClient | None = None,
    model_label: str = "Mock Model（規則式）",
    scripted: bool = False,
    show_trace: bool = True,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> ConversationSession:
    output_func(DEMO_NOTICE_TEMPLATE.format(model_label=model_label).rstrip())
    server = create_mcp_server(ReadServiceLayer(DemoReadRepository()))
    conversation = ConversationSession(session_id="terminal-demo")

    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as mcp_session:
        runner = AgentRunner(
            model_client=(model_client if model_client is not None else RuleBasedRepairMockModel()),
            tool_client=MCPToolClient(mcp_session),
        )
        scripted_inputs = iter(SCRIPTED_INPUTS)

        while True:
            try:
                if scripted:
                    user_text = next(scripted_inputs)
                    output_func(f"\n你 > {user_text}")
                else:
                    user_text = input_func("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt, StopIteration):
                break

            if not user_text:
                continue
            if user_text == "/quit":
                break
            if user_text == "/help":
                output_func("輸入修繕需求，或用 /reset 清除對話、/quit 離開。")
                continue
            if user_text == "/reset":
                conversation = ConversationSession(session_id="terminal-demo")
                output_func("Agent > 對話已重設。")
                continue

            result = await runner.run_turn(
                session=conversation,
                user_text=user_text,
            )
            if show_trace:
                for entry in result.tool_trace:
                    output_func(_format_trace(entry))
            output_func(f"Agent > {result.reply}")

    output_func("\nDemo 結束；本次只讀取 synthetic 候選，沒有保留時段或建立案件。")
    return conversation


def _format_trace(entry: ToolTraceEntry) -> str:
    arguments = json.dumps(entry.arguments, ensure_ascii=False, sort_keys=True)
    ok = entry.result.get("ok") is True and not entry.mcp_is_error
    return f"  [MCP] {entry.name}({arguments}) -> {'ok' if ok else 'error'}"


def _without_suffix(value: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local home repair Agent demo.",
    )
    parser.add_argument(
        "--model-provider",
        choices=("mock", "huggingface"),
        default="mock",
        help="model adapter to use (default: mock)",
    )
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="run a fixed three-turn scenario and exit",
    )
    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="hide MCP tool-call trace lines",
    )
    return parser


def _resolve_model_client(
    model_provider: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[ModelClient, str]:
    if model_provider == "mock":
        return RuleBasedRepairMockModel(), "Mock Model（規則式）"
    if model_provider == "huggingface":
        client = HuggingFaceModelClient.from_environment(environ=environ)
        label = f"Hugging Face｜{client.model_id}（provider={client.provider}）"
        return client, label
    raise ValueError(f"unsupported model provider: {model_provider}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        model_client, model_label = _resolve_model_client(args.model_provider)
    except HuggingFaceConfigurationError as error:
        parser.error(str(error))
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    asyncio.run(
        run_demo(
            model_client=model_client,
            model_label=model_label,
            scripted=args.scripted,
            show_trace=not args.no_trace,
        )
    )


if __name__ == "__main__":
    main()
