"""Contract tests for AI-2 Context Packet Engine."""
import pytest

from phase4.context_packet import (
    ContextError,
    ContextItem,
    ContextLimitError,
    ContextPacket,
    ContextPacketEngine,
    ContextRequest,
    ContextSourceError,
)


def item(source, key, value, relevance=1.0, sensitivity="normal"):
    return ContextItem(
        source=source,
        key=key,
        value=value,
        relevance=relevance,
        provenance=f"source:{source}",
        sensitivity=sensitivity,
    )


class TestContextModels:
    def test_item_rejects_invalid_relevance(self):
        with pytest.raises(ValueError):
            item("a", "k", "v", relevance=1.1)

    def test_item_is_immutable(self):
        value = item("a", "k", {"x": 1})
        with pytest.raises((AttributeError, TypeError)):
            value.key = "changed"

    def test_request_requires_purpose(self):
        with pytest.raises(ValueError):
            ContextRequest(agent_identity="agent-1", purpose="")

    def test_packet_identity_is_deterministic(self):
        values = (item("a", "one", 1), item("b", "two", 2, relevance=0.5))
        a = ContextPacket.derive_id("agent", "test", values)
        b = ContextPacket.derive_id("agent", "test", values)
        assert a == b


class TestContextAssembly:
    def test_deterministic_ordering(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="verify")
        packet = engine.build(
            request,
            [item("z", "z", 1, 0.2), item("a", "a", 2, 0.9), item("b", "b", 3, 0.9)],
        )
        assert [x.key for x in packet.items] == ["a", "b", "z"]

    def test_requested_keys_filter(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="run", requested_keys=("keep",))
        packet = engine.build(request, [item("s", "keep", 1), item("s", "drop", 2)])
        assert [x.key for x in packet.items] == ["keep"]

    def test_sensitivity_filter_is_explicit(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="run", allowed_sensitivity=("public",))
        packet = engine.build(request, [item("s", "public", 1, sensitivity="public"), item("s", "secret", 2, sensitivity="sensitive")])
        assert [x.key for x in packet.items] == ["public"]

    def test_item_limit_truncates_without_failure(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="run", max_items=1)
        packet = engine.build(request, [item("s", "a", 1), item("s", "b", 2)])
        assert len(packet.items) == 1
        assert packet.truncated is True

    def test_byte_limit_truncates_without_failure(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="run", max_bytes=100)
        packet = engine.build(request, [item("s", "large", "x" * 1000)])
        assert packet.items == ()
        assert packet.truncated is True

    def test_invalid_item_type_fails_closed(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="run")
        with pytest.raises(ContextSourceError):
            engine.build(request, ["not-a-context-item"])

    def test_packet_contains_no_authority_decision(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="execute")
        packet = engine.build(request, [item("registry", "capability", "execute")])
        assert not hasattr(packet, "authorized")
        assert not hasattr(packet, "decision")

    def test_audit_trail_records_build(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="audit")
        packet = engine.build(request, [item("s", "k", "v")], actor="test")
        trail = engine.audit_trail(packet.packet_id)
        assert len(trail) == 1
        assert trail[0]["operation"] == "build"
        assert trail[0]["actor"] == "test"

    def test_same_input_has_same_packet_identity_despite_order(self):
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="same")
        a = engine.build(request, [item("b", "b", 2), item("a", "a", 1)])
        b = engine.build(request, [item("a", "a", 1), item("b", "b", 2)])
        assert a.packet_id == b.packet_id

    def test_context_is_not_authority(self):
        """AI-2 must not turn a declared capability into permission."""
        engine = ContextPacketEngine()
        request = ContextRequest(agent_identity="agent", purpose="execute")
        packet = engine.build(request, [item("agent-registry", "declared_capability", "execute")])
        assert packet.items[0].value == "execute"
        assert "authorized" not in packet.canonical()
