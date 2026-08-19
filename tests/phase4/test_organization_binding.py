import pytest

from phase4.execution.models import ExecutionRequest


def test_execution_request_requires_organization_id():
    with pytest.raises(TypeError):
        ExecutionRequest.create(
            request_id="r1",
            agent_identity="agent",
            action="a",
            resource="r",
            context_packet_id="c",
        )


def test_execution_request_rejects_blank_organization_id():
    with pytest.raises(ValueError):
        ExecutionRequest.create(
            request_id="r1",
            agent_identity="agent",
            action="a",
            resource="r",
            context_packet_id="c",
            organization_id=" ",
        )
