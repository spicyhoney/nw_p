from __future__ import annotations

import pytest

from scripts import agentcore_runtime_poc as poc


def test_execution_policy_limits_bedrock_to_selected_model() -> None:
    policy = poc._build_execution_policy("123456789012")
    model_statement = next(
        statement for statement in policy["Statement"] if statement["Sid"] == "NovaLiteInvocation"
    )

    assert model_statement["Resource"] == (
        "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0"
    )
    assert "iam:*" not in model_statement["Action"]


def test_trust_policy_restricts_source_account_and_region() -> None:
    policy = poc._build_trust_policy("123456789012")
    statement = policy["Statement"][0]

    assert statement["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert statement["Condition"]["StringEquals"] == {"aws:SourceAccount": "123456789012"}
    assert statement["Condition"]["ArnLike"] == {
        "aws:SourceArn": "arn:aws:bedrock-agentcore:us-west-2:123456789012:*"
    }


def test_validate_invoke_result_accepts_expected_redacted_trace() -> None:
    trace = [{"name": name} for name in sorted(poc.EXPECTED_TOOL_NAMES)]
    result = {
        "status": "passed",
        "tool_use_trace": trace,
        "observed_request_intervals_seconds": [1.1, 1.25, 1.4],
        "execution_environment": "Amazon Bedrock AgentCore Runtime",
    }

    assert poc._validate_invoke_result(result) is result


@pytest.mark.parametrize(
    "result",
    (
        {"status": "failed"},
        {
            "status": "passed",
            "tool_use_trace": [{"name": "search_services"}],
            "observed_request_intervals_seconds": [1.1],
            "execution_environment": "Amazon Bedrock AgentCore Runtime",
        },
        {
            "status": "passed",
            "tool_use_trace": [{"name": name} for name in sorted(poc.EXPECTED_TOOL_NAMES)],
            "observed_request_intervals_seconds": [1.09],
            "execution_environment": "Amazon Bedrock AgentCore Runtime",
        },
    ),
)
def test_validate_invoke_result_rejects_incomplete_or_unpaced_results(result) -> None:
    with pytest.raises(RuntimeError):
        poc._validate_invoke_result(result)
