from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlencode

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "us-west-2"
PROJECT = "nw_p"
PURPOSE = "agentcore-remote-mcp-demo"
DATA_CLASSIFICATION = "synthetic-only"
MANAGED_BY = "kiro"
RUNTIME_NAME = "nw_p_agentcore_remote_mcp_demo"
ROLE_NAME = "AmazonBedrockAgentCoreRuntime-nw-p-remote-mcp-demo"
ROLE_POLICY_NAME = "AgentCoreRemoteMcpDemoRuntimePolicy"
BUCKET_PREFIX = "nw-p-agentcore-remote-mcp-demo"
OBJECT_KEY = f"{RUNTIME_NAME}/deployment.zip"
LOG_GROUP_PREFIX = "/aws/bedrock-agentcore/runtimes/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "var" / "agentcore-remote-mcp"
STATE_PATH = BUILD_ROOT / "state.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "agentcore_remote_mcp_demo.json"
REQUIREMENTS_PATH = PROJECT_ROOT / "deploy" / "agentcore_remote_mcp_requirements.txt"
ENTRYPOINT_PATH = PROJECT_ROOT / "agentcore_remote_mcp_entrypoint.py"
CLIENT_MODULE_PATH = PROJECT_ROOT / "scripts" / "agentcore_remote_mcp_client.py"
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "agentcore_remote_mcp_synthetic.json"
MAX_LIFETIME = timedelta(hours=6)
MAX_LIFETIME_SECONDS = int(MAX_LIFETIME.total_seconds())
STATE_SCHEMA_VERSION = 1
EXPECTED_TOOL_FLOW = (
    "search_services",
    "resolve_location",
    "get_consultation_form",
    "match_service_providers",
)
EXPECTED_TOOL_NAMES = frozenset(EXPECTED_TOOL_FLOW)
RESOURCE_TYPES = (
    "runtime",
    "workload_identity",
    "log_group",
    "iam_role",
    "s3_bucket",
)
TRACE_PROVENANCE = frozenset(
    {
        "fixture_without_ids",
        "service_id_from_search_result",
        "ids_from_prior_tool_results",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "service_id_from_search_result",
        "location_id_from_location_result",
        "form_used_prior_service_id",
        "match_used_prior_service_and_location_ids",
        "provider_data_source_synthetic",
    }
)
_NOT_FOUND_CODES = frozenset(
    {
        "404",
        "NoSuchBucket",
        "NoSuchEntity",
        "NotFound",
        "ResourceNotFoundException",
        "ValidationException",
    }
)
_ACCOUNT_PATTERN = re.compile(r"^\d{12}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_FAILURE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


class StateValidationError(RuntimeError):
    """The local cleanup state is invalid or outside this demo's boundary."""


class DemoOperationError(RuntimeError):
    """An operation failed without retaining the provider's error payload."""

    def __init__(
        self,
        stage: str,
        failure_type: str,
        cleanup_summary: Mapping[str, object] | None = None,
    ) -> None:
        self.stage = _safe_stage(stage)
        self.failure_type = _safe_failure_type_name(failure_type)
        self.cleanup_summary = _sanitize_cleanup_summary(cleanup_summary)
        super().__init__(f"{self.stage} failed ({self.failure_type}).")


@dataclass(slots=True)
class DemoState:
    schema_version: int = STATE_SCHEMA_VERSION
    project: str = PROJECT
    purpose: str = PURPOSE
    data_classification: str = DATA_CLASSIFICATION
    managed_by: str = MANAGED_BY
    region: str = REGION
    runtime_name: str = RUNTIME_NAME
    role_name: str = ROLE_NAME
    role_policy_name: str = ROLE_POLICY_NAME
    object_key: str = OBJECT_KEY
    created_at_utc: str = ""
    expires_at_utc: str = ""
    account_id: str = ""
    bucket_name: str = ""
    role_arn: str = ""
    runtime_id: str = ""
    runtime_arn: str = ""
    workload_identity_name: str = ""
    workload_identity_arn: str = ""
    log_group_name: str = ""
    log_group_arn: str = ""
    created_bucket: bool = False
    bucket_tagged: bool = False
    object_uploaded: bool = False
    created_role: bool = False
    role_tagged: bool = False
    created_runtime: bool = False
    runtime_tagged: bool = False
    created_workload_identity: bool = False
    workload_identity_tagged: bool = False
    created_log_group: bool = False
    log_group_tagged: bool = False


@dataclass(slots=True)
class _RemoteResource:
    exists: bool
    actual_name: str = ""
    tags: dict[str, str] | None = None
    account_matches: bool = False
    discovery_failed: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("UTC timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise StateValidationError("State timestamp is missing.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise StateValidationError("State timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise StateValidationError("State timestamp must use UTC.")
    return parsed.astimezone(UTC)


def _bucket_name(account_id: str) -> str:
    return f"{BUCKET_PREFIX}-{account_id}-{REGION}"


def _log_group_name(runtime_id: str) -> str:
    return f"{LOG_GROUP_PREFIX}{runtime_id}-DEFAULT"


def _log_group_arn(account_id: str, log_group_name: str) -> str:
    return f"arn:aws:logs:{REGION}:{account_id}:log-group:{log_group_name}"


def _build_tags(expires_at_utc: str) -> dict[str, str]:
    _parse_utc(expires_at_utc)
    return {
        "Project": PROJECT,
        "Purpose": PURPOSE,
        "DataClassification": DATA_CLASSIFICATION,
        "ManagedBy": MANAGED_BY,
        "ExpiresAt": expires_at_utc,
    }


def new_state(
    *,
    now: datetime | None = None,
    lifetime: timedelta = MAX_LIFETIME,
) -> DemoState:
    created = (now or _utc_now()).astimezone(UTC).replace(microsecond=0)
    if lifetime <= timedelta(0) or lifetime > MAX_LIFETIME:
        raise StateValidationError("Demo lifetime must be positive and no more than six hours.")
    state = DemoState(
        created_at_utc=_format_utc(created),
        expires_at_utc=_format_utc(created + lifetime),
    )
    validate_state(state, now=created, allow_incomplete=True)
    return state


def _arn_parts(value: str) -> list[str]:
    parts = value.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn" or not parts[1].startswith("aws"):
        raise StateValidationError("State resource identifier is invalid.")
    return parts


def _validate_arn(
    value: str,
    *,
    service: str,
    account_id: str,
    region: str | None,
) -> None:
    parts = _arn_parts(value)
    if parts[2] != service or parts[4] != account_id or (region is not None and parts[3] != region):
        raise StateValidationError("State resource identifier is outside the demo boundary.")


def _created_resource_types(state: DemoState) -> list[str]:
    flags = {
        "runtime": state.created_runtime,
        "workload_identity": state.created_workload_identity,
        "log_group": state.created_log_group,
        "iam_role": state.created_role,
        "s3_bucket": state.created_bucket,
    }
    return [resource_type for resource_type in RESOURCE_TYPES if flags[resource_type]]


def validate_state(
    state: DemoState,
    *,
    now: datetime | None = None,
    require_unexpired: bool = False,
    allow_incomplete: bool = False,
) -> None:
    expected_scalars = {
        "schema_version": STATE_SCHEMA_VERSION,
        "project": PROJECT,
        "purpose": PURPOSE,
        "data_classification": DATA_CLASSIFICATION,
        "managed_by": MANAGED_BY,
        "region": REGION,
        "runtime_name": RUNTIME_NAME,
        "role_name": ROLE_NAME,
        "role_policy_name": ROLE_POLICY_NAME,
        "object_key": OBJECT_KEY,
    }
    for name, expected in expected_scalars.items():
        if getattr(state, name) != expected:
            raise StateValidationError("State identity does not match this demo.")

    created_at = _parse_utc(state.created_at_utc)
    expires_at = _parse_utc(state.expires_at_utc)
    lifetime = expires_at - created_at
    if lifetime <= timedelta(0) or lifetime > MAX_LIFETIME:
        raise StateValidationError("State expiry exceeds the six-hour boundary.")
    current = (now or _utc_now()).astimezone(UTC)
    if created_at > current + timedelta(minutes=1):
        raise StateValidationError("State creation time is in the future.")
    if require_unexpired and expires_at <= current:
        raise StateValidationError("Demo resources have expired.")

    boolean_fields = (
        "created_bucket",
        "bucket_tagged",
        "object_uploaded",
        "created_role",
        "role_tagged",
        "created_runtime",
        "runtime_tagged",
        "created_workload_identity",
        "workload_identity_tagged",
        "created_log_group",
        "log_group_tagged",
    )
    if any(type(getattr(state, name)) is not bool for name in boolean_fields):
        raise StateValidationError("State resource flags are invalid.")

    if not state.account_id:
        if allow_incomplete and not _created_resource_types(state):
            return
        raise StateValidationError("State account boundary is missing.")
    if not _ACCOUNT_PATTERN.fullmatch(state.account_id):
        raise StateValidationError("State account boundary is invalid.")
    if state.bucket_name != _bucket_name(state.account_id):
        raise StateValidationError("State bucket name is outside the demo boundary.")

    if state.role_arn:
        _validate_arn(state.role_arn, service="iam", account_id=state.account_id, region="")
        if state.role_arn.rsplit("/", 1)[-1] != ROLE_NAME:
            raise StateValidationError("State role name is outside the demo boundary.")
    if state.runtime_id and not _IDENTIFIER_PATTERN.fullmatch(state.runtime_id):
        raise StateValidationError("State runtime identifier is invalid.")
    if state.runtime_arn:
        _validate_arn(
            state.runtime_arn,
            service="bedrock-agentcore",
            account_id=state.account_id,
            region=REGION,
        )
        runtime_resource = _arn_parts(state.runtime_arn)[5]
        if state.runtime_id and runtime_resource != f"runtime/{state.runtime_id}":
            raise StateValidationError("State Runtime name is outside the demo boundary.")
    if state.workload_identity_arn:
        _validate_arn(
            state.workload_identity_arn,
            service="bedrock-agentcore",
            account_id=state.account_id,
            region=REGION,
        )
        if state.workload_identity_arn.rsplit("/", 1)[-1] != state.workload_identity_name:
            raise StateValidationError("State workload identity name is invalid.")
    if state.workload_identity_name and not _IDENTIFIER_PATTERN.fullmatch(
        state.workload_identity_name
    ):
        raise StateValidationError("State workload identity name is invalid.")
    if state.log_group_name:
        if not state.runtime_id or state.log_group_name != _log_group_name(state.runtime_id):
            raise StateValidationError("State log group name is outside the demo boundary.")
        expected_log_arn = _log_group_arn(state.account_id, state.log_group_name)
        if state.log_group_arn != expected_log_arn:
            raise StateValidationError("State log group identifier is outside the demo boundary.")

    consistency_checks = (
        (state.bucket_tagged, state.created_bucket),
        (state.object_uploaded, state.created_bucket),
        (state.role_tagged, state.created_role),
        (state.runtime_tagged, state.created_runtime),
        (state.workload_identity_tagged, state.created_workload_identity),
        (state.log_group_tagged, state.created_log_group),
        (state.created_role, bool(state.role_arn)),
        (state.created_runtime, bool(state.runtime_id and state.runtime_arn)),
        (
            state.created_workload_identity,
            bool(state.workload_identity_name and state.workload_identity_arn),
        ),
        (state.created_log_group, bool(state.log_group_name and state.log_group_arn)),
    )
    if any(condition and not requirement for condition, requirement in consistency_checks):
        raise StateValidationError("State resource fields are inconsistent.")


def _save_state(state: DemoState) -> None:
    validate_state(state, allow_incomplete=not bool(state.account_id))
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    temporary_path = STATE_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        temporary_path.chmod(0o600)
    except OSError:
        pass
    temporary_path.replace(STATE_PATH)


def _load_state(*, required: bool = True) -> DemoState | None:
    if not STATE_PATH.is_file():
        if required:
            raise StateValidationError("No AgentCore remote MCP demo state exists.")
        return None
    try:
        if STATE_PATH.stat().st_size > 64 * 1024:
            raise StateValidationError("State file is unexpectedly large.")
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except StateValidationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StateValidationError("State file could not be loaded.") from error
    if not isinstance(payload, dict):
        raise StateValidationError("State file must contain an object.")
    expected_fields = {item.name for item in fields(DemoState)}
    if set(payload) != expected_fields:
        raise StateValidationError("State file schema is invalid.")
    try:
        state = DemoState(**payload)
    except TypeError as error:
        raise StateValidationError("State file schema is invalid.") from error
    validate_state(state)
    return state


def _remove_state() -> None:
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass


def resolve_uv_executable(executable: str | None = None) -> str:
    candidate = executable or "uv"
    resolved = shutil.which(candidate)
    if resolved is None and executable:
        explicit_path = Path(executable).expanduser()
        if explicit_path.is_file():
            resolved = str(explicit_path.resolve())
    if resolved is None:
        raise RuntimeError("uv is required to build the isolated deployment package.")
    return resolved


def build_package(
    *,
    uv_executable: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    uv_path = resolve_uv_executable(uv_executable)
    source_root = PROJECT_ROOT / "src" / "home_repair_agent"
    required_paths = (ENTRYPOINT_PATH, REQUIREMENTS_PATH, source_root)
    if any(not path.exists() for path in required_paths):
        raise RuntimeError("Remote MCP deployment sources are incomplete.")

    package_dir = BUILD_ROOT / "package"
    archive = BUILD_ROOT / "deployment.zip"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    archive.unlink(missing_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    runner(
        [
            uv_path,
            "pip",
            "install",
            "--target",
            str(package_dir),
            "--python-version",
            "3.12",
            "--python-platform",
            "aarch64-manylinux2014",
            "--only-binary",
            ":all:",
            "--upgrade",
            "-r",
            str(REQUIREMENTS_PATH),
        ],
        check=True,
    )
    shutil.rmtree(package_dir / "bin", ignore_errors=True)
    shutil.rmtree(package_dir / "boto3" / "examples", ignore_errors=True)
    botocore_data = package_dir / "botocore" / "data"
    if botocore_data.exists():
        for example_file in botocore_data.rglob("examples-1.json"):
            example_file.unlink()

    shutil.copy2(ENTRYPOINT_PATH, package_dir / ENTRYPOINT_PATH.name)
    shutil.copy2(REQUIREMENTS_PATH, package_dir / REQUIREMENTS_PATH.name)
    shutil.copytree(
        source_root,
        package_dir / "home_repair_agent",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(package_dir).as_posix())
    if archive.stat().st_size > 250 * 1024 * 1024:
        raise RuntimeError("AgentCore deployment archive exceeds 250 MiB.")
    return archive


def _aws_clients(*, region: str = REGION) -> dict[str, Any]:
    config = Config(connect_timeout=10, read_timeout=180, retries={"max_attempts": 1})
    session = boto3.Session(region_name=region)
    return {
        "sts": session.client("sts", config=config),
        "iam": session.client("iam", config=config),
        "s3": session.client("s3", config=config),
        "control": session.client("bedrock-agentcore-control", config=config),
        "logs": session.client("logs", config=config),
    }


def _build_trust_policy(account_id: str) -> dict[str, object]:
    if not _ACCOUNT_PATTERN.fullmatch(account_id):
        raise StateValidationError("AWS account boundary is invalid.")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AgentCoreRuntimeAssumeRole",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": (f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:*")
                    },
                },
            }
        ],
    }


def _build_execution_policy(account_id: str) -> dict[str, object]:
    if not _ACCOUNT_PATTERN.fullmatch(account_id):
        raise StateValidationError("AWS account boundary is invalid.")
    log_group_arn = f"arn:aws:logs:{REGION}:{account_id}:log-group:{LOG_GROUP_PREFIX}*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AgentCoreRuntimeLogWrite",
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogStreams",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": [log_group_arn, f"{log_group_arn}:log-stream:*"],
            },
            {
                "Sid": "AgentCoreRuntimeMetrics",
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
        ],
    }


def _tag_list(tags: Mapping[str, str]) -> list[dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in tags.items()]


def _build_role_request(state: DemoState) -> dict[str, object]:
    tags = _build_tags(state.expires_at_utc)
    return {
        "RoleName": ROLE_NAME,
        "AssumeRolePolicyDocument": json.dumps(_build_trust_policy(state.account_id)),
        "Description": "Ephemeral synthetic-only AgentCore remote MCP demo role",
        "Tags": _tag_list(tags),
    }


def _build_bucket_tagging(state: DemoState) -> dict[str, object]:
    return {"TagSet": _tag_list(_build_tags(state.expires_at_utc))}


def _build_log_group_request(state: DemoState) -> dict[str, object]:
    return {
        "logGroupName": state.log_group_name,
        "tags": _build_tags(state.expires_at_utc),
    }


def _build_object_upload_args(state: DemoState) -> dict[str, str]:
    return {
        "ServerSideEncryption": "AES256",
        "Tagging": urlencode(list(_build_tags(state.expires_at_utc).items())),
        "ExpectedBucketOwner": state.account_id,
    }


def _remaining_lifetime_seconds(state: DemoState, *, now: datetime | None = None) -> int:
    remaining = int((_parse_utc(state.expires_at_utc) - (now or _utc_now())).total_seconds())
    if remaining < 60:
        raise StateValidationError("Insufficient safe lifetime remains for deployment.")
    return min(remaining, MAX_LIFETIME_SECONDS)


def _build_runtime_request(
    state: DemoState,
    *,
    now: datetime | None = None,
    client_token: str | None = None,
) -> dict[str, object]:
    return {
        "agentRuntimeName": RUNTIME_NAME,
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "code": {"s3": {"bucket": state.bucket_name, "prefix": OBJECT_KEY}},
                "runtime": "PYTHON_3_12",
                "entryPoint": [ENTRYPOINT_PATH.name],
            }
        },
        "roleArn": state.role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "MCP"},
        "lifecycleConfiguration": {
            "idleRuntimeSessionTimeout": 900,
            "maxLifetime": _remaining_lifetime_seconds(state, now=now),
        },
        "description": "Ephemeral synthetic-only nw_p AgentCore remote MCP demo",
        "tags": _build_tags(state.expires_at_utc),
        "clientToken": client_token or f"nwp-remotemcp-{uuid.uuid4().hex}",
    }


def _error_code(error: BaseException) -> str:
    if isinstance(error, ClientError):
        response = error.response
        if isinstance(response, dict):
            details = response.get("Error")
            if isinstance(details, dict):
                code = details.get("Code")
                if isinstance(code, str):
                    return code
    return ""


def _is_not_found(error: BaseException) -> bool:
    return _error_code(error) in _NOT_FOUND_CODES


def _assert_exact_tags(actual: Mapping[str, str], expected: Mapping[str, str]) -> None:
    if dict(actual) != dict(expected):
        raise RuntimeError("AWS resource tags do not match the demo boundary.")


def _tags_from_list(items: object) -> dict[str, str]:
    if not isinstance(items, list):
        raise TypeError("AWS resource tags are unavailable.")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise TypeError("AWS resource tags are invalid.")
        key = item.get("Key")
        value = item.get("Value")
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("AWS resource tags are invalid.")
        result[key] = value
    return result


def _ensure_no_collisions(clients: Mapping[str, Any], state: DemoState) -> None:
    runtimes = clients["control"].list_agent_runtimes().get("agentRuntimes", [])
    if any(
        isinstance(item, dict) and item.get("agentRuntimeName") == RUNTIME_NAME for item in runtimes
    ):
        raise RuntimeError("A deterministic Runtime name is already in use.")

    try:
        clients["iam"].get_role(RoleName=ROLE_NAME)
    except ClientError as error:
        if not _is_not_found(error):
            raise
    else:
        raise RuntimeError("A deterministic IAM role name is already in use.")

    try:
        clients["s3"].head_bucket(
            Bucket=state.bucket_name,
            ExpectedBucketOwner=state.account_id,
        )
    except ClientError as error:
        if not _is_not_found(error):
            raise
    else:
        raise RuntimeError("A deterministic S3 bucket name is already in use.")


def _create_role(clients: Mapping[str, Any], state: DemoState) -> None:
    iam = clients["iam"]
    response = iam.create_role(**_build_role_request(state))
    role = response.get("Role")
    role_arn = role.get("Arn") if isinstance(role, dict) else None
    if not isinstance(role_arn, str):
        raise TypeError("IAM role creation returned no identifier.")
    state.role_arn = role_arn
    state.created_role = True
    _save_state(state)
    _validate_arn(role_arn, service="iam", account_id=state.account_id, region="")
    actual_tags = _tags_from_list(iam.list_role_tags(RoleName=ROLE_NAME).get("Tags"))
    _assert_exact_tags(actual_tags, _build_tags(state.expires_at_utc))
    state.role_tagged = True
    _save_state(state)
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=ROLE_POLICY_NAME,
        PolicyDocument=json.dumps(_build_execution_policy(state.account_id)),
    )


def _create_bucket_and_upload(
    clients: Mapping[str, Any],
    state: DemoState,
    archive: Path,
) -> None:
    s3 = clients["s3"]
    s3.create_bucket(
        Bucket=state.bucket_name,
        CreateBucketConfiguration={"LocationConstraint": REGION},
    )
    state.created_bucket = True
    _save_state(state)

    s3.put_bucket_tagging(Bucket=state.bucket_name, Tagging=_build_bucket_tagging(state))
    actual_tags = _tags_from_list(
        s3.get_bucket_tagging(
            Bucket=state.bucket_name,
            ExpectedBucketOwner=state.account_id,
        ).get("TagSet")
    )
    _assert_exact_tags(actual_tags, _build_tags(state.expires_at_utc))
    state.bucket_tagged = True
    _save_state(state)

    s3.put_public_access_block(
        Bucket=state.bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
        ExpectedBucketOwner=state.account_id,
    )
    s3.put_bucket_ownership_controls(
        Bucket=state.bucket_name,
        OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        ExpectedBucketOwner=state.account_id,
    )
    s3.put_bucket_encryption(
        Bucket=state.bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    "BucketKeyEnabled": False,
                }
            ]
        },
        ExpectedBucketOwner=state.account_id,
    )
    s3.put_bucket_lifecycle_configuration(
        Bucket=state.bucket_name,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expire-remote-mcp-artifacts-after-one-day",
                    "Status": "Enabled",
                    "Filter": {"Prefix": f"{RUNTIME_NAME}/"},
                    "Expiration": {"Days": 1},
                    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                }
            ]
        },
        ExpectedBucketOwner=state.account_id,
    )
    s3.upload_file(
        str(archive),
        state.bucket_name,
        OBJECT_KEY,
        ExtraArgs=_build_object_upload_args(state),
    )
    head = s3.head_object(
        Bucket=state.bucket_name,
        Key=OBJECT_KEY,
        ExpectedBucketOwner=state.account_id,
    )
    if head.get("ServerSideEncryption") != "AES256":
        raise RuntimeError("Deployment object encryption could not be verified.")
    object_tags = _tags_from_list(
        s3.get_object_tagging(
            Bucket=state.bucket_name,
            Key=OBJECT_KEY,
            ExpectedBucketOwner=state.account_id,
        ).get("TagSet")
    )
    _assert_exact_tags(object_tags, _build_tags(state.expires_at_utc))
    state.object_uploaded = True
    _save_state(state)


def _set_exact_log_tags(logs: Any, state: DemoState) -> None:
    expected = _build_tags(state.expires_at_utc)
    response = logs.list_tags_log_group(logGroupName=state.log_group_name)
    existing = response.get("tags", {})
    if not isinstance(existing, dict):
        raise TypeError("Log group tags are unavailable.")
    extra_keys = sorted(set(existing) - set(expected))
    if extra_keys:
        logs.untag_log_group(logGroupName=state.log_group_name, tags=extra_keys)
    logs.tag_log_group(logGroupName=state.log_group_name, tags=expected)
    verified = logs.list_tags_log_group(logGroupName=state.log_group_name).get("tags", {})
    if not isinstance(verified, dict):
        raise TypeError("Log group tags are unavailable.")
    _assert_exact_tags(verified, expected)


def _create_runtime_and_log_group(clients: Mapping[str, Any], state: DemoState) -> None:
    control = clients["control"]
    response = control.create_agent_runtime(**_build_runtime_request(state))
    runtime_id = response.get("agentRuntimeId")
    runtime_arn = response.get("agentRuntimeArn")
    if not isinstance(runtime_id, str) or not isinstance(runtime_arn, str):
        raise TypeError("Runtime creation returned no identifier.")
    state.runtime_id = runtime_id
    state.runtime_arn = runtime_arn
    state.created_runtime = True

    identity_details = response.get("workloadIdentityDetails", {})
    identity_arn = (
        identity_details.get("workloadIdentityArn") if isinstance(identity_details, dict) else None
    )
    if isinstance(identity_arn, str) and identity_arn:
        state.workload_identity_arn = identity_arn
        state.workload_identity_name = identity_arn.rsplit("/", 1)[-1]
        state.created_workload_identity = True

    state.log_group_name = _log_group_name(runtime_id)
    state.log_group_arn = _log_group_arn(state.account_id, state.log_group_name)
    # AgentCore may create this deterministic group before the deployer reaches it.
    # Track it immediately so every post-create failure can discover and remove it.
    state.created_log_group = True
    _save_state(state)
    validate_state(state)

    runtime_tags = control.list_tags_for_resource(resourceArn=runtime_arn).get("tags", {})
    if not isinstance(runtime_tags, dict):
        raise TypeError("Runtime tags are unavailable.")
    _assert_exact_tags(runtime_tags, _build_tags(state.expires_at_utc))
    state.runtime_tagged = True
    _save_state(state)

    if state.created_workload_identity:
        control.tag_resource(
            resourceArn=state.workload_identity_arn,
            tags=_build_tags(state.expires_at_utc),
        )
        identity_tags = control.list_tags_for_resource(resourceArn=state.workload_identity_arn).get(
            "tags", {}
        )
        if not isinstance(identity_tags, dict):
            raise RuntimeError("Workload identity tags are unavailable.")
        _assert_exact_tags(identity_tags, _build_tags(state.expires_at_utc))
        state.workload_identity_tagged = True
        _save_state(state)

    logs = clients["logs"]
    try:
        logs.create_log_group(**_build_log_group_request(state))
    except ClientError as error:
        if _error_code(error) != "ResourceAlreadyExistsException":
            raise
    state.created_log_group = True
    _save_state(state)
    _set_exact_log_tags(logs, state)
    logs.put_retention_policy(logGroupName=state.log_group_name, retentionInDays=1)
    state.log_group_tagged = True
    _save_state(state)
    _wait_for_runtime(control, runtime_id, expected="READY")


def _wait_for_runtime(
    control: Any,
    runtime_id: str,
    *,
    expected: str,
    timeout_seconds: float = 600,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = control.get_agent_runtime(agentRuntimeId=runtime_id)
        except ClientError as error:
            if expected == "DELETED" and _is_not_found(error):
                return
            raise
        status = response.get("status")
        if status == expected:
            return
        if status in {"CREATE_FAILED", "UPDATE_FAILED"}:
            raise RuntimeError("AgentCore Runtime entered a failure state.")
        sleep(5)
    raise TimeoutError("AgentCore Runtime did not reach the expected state.")


def _deploy_impl(
    archive: Path,
    state: DemoState,
    clients: Mapping[str, Any],
) -> DemoState:
    if not archive.is_file():
        raise RuntimeError("Deployment archive is unavailable.")
    account_id = clients["sts"].get_caller_identity().get("Account")
    if not isinstance(account_id, str) or not _ACCOUNT_PATTERN.fullmatch(account_id):
        raise RuntimeError("AWS caller identity is invalid.")
    state.account_id = account_id
    state.bucket_name = _bucket_name(account_id)
    validate_state(state, require_unexpired=True)
    _save_state(state)
    _ensure_no_collisions(clients, state)
    _create_role(clients, state)
    _create_bucket_and_upload(clients, state, archive)
    _create_runtime_and_log_group(clients, state)
    validate_state(state, require_unexpired=True)
    _save_state(state)
    return state


def _safe_failure_type_name(value: str) -> str:
    if isinstance(value, str) and _SAFE_FAILURE_TYPE_PATTERN.fullmatch(value):
        return value
    return "OperationError"


def _failure_type(error: BaseException) -> str:
    return _safe_failure_type_name(type(error).__name__)


def _safe_stage(stage: str | None) -> str | None:
    allowed = {"plan", "package", "deploy", "invoke", "status", "cleanup", "run"}
    return stage if stage in allowed else None


def _sanitize_cleanup_summary(
    summary: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(summary, Mapping):
        return {
            "status": "not-needed",
            "attempted_resource_types": [],
            "failed_resource_types": [],
            "remaining_resource_types": [],
        }
    status = summary.get("status")
    if status not in {"passed", "partial", "retained", "not-needed"}:
        status = "partial"

    def safe_resources(key: str) -> list[str]:
        values = summary.get(key)
        if not isinstance(values, (list, tuple, set, frozenset)):
            return []
        selected = {value for value in values if value in RESOURCE_TYPES}
        return [resource_type for resource_type in RESOURCE_TYPES if resource_type in selected]

    return {
        "status": status,
        "attempted_resource_types": safe_resources("attempted_resource_types"),
        "failed_resource_types": safe_resources("failed_resource_types"),
        "remaining_resource_types": safe_resources("remaining_resource_types"),
    }


def _safe_elapsed_ms(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return 0.0
    return round(float(value), 3)


def _sanitize_report_invocation(
    invocation: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(invocation, Mapping):
        return {"tool_names": [], "redacted_trace": [], "provenance": {}}
    names_input = invocation.get("tool_names")
    names = (
        sorted({name for name in names_input if name in EXPECTED_TOOL_NAMES})
        if isinstance(names_input, (list, tuple, set, frozenset))
        else []
    )
    trace_input = invocation.get("redacted_trace")
    trace: list[dict[str, object]] = []
    if isinstance(trace_input, list):
        for item in trace_input:
            if not isinstance(item, Mapping) or item.get("name") not in EXPECTED_TOOL_NAMES:
                continue
            provenance = item.get("provenance")
            trace.append(
                {
                    "name": item["name"],
                    "status": "passed" if item.get("status") == "passed" else "failed",
                    "elapsed_ms": _safe_elapsed_ms(item.get("elapsed_ms")),
                    "provenance": (provenance if provenance in TRACE_PROVENANCE else "redacted"),
                }
            )
    provenance_input = invocation.get("provenance")
    provenance = (
        {
            key: provenance_input.get(key) is True
            for key in sorted(PROVENANCE_KEYS)
            if key in provenance_input
        }
        if isinstance(provenance_input, Mapping)
        else {}
    )
    return {
        "tool_names": names,
        "redacted_trace": trace,
        "provenance": provenance,
    }


def _sanitize_invocation(result: object) -> dict[str, object]:
    if not isinstance(result, dict) or result.get("status") != "passed":
        raise RuntimeError("Remote MCP synthetic flow did not pass.")
    tool_names = result.get("tool_names")
    if (
        not isinstance(tool_names, list)
        or len(tool_names) != len(EXPECTED_TOOL_NAMES)
        or set(tool_names) != EXPECTED_TOOL_NAMES
    ):
        raise RuntimeError("Remote MCP synthetic flow exposed an unexpected tool set.")

    trace = result.get("trace")
    if not isinstance(trace, list):
        raise TypeError("Remote MCP synthetic flow returned no trace.")
    if len(trace) != len(EXPECTED_TOOL_FLOW):
        raise RuntimeError("Remote MCP synthetic flow returned an incomplete trace.")
    redacted_trace: list[dict[str, object]] = []
    for expected_name, item in zip(EXPECTED_TOOL_FLOW, trace, strict=True):
        if (
            not isinstance(item, dict)
            or item.get("name") != expected_name
            or item.get("status") != "passed"
        ):
            raise RuntimeError("Remote MCP synthetic flow returned an invalid trace.")
        elapsed = item.get("elapsed_ms")
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0:
            raise TypeError("Remote MCP synthetic flow returned invalid timing evidence.")
        provenance = item.get("provenance")
        if provenance not in TRACE_PROVENANCE:
            raise RuntimeError("Remote MCP synthetic flow returned invalid provenance.")
        redacted_trace.append(
            {
                "name": expected_name,
                "status": "passed",
                "elapsed_ms": round(float(elapsed), 3),
                "provenance": provenance,
            }
        )

    provenance_input = result.get("provenance")
    if not isinstance(provenance_input, dict):
        raise TypeError("Remote MCP synthetic provenance is unavailable.")
    provenance = {key: provenance_input.get(key) is True for key in sorted(PROVENANCE_KEYS)}
    if not all(provenance.values()):
        raise RuntimeError("Remote MCP synthetic provenance did not pass.")
    return {
        "tool_names": sorted(EXPECTED_TOOL_NAMES),
        "redacted_trace": redacted_trace,
        "provenance": provenance,
    }


def _build_report(
    *,
    status: str,
    state: DemoState,
    started_at_utc: str,
    finished_at_utc: str,
    invocation: Mapping[str, object] | None = None,
    failure_stage: str | None = None,
    failure_type: str | None = None,
    cleanup_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    safe_invocation = _sanitize_report_invocation(invocation)
    return {
        "status": status if status in {"passed", "failed", "deployed", "cleaned"} else "failed",
        "started_at_utc": _format_utc(_parse_utc(started_at_utc)),
        "finished_at_utc": _format_utc(_parse_utc(finished_at_utc)),
        "region": REGION,
        "runtime_name": RUNTIME_NAME,
        "expires_at_utc": state.expires_at_utc,
        "tags": _build_tags(state.expires_at_utc),
        "tool_names": safe_invocation["tool_names"],
        "redacted_trace": safe_invocation["redacted_trace"],
        "provenance": safe_invocation["provenance"],
        "failure_stage": _safe_stage(failure_stage),
        "failure_type": (
            _safe_failure_type_name(failure_type) if failure_type is not None else None
        ),
        "cleanup_summary": _sanitize_cleanup_summary(cleanup_summary),
    }


def _write_report(report: Mapping[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cleanup_after_failure(
    state: DemoState,
    *,
    clients: Mapping[str, Any] | None,
    cleanup_fn: Callable[[DemoState], Mapping[str, object]] | None,
) -> dict[str, object]:
    try:
        if cleanup_fn is not None:
            return _sanitize_cleanup_summary(cleanup_fn(state))
        return _sanitize_cleanup_summary(cleanup(state, clients=clients, allow_incomplete=True))
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _sanitize_cleanup_summary(
            {
                "status": "partial",
                "failed_resource_types": _created_resource_types(state),
                "remaining_resource_types": _created_resource_types(state),
            }
        )


def deploy(
    archive: Path,
    state: DemoState | None = None,
    *,
    clients: Mapping[str, Any] | None = None,
    cleanup_fn: Callable[[DemoState], Mapping[str, object]] | None = None,
) -> DemoState:
    active_state = state or new_state()
    started_at = _format_utc(_utc_now())
    resolved_clients = clients
    try:
        resolved_clients = resolved_clients or _aws_clients(region=active_state.region)
        return _deploy_impl(archive, active_state, resolved_clients)
    except Exception as error:  # noqa: BLE001 - cleanup/report boundary
        cleanup_summary = _cleanup_after_failure(
            active_state,
            clients=resolved_clients,
            cleanup_fn=cleanup_fn,
        )
        report = _build_report(
            status="failed",
            state=active_state,
            started_at_utc=started_at,
            finished_at_utc=_format_utc(_utc_now()),
            failure_stage="deploy",
            failure_type=_failure_type(error),
            cleanup_summary=cleanup_summary,
        )
        _write_report(report)
        raise DemoOperationError("deploy", _failure_type(error), cleanup_summary) from None


def _load_client_module() -> ModuleType:
    module_name = "_agentcore_remote_mcp_client_for_demo"
    spec = importlib.util.spec_from_file_location(module_name, CLIENT_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Remote MCP client module is unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _run_coroutine(coroutine: Any) -> object:
    return asyncio.run(coroutine)


def _invoke_remote_mcp(
    state: DemoState,
    *,
    session: boto3.Session | None = None,
    client_module: ModuleType | None = None,
) -> object:
    module = client_module or _load_client_module()
    scenario = module.load_synthetic_flow(FIXTURE_PATH)
    boto_session = session or boto3.Session(region_name=state.region)
    auth = module.AgentCoreSigV4Auth.from_boto3_session(
        boto_session,
        region=state.region,
    )
    invocation_url = module.build_agentcore_invocation_url(
        runtime_arn=state.runtime_arn,
        region=state.region,
    )
    return _run_coroutine(
        module.run_read_only_flow(
            url=invocation_url,
            scenario=scenario,
            auth=auth,
            authentication_label="iam-sigv4",
            timeout_seconds=60,
        )
    )


def invoke(
    state: DemoState | None = None,
    *,
    session: boto3.Session | None = None,
    client_module: ModuleType | None = None,
    flow_runner: Callable[[DemoState], object] | None = None,
    cleanup_fn: Callable[[DemoState], Mapping[str, object]] | None = None,
    cleanup_clients: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    active_state = state or _load_state()
    if active_state is None:
        raise StateValidationError("No AgentCore remote MCP demo state exists.")
    started_at = _format_utc(_utc_now())
    try:
        validate_state(active_state, require_unexpired=True)
        raw_result = (
            flow_runner(active_state)
            if flow_runner is not None
            else _invoke_remote_mcp(
                active_state,
                session=session,
                client_module=client_module,
            )
        )
        invocation = _sanitize_invocation(raw_result)
    except Exception as error:  # noqa: BLE001 - cleanup/report boundary
        cleanup_summary = _cleanup_after_failure(
            active_state,
            clients=cleanup_clients,
            cleanup_fn=cleanup_fn,
        )
        report = _build_report(
            status="failed",
            state=active_state,
            started_at_utc=started_at,
            finished_at_utc=_format_utc(_utc_now()),
            failure_stage="invoke",
            failure_type=_failure_type(error),
            cleanup_summary=cleanup_summary,
        )
        _write_report(report)
        raise DemoOperationError("invoke", _failure_type(error), cleanup_summary) from None

    retained_summary = {
        "status": "retained",
        "attempted_resource_types": [],
        "failed_resource_types": [],
        "remaining_resource_types": _created_resource_types(active_state),
    }
    report = _build_report(
        status="passed",
        state=active_state,
        started_at_utc=started_at,
        finished_at_utc=_format_utc(_utc_now()),
        invocation=invocation,
        cleanup_summary=retained_summary,
    )
    _write_report(report)
    return report


def _purpose_tags_match(tags: Mapping[str, str] | None, state: DemoState) -> bool:
    if not isinstance(tags, Mapping):
        return False
    expected = _build_tags(state.expires_at_utc)
    return (
        tags.get("Purpose") == expected["Purpose"]
        and tags.get("ManagedBy") == expected["ManagedBy"]
    )


def _arn_matches_account(value: str, account_id: str) -> bool:
    try:
        return _arn_parts(value)[4] == account_id
    except StateValidationError:
        return False


def _discover_runtime(clients: Mapping[str, Any], state: DemoState) -> _RemoteResource:
    if not state.created_runtime:
        return _RemoteResource(False)
    try:
        response = clients["control"].get_agent_runtime(agentRuntimeId=state.runtime_id)
    except ClientError as error:
        if _is_not_found(error):
            return _RemoteResource(False)
        return _RemoteResource(True, discovery_failed=True)
    except Exception:  # noqa: BLE001 - provider discovery must fail closed
        return _RemoteResource(True, discovery_failed=True)
    arn = response.get("agentRuntimeArn", state.runtime_arn)
    name = response.get("agentRuntimeName", "")
    try:
        tags = clients["control"].list_tags_for_resource(resourceArn=arn).get("tags", {})
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _RemoteResource(True, actual_name=str(name), discovery_failed=True)
    return _RemoteResource(
        True,
        actual_name=name if isinstance(name, str) else "",
        tags=tags if isinstance(tags, dict) else None,
        account_matches=isinstance(arn, str) and _arn_matches_account(arn, state.account_id),
    )


def _discover_identity(clients: Mapping[str, Any], state: DemoState) -> _RemoteResource:
    if not state.created_workload_identity:
        return _RemoteResource(False)
    try:
        items = clients["control"].list_workload_identities().get("workloadIdentities", [])
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _RemoteResource(True, discovery_failed=True)
    match = next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("name") == state.workload_identity_name
        ),
        None,
    )
    if match is None:
        return _RemoteResource(False)
    arn = match.get("workloadIdentityArn", state.workload_identity_arn)
    try:
        tags = clients["control"].list_tags_for_resource(resourceArn=arn).get("tags", {})
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _RemoteResource(
            True,
            actual_name=state.workload_identity_name,
            discovery_failed=True,
        )
    return _RemoteResource(
        True,
        actual_name=str(match.get("name", "")),
        tags=tags if isinstance(tags, dict) else None,
        account_matches=isinstance(arn, str) and _arn_matches_account(arn, state.account_id),
    )


def _discover_log_group(clients: Mapping[str, Any], state: DemoState) -> _RemoteResource:
    if not state.created_log_group:
        return _RemoteResource(False)
    try:
        response = clients["logs"].list_tags_log_group(logGroupName=state.log_group_name)
    except ClientError as error:
        if _is_not_found(error):
            return _RemoteResource(False)
        return _RemoteResource(True, discovery_failed=True)
    except Exception:  # noqa: BLE001 - provider discovery must fail closed
        return _RemoteResource(True, discovery_failed=True)
    tags = response.get("tags", {})
    return _RemoteResource(
        True,
        actual_name=state.log_group_name,
        tags=tags if isinstance(tags, dict) else None,
        account_matches=_arn_matches_account(state.log_group_arn, state.account_id),
    )


def _discover_role(clients: Mapping[str, Any], state: DemoState) -> _RemoteResource:
    if not state.created_role:
        return _RemoteResource(False)
    try:
        response = clients["iam"].get_role(RoleName=ROLE_NAME)
    except ClientError as error:
        if _is_not_found(error):
            return _RemoteResource(False)
        return _RemoteResource(True, discovery_failed=True)
    except Exception:  # noqa: BLE001 - provider discovery must fail closed
        return _RemoteResource(True, discovery_failed=True)
    role = response.get("Role", {})
    arn = role.get("Arn", state.role_arn) if isinstance(role, dict) else state.role_arn
    name = role.get("RoleName", "") if isinstance(role, dict) else ""
    try:
        tags = _tags_from_list(clients["iam"].list_role_tags(RoleName=ROLE_NAME).get("Tags"))
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _RemoteResource(True, actual_name=str(name), discovery_failed=True)
    return _RemoteResource(
        True,
        actual_name=name if isinstance(name, str) else "",
        tags=tags,
        account_matches=isinstance(arn, str) and _arn_matches_account(arn, state.account_id),
    )


def _discover_bucket(clients: Mapping[str, Any], state: DemoState) -> _RemoteResource:
    if not state.created_bucket:
        return _RemoteResource(False)
    try:
        clients["s3"].head_bucket(
            Bucket=state.bucket_name,
            ExpectedBucketOwner=state.account_id,
        )
    except ClientError as error:
        if _is_not_found(error):
            return _RemoteResource(False)
        return _RemoteResource(True, discovery_failed=True)
    except Exception:  # noqa: BLE001 - provider discovery must fail closed
        return _RemoteResource(True, discovery_failed=True)
    try:
        tags = _tags_from_list(
            clients["s3"]
            .get_bucket_tagging(
                Bucket=state.bucket_name,
                ExpectedBucketOwner=state.account_id,
            )
            .get("TagSet")
        )
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _RemoteResource(True, actual_name=state.bucket_name, discovery_failed=True)
    return _RemoteResource(
        True,
        actual_name=state.bucket_name,
        tags=tags,
        account_matches=state.bucket_name == _bucket_name(state.account_id),
    )


def _cleanup_authorized(
    remote: _RemoteResource,
    *,
    state: DemoState,
    expected_name: str,
    created: bool,
    tagged: bool,
) -> bool:
    if not remote.exists:
        return True
    if remote.discovery_failed or not created:
        return False
    if remote.actual_name != expected_name or not remote.account_matches:
        return False
    if _purpose_tags_match(remote.tags, state):
        return True
    return not tagged


def _delete_runtime(clients: Mapping[str, Any], state: DemoState) -> None:
    clients["control"].delete_agent_runtime(agentRuntimeId=state.runtime_id)
    _wait_for_runtime(clients["control"], state.runtime_id, expected="DELETED")


def _delete_identity(clients: Mapping[str, Any], state: DemoState) -> None:
    clients["control"].delete_workload_identity(name=state.workload_identity_name)


def _delete_log_group(clients: Mapping[str, Any], state: DemoState) -> None:
    clients["logs"].delete_log_group(logGroupName=state.log_group_name)


def _delete_role(clients: Mapping[str, Any], state: DemoState) -> None:
    iam = clients["iam"]
    try:
        iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=ROLE_POLICY_NAME)
    except ClientError as error:
        if not _is_not_found(error):
            raise
    iam.delete_role(RoleName=ROLE_NAME)


def _empty_and_delete_bucket(clients: Mapping[str, Any], state: DemoState) -> None:
    s3 = clients["s3"]
    continuation_token: str | None = None
    while True:
        request: dict[str, object] = {
            "Bucket": state.bucket_name,
            "ExpectedBucketOwner": state.account_id,
        }
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = s3.list_objects_v2(**request)
        objects = [
            {"Key": item["Key"]}
            for item in response.get("Contents", [])
            if isinstance(item, dict) and isinstance(item.get("Key"), str)
        ]
        if objects:
            s3.delete_objects(
                Bucket=state.bucket_name,
                Delete={"Objects": objects, "Quiet": True},
                ExpectedBucketOwner=state.account_id,
            )
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
        if not isinstance(token, str) or not token:
            raise RuntimeError("S3 cleanup pagination is invalid.")
        continuation_token = token
    s3.delete_bucket(Bucket=state.bucket_name, ExpectedBucketOwner=state.account_id)


def _resource_exists(
    resource_type: str,
    clients: Mapping[str, Any],
    state: DemoState,
) -> bool:
    if resource_type == "runtime":
        try:
            clients["control"].get_agent_runtime(agentRuntimeId=state.runtime_id)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True
    if resource_type == "workload_identity":
        items = clients["control"].list_workload_identities().get("workloadIdentities", [])
        return any(
            isinstance(item, dict) and item.get("name") == state.workload_identity_name
            for item in items
        )
    if resource_type == "log_group":
        try:
            clients["logs"].list_tags_log_group(logGroupName=state.log_group_name)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True
    if resource_type == "iam_role":
        try:
            clients["iam"].get_role(RoleName=ROLE_NAME)
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True
    if resource_type == "s3_bucket":
        try:
            clients["s3"].head_bucket(
                Bucket=state.bucket_name,
                ExpectedBucketOwner=state.account_id,
            )
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True
    raise ValueError("Unknown cleanup resource type.")


def cleanup(
    state: DemoState | None = None,
    *,
    clients: Mapping[str, Any] | None = None,
    allow_incomplete: bool = False,
) -> dict[str, object]:
    active_state = state or _load_state(required=False)
    if active_state is None:
        return _sanitize_cleanup_summary({"status": "not-needed"})
    validate_state(active_state, allow_incomplete=allow_incomplete)
    managed_types = _created_resource_types(active_state)
    if not managed_types:
        return _sanitize_cleanup_summary({"status": "not-needed"})
    if not active_state.account_id:
        return _sanitize_cleanup_summary(
            {
                "status": "partial",
                "failed_resource_types": managed_types,
                "remaining_resource_types": managed_types,
            }
        )

    resolved_clients = clients
    try:
        resolved_clients = resolved_clients or _aws_clients(region=active_state.region)
        caller_account = resolved_clients["sts"].get_caller_identity().get("Account")
    except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
        return _sanitize_cleanup_summary(
            {
                "status": "partial",
                "failed_resource_types": managed_types,
                "remaining_resource_types": managed_types,
            }
        )
    if caller_account != active_state.account_id:
        return _sanitize_cleanup_summary(
            {
                "status": "partial",
                "failed_resource_types": managed_types,
                "remaining_resource_types": managed_types,
            }
        )

    discovery = {
        "runtime": _discover_runtime(resolved_clients, active_state),
        "workload_identity": _discover_identity(resolved_clients, active_state),
        "log_group": _discover_log_group(resolved_clients, active_state),
        "iam_role": _discover_role(resolved_clients, active_state),
        "s3_bucket": _discover_bucket(resolved_clients, active_state),
    }
    expected_names = {
        "runtime": RUNTIME_NAME,
        "workload_identity": active_state.workload_identity_name,
        "log_group": active_state.log_group_name,
        "iam_role": ROLE_NAME,
        "s3_bucket": active_state.bucket_name,
    }
    created_flags = {
        "runtime": active_state.created_runtime,
        "workload_identity": active_state.created_workload_identity,
        "log_group": active_state.created_log_group,
        "iam_role": active_state.created_role,
        "s3_bucket": active_state.created_bucket,
    }
    tagged_flags = {
        "runtime": active_state.runtime_tagged,
        "workload_identity": active_state.workload_identity_tagged,
        "log_group": active_state.log_group_tagged,
        "iam_role": active_state.role_tagged,
        "s3_bucket": active_state.bucket_tagged,
    }
    authorized = {
        resource_type: _cleanup_authorized(
            discovery[resource_type],
            state=active_state,
            expected_name=expected_names[resource_type],
            created=created_flags[resource_type],
            tagged=tagged_flags[resource_type],
        )
        for resource_type in RESOURCE_TYPES
    }

    delete_functions: dict[str, Callable[[Mapping[str, Any], DemoState], None]] = {
        "runtime": _delete_runtime,
        "workload_identity": _delete_identity,
        "log_group": _delete_log_group,
        "iam_role": _delete_role,
        "s3_bucket": _empty_and_delete_bucket,
    }
    attempted: list[str] = []
    failed: set[str] = set()
    for resource_type in RESOURCE_TYPES:
        remote = discovery[resource_type]
        if not remote.exists:
            continue
        if not authorized[resource_type]:
            failed.add(resource_type)
            continue
        attempted.append(resource_type)
        try:
            delete_functions[resource_type](resolved_clients, active_state)
        except ClientError as error:
            if not _is_not_found(error):
                failed.add(resource_type)
        except (RuntimeError, TimeoutError):
            failed.add(resource_type)
        except Exception:  # noqa: BLE001 - continue and verify every resource
            failed.add(resource_type)

    remaining: set[str] = set()
    for resource_type in managed_types:
        try:
            if _resource_exists(resource_type, resolved_clients, active_state):
                remaining.add(resource_type)
        except Exception:  # noqa: BLE001 - provider boundary must remain payload-free
            failed.add(resource_type)
            remaining.add(resource_type)

    status = "passed" if not failed and not remaining else "partial"
    summary = _sanitize_cleanup_summary(
        {
            "status": status,
            "attempted_resource_types": attempted,
            "failed_resource_types": failed,
            "remaining_resource_types": remaining,
        }
    )
    if status == "passed":
        _remove_state()
    return summary


def plan(state: DemoState | None = None) -> dict[str, object]:
    active_state = state or new_state()
    validate_state(active_state, allow_incomplete=not bool(active_state.account_id))
    return {
        "status": "planned",
        "region": REGION,
        "runtime_name": RUNTIME_NAME,
        "expires_at_utc": active_state.expires_at_utc,
        "tags": _build_tags(active_state.expires_at_utc),
        "cleanup_command": "python scripts/agentcore_remote_mcp_demo.py cleanup",
    }


def status(
    state: DemoState | None = None,
    *,
    clients: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    active_state = state or _load_state(required=False)
    if active_state is None:
        return {"status": "not-deployed", "region": REGION, "runtime_name": RUNTIME_NAME}
    validate_state(active_state)
    try:
        resolved_clients = clients or _aws_clients(region=active_state.region)
        caller_account = resolved_clients["sts"].get_caller_identity().get("Account")
        if caller_account != active_state.account_id:
            raise StateValidationError("AWS caller does not match the state boundary.")
        try:
            response = resolved_clients["control"].get_agent_runtime(
                agentRuntimeId=active_state.runtime_id
            )
        except ClientError as error:
            if _is_not_found(error):
                remote_status = "not-found"
            else:
                raise DemoOperationError("status", _failure_type(error)) from None
        else:
            tags = (
                resolved_clients["control"]
                .list_tags_for_resource(resourceArn=active_state.runtime_arn)
                .get("tags", {})
            )
            if not isinstance(tags, dict) or not _purpose_tags_match(tags, active_state):
                raise StateValidationError("Remote Runtime tags do not match the state boundary.")
            provider_status = response.get("status")
            allowed_statuses = {
                "CREATING",
                "READY",
                "UPDATING",
                "DELETING",
                "CREATE_FAILED",
                "UPDATE_FAILED",
            }
            remote_status = provider_status if provider_status in allowed_statuses else "unknown"
    except (DemoOperationError, StateValidationError):
        raise
    except Exception as error:  # noqa: BLE001 - public provider boundary
        raise DemoOperationError("status", _failure_type(error)) from None
    return {
        "status": remote_status,
        "region": REGION,
        "runtime_name": RUNTIME_NAME,
        "expires_at_utc": active_state.expires_at_utc,
        "tags": _build_tags(active_state.expires_at_utc),
    }


def run_demo(
    *,
    state: DemoState | None = None,
    uv_executable: str | None = None,
    clients: Mapping[str, Any] | None = None,
    session: boto3.Session | None = None,
) -> dict[str, object]:
    active_state = state or new_state()
    archive = build_package(uv_executable=uv_executable)
    deployed_state = deploy(archive, active_state, clients=clients)
    return invoke(deployed_state, session=session, cleanup_clients=clients)


def run_all(**kwargs: Any) -> dict[str, object]:
    return run_demo(**kwargs)


def _emit(payload: Mapping[str, object]) -> None:
    print(json.dumps(dict(payload), ensure_ascii=False, indent=2))


def _safe_cli_failure(stage: str, error: BaseException) -> dict[str, object]:
    if isinstance(error, DemoOperationError):
        failure_stage = error.stage
        failure_type = error.failure_type
        cleanup_summary = error.cleanup_summary
    else:
        failure_stage = _safe_stage(stage)
        failure_type = _failure_type(error)
        cleanup_summary = _sanitize_cleanup_summary(None)
    return {
        "status": "failed",
        "failure_stage": failure_stage,
        "failure_type": failure_type,
        "cleanup_summary": cleanup_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy and exercise the ephemeral synthetic AgentCore remote MCP demo"
    )
    parser.add_argument(
        "command",
        choices=("plan", "package", "deploy", "invoke", "status", "cleanup", "run"),
        nargs="?",
        default="plan",
    )
    parser.add_argument(
        "--uv-executable",
        help="Explicit uv executable; otherwise uv is resolved from PATH.",
    )
    args = parser.parse_args(argv)
    command = args.command
    try:
        if command == "plan":
            _emit(plan())
            return 0
        if command == "package":
            archive = build_package(uv_executable=args.uv_executable)
            _emit({"status": "packaged", "size_bytes": archive.stat().st_size})
            return 0

        active_state = (
            new_state()
            if command in {"deploy", "run"}
            else _load_state(required=command not in {"status", "cleanup"})
        )
        _emit(plan(active_state if isinstance(active_state, DemoState) else None))

        if command == "deploy":
            archive = build_package(uv_executable=args.uv_executable)
            deployed = deploy(archive, active_state)
            _emit(
                {
                    "status": "deployed",
                    "region": REGION,
                    "runtime_name": RUNTIME_NAME,
                    "expires_at_utc": deployed.expires_at_utc,
                    "tags": _build_tags(deployed.expires_at_utc),
                }
            )
            return 0
        if command == "invoke":
            if not isinstance(active_state, DemoState):
                raise StateValidationError("No AgentCore remote MCP demo state exists.")
            _emit(invoke(active_state))
            return 0
        if command == "status":
            _emit(status(active_state))
            return 0
        if command == "cleanup":
            if not isinstance(active_state, DemoState):
                _emit(_sanitize_cleanup_summary({"status": "not-needed"}))
                return 0
            summary = cleanup(active_state)
            _emit(summary)
            return 0 if summary["status"] in {"passed", "not-needed"} else 1
        if command == "run":
            archive = build_package(uv_executable=args.uv_executable)
            deployed = deploy(archive, active_state)
            _emit(invoke(deployed))
            return 0
        raise AssertionError("Unsupported command")
    except Exception as error:  # noqa: BLE001 - cleanup/report boundary
        _emit(_safe_cli_failure(command, error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
