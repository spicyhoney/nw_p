from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from home_repair_agent.agent.demo import DemoReadRepository
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server

HOST = "0.0.0.0"
PORT = 8000
MCP_PATH = "/mcp"
MAX_REQUEST_BODY_BYTES = 64 * 1024
SAFE_REJECTION_BODY = (
    b'{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Request rejected."}}'
)

_ALLOWED_ENVELOPE_KEYS = frozenset({"jsonrpc", "id", "method", "params"})
_ALLOWED_CONTROL_METHODS = frozenset({"initialize", "tools/list", "ping"})
_TOOL_ARGUMENT_TYPES: dict[str, dict[str, tuple[type, ...]]] = {
    "search_services": {
        "query": (str, type(None)),
        "limit": (int,),
    },
    "resolve_location": {
        "county_name": (str,),
        "district_name": (str,),
    },
    "get_consultation_form": {
        "service_id": (int,),
    },
    "match_service_providers": {
        "service_id": (int,),
        "location_id": (str,),
        "preferred_start": (str, type(None)),
        "preferred_end": (str, type(None)),
        "limit": (int,),
    },
}
_TOOL_REQUIRED_ARGUMENTS: dict[str, frozenset[str]] = {
    "search_services": frozenset(),
    "resolve_location": frozenset({"county_name", "district_name"}),
    "get_consultation_form": frozenset({"service_id"}),
    "match_service_providers": frozenset({"service_id", "location_id"}),
}
_PERSONAL_FIELD_KEYS = frozenset(
    {
        "name",
        "fullname",
        "legalname",
        "customername",
        "contactname",
        "recipientname",
        "username",
        "email",
        "emailaddress",
        "phone",
        "phonenumber",
        "mobile",
        "mobilenumber",
        "address",
        "streetaddress",
        "exactaddress",
        "serviceaddress",
        "姓名",
        "真實姓名",
        "聯絡人",
        "聯絡人姓名",
        "收件人",
        "收件人姓名",
        "電子郵件",
        "信箱",
        "電話",
        "手機",
        "地址",
        "詳細地址",
        "服務地址",
    }
)
_MEDIA_FIELD_KEYS = frozenset(
    {
        "image",
        "images",
        "imageurl",
        "photo",
        "photos",
        "photourl",
        "icon",
        "icons",
        "binary",
        "blob",
        "bytes",
        "file",
        "files",
        "attachment",
        "attachments",
        "audio",
        "video",
    }
)
_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])",
    re.IGNORECASE,
)
_TAIWAN_MOBILE_PATTERN = re.compile(
    r"(?<!\d)(?:09\d{2}[\s.-]?\d{3}[\s.-]?\d{3}|"
    r"\+?886[\s.-]?9\d{2}[\s.-]?\d{3}[\s.-]?\d{3})(?!\d)"
)
_TAIWAN_LANDLINE_PATTERN = re.compile(
    r"(?<!\d)(?:0[2-8][\s.-]?\d{3,4}[\s.-]?\d{4}|"
    r"\+?886[\s.-]?[2-8][\s.-]?\d{3,4}[\s.-]?\d{4})(?!\d)"
)
_CHINESE_HOUSE_NUMBER_PATTERN = re.compile(
    r"(?:路|街|大道|段|巷|弄)\s*"
    r"(?:[0-9一二三四五六七八九十百]+段\s*)?"
    r"(?:[0-9]+巷\s*)?(?:[0-9]+弄\s*)?"
    r"[0-9一二三四五六七八九十百]+(?:之[0-9]+)?號"
)
_ENGLISH_HOUSE_NUMBER_PATTERN = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][A-Z0-9'-]*\s+){0,4}"
    r"(?:ROAD|RD|STREET|ST|LANE|LN|AVENUE|AVE)\b",
    re.IGNORECASE,
)
_EXPLICIT_NAME_PATTERN = re.compile(
    r"(?:姓名|真實姓名|聯絡人(?:姓名)?|收件人(?:姓名)?)\s*[:：=]\s*\S+"
    r"|(?:我叫|我的名字是|我的姓名是|本人姓名為)\s*\S+"
    r"|\b(?:MY NAME IS|FULL NAME|LEGAL NAME|CUSTOMER NAME|CONTACT NAME)"
    r"\s*(?:IS|[:=])\s*\S+",
    re.IGNORECASE,
)
_BASE64_BLOB_PATTERN = re.compile(r"[A-Za-z0-9+/]{128,}={0,2}\Z")
_BINARY_TEXT_MARKERS = (
    "data:image/",
    "data:application/octet-stream",
    ";base64,",
    "application/octet-stream",
    "image/jpeg",
    "image/png",
    "image/webp",
)
_BINARY_TYPE_VALUES = frozenset(
    {"image", "binary", "blob", "bytes", "file", "attachment", "audio", "video"}
)


class _InvalidJSON(ValueError):
    pass


class MCPRequestGuard:
    """Small ASGI boundary guard for the public Streamable HTTP endpoint."""

    def __init__(self, downstream: ASGIApp) -> None:
        self._downstream = downstream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != MCP_PATH
        ):
            await self._downstream(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                await _send_rejection(send, status=400)
                return

            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                await _send_rejection(send, status=400)
                return
            if len(body) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                await _send_rejection(send, status=413)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        raw_body = bytes(body)
        if not _is_allowed_request(raw_body):
            await _send_rejection(send, status=400)
            return

        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return await receive()

        await self._downstream(scope, replay_receive, send)


def _is_allowed_request(raw_body: bytes) -> bool:
    try:
        payload = json.loads(
            raw_body,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_json_number,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, _InvalidJSON):
        return False

    if isinstance(payload, dict):
        messages = (payload,)
    elif isinstance(payload, list) and payload:
        messages = tuple(payload)
    else:
        return False

    return all(isinstance(message, dict) and _is_allowed_message(message) for message in messages)


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJSON("duplicate object key")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise _InvalidJSON(f"invalid JSON number: {value}")


def _is_allowed_message(message: dict[str, Any]) -> bool:
    if not set(message).issubset(_ALLOWED_ENVELOPE_KEYS):
        return False
    if message.get("jsonrpc") != "2.0":
        return False

    method = message.get("method")
    if not isinstance(method, str):
        return False

    is_notification = method.startswith("notifications/")
    if is_notification:
        if "id" in message:
            return False
    else:
        if "id" not in message or not _is_json_rpc_id(message["id"]):
            return False

    params = message.get("params", {})
    if not isinstance(params, dict):
        return False

    if method == "tools/call":
        allowed_name_paths = frozenset({("params", "name")})
    elif method == "initialize":
        allowed_name_paths = frozenset({("params", "clientinfo", "name")})
    else:
        allowed_name_paths = frozenset()
    if _contains_restricted_content(message, allowed_name_paths=allowed_name_paths):
        return False

    if method == "tools/call":
        return _is_allowed_tool_call(params)
    return method in _ALLOWED_CONTROL_METHODS or is_notification


def _is_json_rpc_id(value: Any) -> bool:
    return value is None or (not isinstance(value, bool) and isinstance(value, (str, int, float)))


def _is_allowed_tool_call(params: dict[str, Any]) -> bool:
    if not set(params).issubset({"name", "arguments"}):
        return False

    tool_name = params.get("name")
    if not isinstance(tool_name, str) or tool_name not in _TOOL_ARGUMENT_TYPES:
        return False

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return False

    argument_types = _TOOL_ARGUMENT_TYPES[tool_name]
    if not set(arguments).issubset(argument_types):
        return False
    if not _TOOL_REQUIRED_ARGUMENTS[tool_name].issubset(arguments):
        return False

    for key, value in arguments.items():
        expected_types = argument_types[key]
        if int in expected_types and isinstance(value, bool):
            return False
        if not isinstance(value, expected_types):
            return False
    return True


def _contains_restricted_content(
    value: Any,
    *,
    allowed_name_paths: frozenset[tuple[str, ...]],
    path: tuple[str, ...] = (),
) -> bool:
    if isinstance(value, str):
        return _is_restricted_string(value)

    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = _normalize_key(key)
            normalized_path = (*path, normalized_key)
            if normalized_key in _MEDIA_FIELD_KEYS:
                return True
            if normalized_key in _PERSONAL_FIELD_KEYS and normalized_path not in allowed_name_paths:
                return True
            if (
                normalized_key in {"type", "mimetype"}
                and isinstance(child, str)
                and _normalize_key(child) in _BINARY_TYPE_VALUES
            ):
                return True
            if _contains_restricted_content(
                child,
                allowed_name_paths=allowed_name_paths,
                path=normalized_path,
            ):
                return True
        return False

    if isinstance(value, list):
        if len(value) >= 16 and all(type(item) is int and 0 <= item <= 255 for item in value):
            return True
        return any(
            _contains_restricted_content(
                child,
                allowed_name_paths=allowed_name_paths,
                path=path,
            )
            for child in value
        )

    return False


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s_-]", "", normalized)


def _is_restricted_string(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _BINARY_TEXT_MARKERS):
        return True
    if _EMAIL_PATTERN.search(normalized):
        return True
    if _TAIWAN_MOBILE_PATTERN.search(normalized):
        return True
    if _TAIWAN_LANDLINE_PATTERN.search(normalized):
        return True
    if _CHINESE_HOUSE_NUMBER_PATTERN.search(normalized):
        return True
    if _ENGLISH_HOUSE_NUMBER_PATTERN.search(normalized):
        return True
    if _EXPLICIT_NAME_PATTERN.search(normalized):
        return True

    compact = "".join(normalized.split())
    return len(compact) >= 128 and _BASE64_BLOB_PATTERN.fullmatch(compact) is not None


async def _send_rejection(send: Send, *, status: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(SAFE_REJECTION_BODY)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": SAFE_REJECTION_BODY})


mcp = create_mcp_server(
    ReadServiceLayer(DemoReadRepository()),
    host=HOST,
    port=PORT,
)
_mcp_http_app = mcp.streamable_http_app()
app = MCPRequestGuard(_mcp_http_app)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, access_log=False)


if __name__ == "__main__":
    main()
