from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl

import pytest

from scripts import agentcore_remote_mcp_demo as demo

SYNTHETIC_ACCOUNT_ID = "1" * 12


def _deployed_state() -> demo.DemoState:
    state = demo.new_state(now=datetime.now(UTC))
    state.account_id = SYNTHETIC_ACCOUNT_ID
    state.bucket_name = demo._bucket_name(state.account_id)
    state.role_arn = f"arn:aws:iam::{state.account_id}:role/{demo.ROLE_NAME}"
    state.runtime_id = "runtime-test-123"
    state.runtime_arn = (
        f"arn:aws:bedrock-agentcore:{demo.REGION}:{state.account_id}:runtime/{state.runtime_id}"
    )
    state.workload_identity_name = "identity-test-123"
    state.workload_identity_arn = (
        f"arn:aws:bedrock-agentcore:{demo.REGION}:{state.account_id}:"
        f"workload-identity/{state.workload_identity_name}"
    )
    state.log_group_name = demo._log_group_name(state.runtime_id)
    state.log_group_arn = demo._log_group_arn(state.account_id, state.log_group_name)
    state.created_bucket = True
    state.bucket_tagged = True
    state.object_uploaded = True
    state.created_role = True
    state.role_tagged = True
    state.created_runtime = True
    state.runtime_tagged = True
    state.created_workload_identity = True
    state.workload_identity_tagged = True
    state.created_log_group = True
    state.log_group_tagged = True
    demo.validate_state(state, require_unexpired=True)
    return state


def _passing_flow() -> dict[str, object]:
    trace = [
        {
            "name": "search_services",
            "status": "passed",
            "elapsed_ms": 1,
            "provenance": "fixture_without_ids",
        },
        {
            "name": "resolve_location",
            "status": "passed",
            "elapsed_ms": 2,
            "provenance": "fixture_without_ids",
        },
        {
            "name": "get_consultation_form",
            "status": "passed",
            "elapsed_ms": 3,
            "provenance": "service_id_from_search_result",
        },
        {
            "name": "match_service_providers",
            "status": "passed",
            "elapsed_ms": 4,
            "provenance": "ids_from_prior_tool_results",
        },
    ]
    return {
        "status": "passed",
        "tool_names": sorted(demo.EXPECTED_TOOL_NAMES),
        "trace": trace,
        "provenance": {key: True for key in demo.PROVENANCE_KEYS},
    }


def test_package_uses_resolved_uv_and_contains_isolated_remote_mcp_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    source_root = project_root / "src" / "home_repair_agent"
    nested = source_root / "backend"
    nested.mkdir(parents=True)
    (source_root / "__init__.py").write_text("", encoding="utf-8")
    (nested / "services.py").write_text("VALUE = 1\n", encoding="utf-8")
    entrypoint = project_root / "agentcore_remote_mcp_entrypoint.py"
    entrypoint.write_text("app = object()\n", encoding="utf-8")
    requirements = project_root / "deploy" / "agentcore_remote_mcp_requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("mcp==1.27.0\n", encoding="utf-8")

    monkeypatch.setattr(demo, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(demo, "BUILD_ROOT", project_root / "var" / "agentcore-remote-mcp")
    monkeypatch.setattr(demo, "ENTRYPOINT_PATH", entrypoint)
    monkeypatch.setattr(demo, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(demo.shutil, "which", lambda executable: "/tools/uv")
    observed: dict[str, object] = {}

    def fake_runner(command: list[str], *, check: bool) -> None:
        observed["command"] = command
        observed["check"] = check
        target = Path(command[command.index("--target") + 1])
        (target / "dependency").mkdir(parents=True)
        (target / "dependency" / "__init__.py").write_text("", encoding="utf-8")

    archive = demo.build_package(uv_executable="injected-uv", runner=fake_runner)

    assert observed["check"] is True
    assert observed["command"][0] == "/tools/uv"  # type: ignore[index]
    assert str(requirements) in observed["command"]  # type: ignore[operator]
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "agentcore_remote_mcp_entrypoint.py" in names
    assert "agentcore_remote_mcp_requirements.txt" in names
    assert "home_repair_agent/__init__.py" in names
    assert "home_repair_agent/backend/services.py" in names
    assert "dependency/__init__.py" in names


def test_runtime_is_direct_code_public_mcp_with_one_common_tag_set() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = demo.new_state(now=now)
    state.account_id = SYNTHETIC_ACCOUNT_ID
    state.bucket_name = demo._bucket_name(state.account_id)
    state.role_arn = f"arn:aws:iam::{state.account_id}:role/{demo.ROLE_NAME}"
    state.log_group_name = demo._log_group_name("runtime-test")

    expected_tags = demo._build_tags(state.expires_at_utc)
    runtime_request = demo._build_runtime_request(
        state,
        now=now,
        client_token="fixed-token",
    )
    role_request = demo._build_role_request(state)
    bucket_tagging = demo._build_bucket_tagging(state)
    log_request = demo._build_log_group_request(state)
    object_args = demo._build_object_upload_args(state)

    assert runtime_request["protocolConfiguration"] == {"serverProtocol": "MCP"}
    assert runtime_request["networkConfiguration"] == {"networkMode": "PUBLIC"}
    code_configuration = runtime_request["agentRuntimeArtifact"]["codeConfiguration"]
    assert code_configuration["entryPoint"] == ["agentcore_remote_mcp_entrypoint.py"]
    assert code_configuration["code"]["s3"]["prefix"] == demo.OBJECT_KEY
    assert runtime_request["lifecycleConfiguration"]["maxLifetime"] <= 6 * 60 * 60
    assert runtime_request["tags"] == expected_tags
    assert role_request["Tags"] == demo._tag_list(expected_tags)
    assert bucket_tagging["TagSet"] == demo._tag_list(expected_tags)
    assert log_request["tags"] == expected_tags
    assert dict(parse_qsl(object_args["Tagging"])) == expected_tags
    assert set(expected_tags) == {
        "Project",
        "Purpose",
        "DataClassification",
        "ManagedBy",
        "ExpiresAt",
    }


def test_execution_role_policy_has_only_agentcore_logs_and_metrics() -> None:
    policy = demo._build_execution_policy(SYNTHETIC_ACCOUNT_ID)
    statements = policy["Statement"]
    actions: set[str] = set()
    for statement in statements:
        value = statement["Action"]
        actions.update(value if isinstance(value, list) else [value])

    assert actions == {
        "logs:DescribeLogStreams",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "cloudwatch:PutMetricData",
    }
    serialized = json.dumps(policy).lower()
    assert "invokemodel" not in serialized
    assert "gateway" not in serialized
    assert "s3:" not in serialized


def test_bucket_setup_is_private_encrypted_one_day_fallback_and_tagged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = demo.new_state(now=datetime.now(UTC))
    state.account_id = SYNTHETIC_ACCOUNT_ID
    state.bucket_name = demo._bucket_name(state.account_id)
    archive = tmp_path / "deployment.zip"
    archive.write_bytes(b"zip")
    expected_tags = demo._build_tags(state.expires_at_utc)

    class FakeS3:
        def __init__(self) -> None:
            self.calls: dict[str, object] = {}

        def create_bucket(self, **kwargs: object) -> None:
            self.calls["create"] = kwargs

        def put_bucket_tagging(self, **kwargs: object) -> None:
            self.calls["bucket_tags"] = kwargs

        def get_bucket_tagging(self, **kwargs: object) -> dict[str, object]:
            return {"TagSet": demo._tag_list(expected_tags)}

        def put_public_access_block(self, **kwargs: object) -> None:
            self.calls["public"] = kwargs

        def put_bucket_ownership_controls(self, **kwargs: object) -> None:
            self.calls["ownership"] = kwargs

        def put_bucket_encryption(self, **kwargs: object) -> None:
            self.calls["encryption"] = kwargs

        def put_bucket_lifecycle_configuration(self, **kwargs: object) -> None:
            self.calls["lifecycle"] = kwargs

        def upload_file(self, *args: object, **kwargs: object) -> None:
            self.calls["upload"] = (args, kwargs)

        def head_object(self, **kwargs: object) -> dict[str, str]:
            return {"ServerSideEncryption": "AES256"}

        def get_object_tagging(self, **kwargs: object) -> dict[str, object]:
            return {"TagSet": demo._tag_list(expected_tags)}

    fake_s3 = FakeS3()
    monkeypatch.setattr(demo, "_save_state", lambda _state: None)

    demo._create_bucket_and_upload({"s3": fake_s3}, state, archive)

    public_config = fake_s3.calls["public"]["PublicAccessBlockConfiguration"]
    assert all(public_config.values())
    encryption_rules = fake_s3.calls["encryption"]["ServerSideEncryptionConfiguration"]["Rules"]
    assert encryption_rules[0]["ApplyServerSideEncryptionByDefault"] == {"SSEAlgorithm": "AES256"}
    lifecycle_rule = fake_s3.calls["lifecycle"]["LifecycleConfiguration"]["Rules"][0]
    assert lifecycle_rule["Expiration"] == {"Days": 1}
    upload_args = fake_s3.calls["upload"][1]["ExtraArgs"]
    assert upload_args["ServerSideEncryption"] == "AES256"
    assert dict(parse_qsl(upload_args["Tagging"])) == expected_tags


def test_state_rejects_expiry_beyond_six_hours() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = demo.new_state(now=now)
    state.expires_at_utc = demo._format_utc(now + timedelta(hours=6, seconds=1))

    with pytest.raises(demo.StateValidationError, match="six-hour"):
        demo.validate_state(state, now=now, allow_incomplete=True)


def test_report_is_whitelisted_and_redacts_identifiers_payloads_and_urls() -> None:
    state = _deployed_state()
    raw = _passing_flow()
    raw["provider_payload"] = {"credentials": "do-not-store"}
    raw["url"] = "https://example.invalid/private"
    raw["trace"][0]["runtime_arn"] = state.runtime_arn
    raw["trace"][0]["account"] = state.account_id
    invocation = demo._sanitize_invocation(raw)
    invocation["tool_names"].append(state.account_id)
    invocation["redacted_trace"][0]["url"] = "https://example.invalid/private"
    invocation["redacted_trace"][0]["runtime_arn"] = state.runtime_arn
    invocation["provenance"]["account"] = state.account_id

    report = demo._build_report(
        status="failed",
        state=state,
        started_at_utc=state.created_at_utc,
        finished_at_utc=state.created_at_utc,
        invocation=invocation,
        failure_stage="invoke",
        failure_type="RemoteMCPError",
        cleanup_summary={
            "status": "partial",
            "failed_resource_types": ["runtime"],
            "provider_payload": raw,
        },
    )
    serialized = json.dumps(report)

    assert set(report) == {
        "status",
        "started_at_utc",
        "finished_at_utc",
        "region",
        "runtime_name",
        "expires_at_utc",
        "tags",
        "tool_names",
        "redacted_trace",
        "provenance",
        "failure_stage",
        "failure_type",
        "cleanup_summary",
    }
    assert state.account_id not in serialized
    assert "arn:aws" not in serialized
    assert "https://" not in serialized
    assert "provider_payload" not in serialized
    assert "credentials" not in serialized
    assert "do-not-store" not in serialized
    assert set(report["tool_names"]) == demo.EXPECTED_TOOL_NAMES


def test_deploy_failure_always_attempts_cleanup_and_hides_provider_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = demo.new_state(now=datetime.now(UTC))
    cleanup_calls: list[demo.DemoState] = []
    monkeypatch.setattr(demo, "REPORT_PATH", tmp_path / "report.json")

    def fail_deploy(
        _archive: Path,
        _state: demo.DemoState,
        _clients: object,
    ) -> demo.DemoState:
        raise RuntimeError("provider payload with arn:aws and credentials")

    def fake_cleanup(cleanup_state: demo.DemoState) -> dict[str, object]:
        cleanup_calls.append(cleanup_state)
        return {"status": "passed"}

    monkeypatch.setattr(demo, "_deploy_impl", fail_deploy)

    with pytest.raises(demo.DemoOperationError) as captured:
        demo.deploy(
            tmp_path / "deployment.zip",
            state,
            clients={"fake": object()},
            cleanup_fn=fake_cleanup,
        )

    assert cleanup_calls == [state]
    assert "provider payload" not in str(captured.value)
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "credentials" not in report_text
    assert "arn:aws" not in report_text
    assert json.loads(report_text)["failure_stage"] == "deploy"


def test_invoke_failure_always_attempts_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _deployed_state()
    cleanup_calls: list[demo.DemoState] = []
    monkeypatch.setattr(demo, "REPORT_PATH", tmp_path / "report.json")

    def fail_flow(_state: demo.DemoState) -> object:
        raise RuntimeError("full provider payload must not escape")

    def fake_cleanup(cleanup_state: demo.DemoState) -> dict[str, object]:
        cleanup_calls.append(cleanup_state)
        return {
            "status": "passed",
            "attempted_resource_types": list(demo.RESOURCE_TYPES),
        }

    with pytest.raises(demo.DemoOperationError) as captured:
        demo.invoke(state, flow_runner=fail_flow, cleanup_fn=fake_cleanup)

    assert cleanup_calls == [state]
    assert "provider payload" not in str(captured.value)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["failure_stage"] == "invoke"
    assert report["cleanup_summary"]["status"] == "passed"


def test_successful_invoke_uses_sanitized_mcp_evidence_and_does_not_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _deployed_state()
    cleanup_calls: list[demo.DemoState] = []
    monkeypatch.setattr(demo, "REPORT_PATH", tmp_path / "report.json")

    def forbidden_cleanup(cleanup_state: demo.DemoState) -> dict[str, object]:
        cleanup_calls.append(cleanup_state)
        return {"status": "passed"}

    report = demo.invoke(
        state,
        flow_runner=lambda _state: _passing_flow(),
        cleanup_fn=forbidden_cleanup,
    )

    assert cleanup_calls == []
    assert report["status"] == "passed"
    assert set(report["tool_names"]) == demo.EXPECTED_TOOL_NAMES
    assert [item["name"] for item in report["redacted_trace"]] == [
        "search_services",
        "resolve_location",
        "get_consultation_form",
        "match_service_providers",
    ]
    assert report["cleanup_summary"]["status"] == "retained"
    serialized = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert state.account_id not in serialized
    assert state.runtime_arn not in serialized


def test_partial_untagged_cleanup_requires_exact_name_and_caller_account() -> None:
    state = _deployed_state()
    partial = demo._RemoteResource(
        exists=True,
        actual_name=demo.RUNTIME_NAME,
        tags={},
        account_matches=True,
    )

    assert demo._cleanup_authorized(
        partial,
        state=state,
        expected_name=demo.RUNTIME_NAME,
        created=True,
        tagged=False,
    )
    assert not demo._cleanup_authorized(
        partial,
        state=state,
        expected_name=demo.RUNTIME_NAME,
        created=True,
        tagged=True,
    )
    wrong_name = demo._RemoteResource(
        exists=True,
        actual_name="other-runtime",
        tags={},
        account_matches=True,
    )
    assert not demo._cleanup_authorized(
        wrong_name,
        state=state,
        expected_name=demo.RUNTIME_NAME,
        created=True,
        tagged=False,
    )
    wrong_account = demo._RemoteResource(
        exists=True,
        actual_name=demo.RUNTIME_NAME,
        tags={},
        account_matches=False,
    )
    assert not demo._cleanup_authorized(
        wrong_account,
        state=state,
        expected_name=demo.RUNTIME_NAME,
        created=True,
        tagged=False,
    )


def test_plan_prints_safe_cleanup_command_without_aws(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        demo,
        "_aws_clients",
        lambda **_kwargs: pytest.fail("plan must not construct AWS clients"),
    )

    assert demo.main(["plan"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup_command"] == ("python scripts/agentcore_remote_mcp_demo.py cleanup")
    serialized = json.dumps(payload)
    assert "arn:aws" not in serialized
    assert "account_id" not in serialized


def test_remote_invoke_delegates_sigv4_mcp_flow_to_client_module() -> None:
    state = _deployed_state()
    calls: dict[str, object] = {}
    scenario = object()
    auth = object()
    session = object()

    class FakeAuth:
        @classmethod
        def from_boto3_session(cls, given_session: object, *, region: str) -> object:
            calls["auth"] = (given_session, region)
            return auth

    def load_synthetic_flow(path: Path) -> object:
        calls["fixture"] = path
        return scenario

    def build_agentcore_invocation_url(*, runtime_arn: str, region: str) -> str:
        calls["url_input"] = (runtime_arn, region)
        return "https://signed-endpoint.invalid/mcp"

    async def run_read_only_flow(**kwargs: object) -> dict[str, object]:
        calls["flow"] = kwargs
        return _passing_flow()

    fake_module = SimpleNamespace(
        AgentCoreSigV4Auth=FakeAuth,
        load_synthetic_flow=load_synthetic_flow,
        build_agentcore_invocation_url=build_agentcore_invocation_url,
        run_read_only_flow=run_read_only_flow,
    )

    result = demo._invoke_remote_mcp(
        state,
        session=session,  # type: ignore[arg-type]
        client_module=fake_module,  # type: ignore[arg-type]
    )

    assert result == _passing_flow()
    assert calls["fixture"] == demo.FIXTURE_PATH
    assert calls["auth"] == (session, demo.REGION)
    assert calls["url_input"] == (state.runtime_arn, demo.REGION)
    flow = calls["flow"]
    assert flow["scenario"] is scenario
    assert flow["auth"] is auth
    assert flow["authentication_label"] == "iam-sigv4"
    assert flow["timeout_seconds"] == 60
