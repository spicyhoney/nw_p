from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "us-west-2"
MODEL_ID = "amazon.nova-lite-v1:0"
RUNTIME_NAME = "nw_p_runtime_poc"
ROLE_NAME = "AmazonBedrockAgentCoreRuntime-nwpoc"
ROLE_POLICY_NAME = "BedrockAgentCoreRuntimeNwPocPolicy"
OBJECT_KEY = f"{RUNTIME_NAME}/deployment.zip"
LOG_GROUP_PREFIX = "/aws/bedrock-agentcore/runtimes/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "var" / "agentcore-poc"
STATE_PATH = BUILD_ROOT / "state.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "agentcore_runtime_poc.json"
REQUIREMENTS_PATH = PROJECT_ROOT / "deploy" / "agentcore_runtime_requirements.txt"
ENTRYPOINT_PATH = PROJECT_ROOT / "agentcore_runtime_entrypoint.py"
UV_PATH = PROJECT_ROOT / ".venv" / "Scripts" / "uv.exe"
EXPECTED_TOOL_NAMES = {
    "search_services",
    "resolve_location",
    "get_consultation_form",
    "match_service_providers",
}
SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"aws_(?:access_key_id|secret_access_key|session_token)", re.IGNORECASE),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

LOGGER = logging.getLogger("agentcore_runtime_poc")


@dataclass
class PocState:
    account_id: str = ""
    bucket_name: str = ""
    role_arn: str = ""
    runtime_id: str = ""
    runtime_arn: str = ""
    workload_identity_name: str = ""
    runtime_session_id: str = ""
    created_bucket: bool = False
    created_role: bool = False
    created_runtime: bool = False
    log_group_name: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _tags() -> dict[str, str]:
    return {
        "Project": "nw_p",
        "Purpose": "agentcore-runtime-poc",
        "ManagedBy": "codex",
        "ExpiresAt": (datetime.now(UTC) + timedelta(hours=2)).isoformat(timespec="seconds"),
    }


def _save_state(state: PocState) -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def _load_state() -> PocState:
    if not STATE_PATH.exists():
        return PocState()
    return PocState(**json.loads(STATE_PATH.read_text(encoding="utf-8")))


def _aws_clients() -> dict[str, Any]:
    config = Config(connect_timeout=10, read_timeout=180, retries={"max_attempts": 1})
    session = boto3.Session(region_name=REGION)
    return {
        "sts": session.client("sts", config=config),
        "iam": session.client("iam", config=config),
        "s3": session.client("s3", config=config),
        "control": session.client("bedrock-agentcore-control", config=config),
        "runtime": session.client("bedrock-agentcore", config=config),
        "logs": session.client("logs", config=config),
    }


def _build_trust_policy(account_id: str) -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:*"
                    },
                },
            }
        ],
    }


def _build_execution_policy(account_id: str) -> dict[str, object]:
    log_group_arn = f"arn:aws:logs:{REGION}:{account_id}:log-group:{LOG_GROUP_PREFIX}*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "RuntimeLogGroupAccess",
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": log_group_arn,
            },
            {
                "Sid": "RuntimeLogGroupDiscovery",
                "Effect": "Allow",
                "Action": "logs:DescribeLogGroups",
                "Resource": f"arn:aws:logs:{REGION}:{account_id}:log-group:*",
            },
            {
                "Sid": "RuntimeLogWrite",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"{log_group_arn}:log-stream:*",
            },
            {
                "Sid": "RuntimeMetrics",
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "NovaLiteInvocation",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": f"arn:aws:bedrock:{REGION}::foundation-model/{MODEL_ID}",
            },
        ],
    }


def build_package() -> Path:
    if not UV_PATH.is_file():
        raise RuntimeError("uv is required in the isolated project virtual environment")
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    package_dir = BUILD_ROOT / "package"
    package_dir.mkdir(parents=True)

    subprocess.run(
        [
            str(UV_PATH),
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
    # uv generates host-specific console launchers; the Runtime executes our Python
    # entrypoint directly, so shipping Windows launchers would be both unused and noisy.
    shutil.rmtree(package_dir / "bin", ignore_errors=True)
    # Boto3 ships documentation-only sample credentials. They are not needed at runtime
    # and would make a deployment artifact secret scan ambiguous.
    shutil.rmtree(package_dir / "boto3" / "examples", ignore_errors=True)
    for example_file in (package_dir / "botocore" / "data").rglob("examples-1.json"):
        example_file.unlink()

    shutil.copy2(ENTRYPOINT_PATH, package_dir / ENTRYPOINT_PATH.name)
    shutil.copytree(
        PROJECT_ROOT / "src" / "home_repair_agent",
        package_dir / "home_repair_agent",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    scripts_dir = package_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(PROJECT_ROOT / "scripts" / "bedrock_mcp_e2e.py", scripts_dir)

    archive = BUILD_ROOT / "deployment.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in package_dir.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(package_dir).as_posix())
    if archive.stat().st_size > 250 * 1024 * 1024:
        raise RuntimeError("AgentCore deployment archive exceeds 250 MiB")
    return archive


def _ensure_role(clients: dict[str, Any], state: PocState) -> None:
    iam = clients["iam"]
    try:
        iam.get_role(RoleName=ROLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
    else:
        raise RuntimeError(
            f"Refusing to reuse existing IAM role {ROLE_NAME}; clean it up or choose a new POC name"
        )

    response = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(_build_trust_policy(state.account_id)),
        Description="Ephemeral execution role for the nw_p synthetic AgentCore Runtime POC",
        Tags=[{"Key": key, "Value": value} for key, value in _tags().items()],
    )
    state.role_arn = response["Role"]["Arn"]
    state.created_role = True
    _save_state(state)
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=ROLE_POLICY_NAME,
        PolicyDocument=json.dumps(_build_execution_policy(state.account_id)),
    )


def _ensure_bucket(clients: dict[str, Any], state: PocState) -> None:
    s3 = clients["s3"]
    state.bucket_name = f"bedrock-agentcore-nwpoc-{state.account_id}-{REGION}"
    try:
        s3.head_bucket(Bucket=state.bucket_name)
    except ClientError as error:
        code = str(error.response["Error"].get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
    else:
        raise RuntimeError(
            f"Refusing to reuse existing S3 bucket {state.bucket_name}; clean it up first"
        )

    s3.create_bucket(
        Bucket=state.bucket_name,
        CreateBucketConfiguration={"LocationConstraint": REGION},
    )
    state.created_bucket = True
    _save_state(state)
    s3.put_public_access_block(
        Bucket=state.bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
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
    )
    s3.put_bucket_tagging(
        Bucket=state.bucket_name,
        Tagging={"TagSet": [{"Key": key, "Value": value} for key, value in _tags().items()]},
    )


def _wait_for_runtime(control: Any, runtime_id: str, expected: str) -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            response = control.get_agent_runtime(agentRuntimeId=runtime_id)
        except ClientError as error:
            if expected == "DELETED" and error.response["Error"]["Code"] in {
                "ResourceNotFoundException",
                "ValidationException",
            }:
                return
            raise
        status = response["status"]
        if status == expected:
            return
        if status in {"CREATE_FAILED", "UPDATE_FAILED"}:
            raise RuntimeError(f"AgentCore Runtime entered {status}")
        time.sleep(5)
    raise TimeoutError(f"AgentCore Runtime did not reach {expected}")


def deploy(archive: Path, state: PocState) -> PocState:
    clients = _aws_clients()
    state.account_id = clients["sts"].get_caller_identity()["Account"]
    existing = [
        item
        for item in clients["control"].list_agent_runtimes()["agentRuntimes"]
        if item["agentRuntimeName"] == RUNTIME_NAME
    ]
    if existing:
        raise RuntimeError(f"Refusing to overwrite existing AgentCore Runtime {RUNTIME_NAME}")

    _ensure_role(clients, state)
    _ensure_bucket(clients, state)
    clients["s3"].upload_file(
        str(archive),
        state.bucket_name,
        OBJECT_KEY,
        ExtraArgs={
            "ServerSideEncryption": "AES256",
            "ExpectedBucketOwner": state.account_id,
        },
    )

    time.sleep(10)
    response = clients["control"].create_agent_runtime(
        agentRuntimeName=RUNTIME_NAME,
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {"s3": {"bucket": state.bucket_name, "prefix": OBJECT_KEY}},
                "runtime": "PYTHON_3_12",
                "entryPoint": [ENTRYPOINT_PATH.name],
            }
        },
        roleArn=state.role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
        lifecycleConfiguration={"idleRuntimeSessionTimeout": 60, "maxLifetime": 300},
        environmentVariables={
            "BEDROCK_REGION": REGION,
            "BEDROCK_MODEL_ID": MODEL_ID,
            "BEDROCK_MAX_TOKENS": "512",
            "BEDROCK_TIMEOUT_SECONDS": "60",
        },
        description="Ephemeral synthetic-only nw_p AgentCore Runtime POC",
        tags=_tags(),
        clientToken=f"nwpoc-{uuid.uuid4().hex}",
    )
    state.runtime_id = response["agentRuntimeId"]
    state.runtime_arn = response["agentRuntimeArn"]
    state.created_runtime = True
    identity_arn = response.get("workloadIdentityDetails", {}).get("workloadIdentityArn", "")
    state.workload_identity_name = identity_arn.rsplit("/", 1)[-1] if identity_arn else ""
    state.log_group_name = f"{LOG_GROUP_PREFIX}{state.runtime_id}-DEFAULT"
    _save_state(state)
    _wait_for_runtime(clients["control"], state.runtime_id, "READY")
    return state


def _validate_invoke_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict) or result.get("status") != "passed":
        raise RuntimeError("AgentCore synthetic invocation did not pass")
    trace = result.get("tool_use_trace")
    if not isinstance(trace, list):
        raise TypeError("AgentCore synthetic invocation returned no tool trace")
    names = {entry.get("name") for entry in trace if isinstance(entry, dict)}
    if names != EXPECTED_TOOL_NAMES:
        raise RuntimeError("AgentCore synthetic invocation returned an unexpected tool trace")
    intervals = result.get("observed_request_intervals_seconds")
    if not isinstance(intervals, list) or any(
        not isinstance(value, (int, float)) or value < 1.1 for value in intervals
    ):
        raise RuntimeError("AgentCore synthetic invocation violated the Bedrock request interval")
    if result.get("execution_environment") != "Amazon Bedrock AgentCore Runtime":
        raise RuntimeError("AgentCore synthetic invocation did not identify its runtime")
    return result


def invoke(state: PocState) -> dict[str, object]:
    runtime = _aws_clients()["runtime"]
    state.runtime_session_id = f"nwpoc-{uuid.uuid4().hex}"
    _save_state(state)
    response = runtime.invoke_agent_runtime(
        agentRuntimeArn=state.runtime_arn,
        runtimeSessionId=state.runtime_session_id,
        qualifier="DEFAULT",
        contentType="application/json",
        accept="application/json",
        payload=json.dumps({"scenario": "synthetic_repair_v1"}).encode("utf-8"),
    )
    body = response["response"].read()
    result = json.loads(body.decode("utf-8"))
    return _validate_invoke_result(result)


def inspect_logs(state: PocState) -> dict[str, object]:
    logs = _aws_clients()["logs"]
    deadline = time.monotonic() + 60
    messages: list[str] = []
    while time.monotonic() < deadline:
        try:
            response = logs.filter_log_events(
                logGroupName=state.log_group_name,
                startTime=int((time.time() - 900) * 1000),
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ResourceNotFoundException":
                time.sleep(3)
                continue
            raise
        messages = [event.get("message", "") for event in response.get("events", [])]
        if any("agentcore_poc_passed" in message for message in messages):
            break
        time.sleep(3)

    joined = "\n".join(messages)
    sensitive_matches = sum(bool(pattern.search(joined)) for pattern in SENSITIVE_PATTERNS)
    return {
        "log_group": state.log_group_name,
        "event_count": len(messages),
        "started_marker": "agentcore_poc_started" in joined,
        "passed_marker": "agentcore_poc_passed" in joined,
        "credential_or_private_key_patterns": sensitive_matches,
        "full_provider_payload_markers": sum(
            marker in joined for marker in ("toolConfig", "output.message", "inputText")
        ),
    }


def _delete_bucket(s3: Any, state: PocState) -> None:
    if not state.created_bucket or not state.bucket_name:
        return
    response = s3.list_objects_v2(Bucket=state.bucket_name)
    objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
    if objects:
        s3.delete_objects(Bucket=state.bucket_name, Delete={"Objects": objects, "Quiet": True})
    s3.delete_bucket(Bucket=state.bucket_name)


def cleanup(state: PocState) -> dict[str, object]:
    clients = _aws_clients()
    cleanup_errors: list[str] = []
    if state.runtime_session_id and state.runtime_arn:
        try:
            clients["runtime"].stop_runtime_session(
                agentRuntimeArn=state.runtime_arn,
                runtimeSessionId=state.runtime_session_id,
                qualifier="DEFAULT",
                clientToken=f"nwpoc-stop-{uuid.uuid4().hex}",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] not in {
                "ResourceNotFoundException",
                "ValidationException",
                "ConflictException",
            }:
                cleanup_errors.append("stop_runtime_session")

    if state.created_runtime and state.runtime_id:
        try:
            clients["control"].delete_agent_runtime(agentRuntimeId=state.runtime_id)
            _wait_for_runtime(clients["control"], state.runtime_id, "DELETED")
        except (ClientError, TimeoutError):
            cleanup_errors.append("delete_agent_runtime")

    if state.workload_identity_name:
        try:
            identities = clients["control"].list_workload_identities()["workloadIdentities"]
            if any(item["name"] == state.workload_identity_name for item in identities):
                clients["control"].delete_workload_identity(name=state.workload_identity_name)
        except ClientError:
            cleanup_errors.append("delete_workload_identity")

    if state.log_group_name:
        try:
            clients["logs"].delete_log_group(logGroupName=state.log_group_name)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                cleanup_errors.append("delete_log_group")

    try:
        _delete_bucket(clients["s3"], state)
    except ClientError:
        cleanup_errors.append("delete_s3_bucket")

    if state.created_role:
        try:
            clients["iam"].delete_role_policy(RoleName=ROLE_NAME, PolicyName=ROLE_POLICY_NAME)
            clients["iam"].delete_role(RoleName=ROLE_NAME)
        except ClientError:
            cleanup_errors.append("delete_iam_role")

    remaining_runtimes = [
        item
        for item in clients["control"].list_agent_runtimes()["agentRuntimes"]
        if item["agentRuntimeName"] == RUNTIME_NAME
    ]
    bucket_exists = False
    if state.bucket_name:
        try:
            clients["s3"].head_bucket(Bucket=state.bucket_name)
        except ClientError:
            bucket_exists = False
        else:
            bucket_exists = True
    role_exists = True
    try:
        clients["iam"].get_role(RoleName=ROLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] == "NoSuchEntity":
            role_exists = False
        else:
            cleanup_errors.append("verify_iam_role")

    evidence = {
        "cleanup_errors": cleanup_errors,
        "runtime_count_after_cleanup": len(remaining_runtimes),
        "s3_bucket_exists_after_cleanup": bucket_exists,
        "iam_role_exists_after_cleanup": role_exists,
        "cleanup_passed": not cleanup_errors
        and not remaining_runtimes
        and not bucket_exists
        and not role_exists,
    }
    if not evidence["cleanup_passed"]:
        raise RuntimeError(f"AgentCore POC cleanup failed: {evidence}")
    return evidence


def run_all() -> dict[str, object]:
    started_at = _now()
    state = PocState()
    invocation: dict[str, object] | None = None
    log_evidence: dict[str, object] | None = None
    cleanup_evidence: dict[str, object] | None = None
    failure: str | None = None
    try:
        archive = build_package()
        state = deploy(archive, state)
        invocation = invoke(state)
        log_evidence = inspect_logs(state)
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        persisted = _load_state()
        if persisted.account_id:
            state = persisted
        try:
            if state.account_id:
                cleanup_evidence = cleanup(state)
        finally:
            report = {
                "started_at_utc": started_at,
                "finished_at_utc": _now(),
                "region": REGION,
                "model_id": MODEL_ID,
                "runtime_name": RUNTIME_NAME,
                "runtime_id": state.runtime_id,
                "tags": _tags(),
                "invocation": invocation,
                "logs": log_evidence,
                "cleanup": cleanup_evidence,
                "failure_type": failure,
            }
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ephemeral nw_p AgentCore Runtime POC")
    parser.add_argument("command", choices=("package", "run", "cleanup"), default="run", nargs="?")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "package":
        archive = build_package()
        print(json.dumps({"status": "packaged", "size_bytes": archive.stat().st_size}))
    elif args.command == "cleanup":
        print(json.dumps(cleanup(_load_state()), indent=2))
    else:
        print(json.dumps(run_all(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
