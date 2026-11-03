"""ТЗ Ф4 WP3.2 (§8.4): handlers of phase A, `rules@3` — the slice, the table, aliases.

T-P3 `test_handler_outside_slice_is_bug`, T-P4 `test_handler_table` (by groups of the S5 table),
T-P5 `test_alias_and_empty_apply`; the unknown type of T-P6 at the handler level (the stopped
stream and `ops resume` — with the batch loop, WP3.3).
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

import quack.events.event_types  # noqa: F401  (registers the catalog before SPECS is read)
from quack.events.log import StoredEvent
from quack.events.registry import SPECS, UnknownEventTypeError
from quack.graph.ids import deterministic_id
from quack.graph.projection.handlers import HANDLERS, handler_for
from quack.graph.projection.phase_a import apply_events
from quack.graph.projection.types import NodeRecord, Props, RelKey, RelRecord, SubGraph
from quack.graph.projection.view import BatchSlice, Need, OutsideSliceError
from quack.graph.projector_rows import ROWS

LEARNER = UUID(int=0xA0)
L = str(LEARNER)
DOMAIN = str(UUID(int=0xD0))
TOPIC = str(UUID(int=0x71))
TOPIC_B = str(UUID(int=0x72))
SKILL = str(UUID(int=0x51))
SKILL_B = str(UUID(int=0x52))
SKILL_OLD = str(UUID(int=0x59))
HUB = str(UUID(int=0xB0))
AT = datetime(2026, 11, 3, tzinfo=UTC)


def _event(seq: int, event_type: str, payload: dict[str, Any], **envelope: Any) -> StoredEvent:
    return StoredEvent(
        learner_id=LEARNER,
        seq=seq,
        id=seq,
        type=event_type,
        schema_version=envelope.pop("schema_version", 1),
        actor="test",
        domain_id=envelope.pop("domain_id", None),
        session_id=envelope.pop("session_id", None),
        causation_seq=None,
        correlation_id=None,
        idempotency_key=f"key:{seq}",
        payload_hash="hash",
        occurred_at=AT,
        payload=payload,
        source_refs=[],
    )


def _node(label: str, node_id: str, **props: Any) -> NodeRecord:
    return NodeRecord(label, node_id, {"learnerId": L, **props})


def _rel(a: tuple[str, str], rel_type: str, b: tuple[str, str], **props: Any) -> RelRecord:
    return RelRecord(a[0], a[1], rel_type, b[0], b[1], dict(props))


def _graph(batch: BatchSlice) -> tuple[dict[tuple[str, str], Props], dict[RelKey, Props]]:
    shot = batch.snapshot()
    return {(n.label, n.id): n.props for n in shot.nodes}, {r.key: r.props for r in shot.rels}


def _run(
    events: Sequence[StoredEvent], nodes: Sequence[NodeRecord] = (), rels: Sequence[RelRecord] = ()
) -> tuple[dict[tuple[str, str], Props], dict[RelKey, Props]]:
    batch = BatchSlice(L, SubGraph(nodes=list(nodes), rels=list(rels)))
    apply_events(events, batch)
    return _graph(batch)


_DOMAIN = _node("Domain", DOMAIN, name="Algebra", status="active")
_TOPIC = _node("Topic", TOPIC, domainId=DOMAIN, name="Fractions", origin="session",
               status="active", knownClaimedAtMs=0)  # fmt: skip
_TOPIC_B = _node("Topic", TOPIC_B, domainId=DOMAIN, name="Ratios", origin="session",
                 status="active", knownClaimedAtMs=0)  # fmt: skip
_SKILL = _node("Skill", SKILL, domainId=DOMAIN, name="add fractions", summary="s",
               status="active", origin="session")  # fmt: skip
_SKILL_B = _node("Skill", SKILL_B, domainId=DOMAIN, name="common denominator", summary="s",
                 status="active", origin="session")  # fmt: skip
_HUB = _node("Hub", HUB, domainId=DOMAIN, name="Exam", kind="request", origin="learner",
             controlType="tasks", deadlineAtMs=0, status="active")  # fmt: skip
_ALIAS = NodeRecord("Alias", SKILL_OLD, {"learnerId": L})
_ALIAS_OF = _rel(("Alias", SKILL_OLD), "ALIAS_OF", ("Skill", SKILL))


# --- the table and the catalog (T-P4, T-P6) -------------------------------------------------


def test_every_projector_row_has_a_handler() -> None:
    """S5: one handler per row; the catalog types «без обработчика» have none (Т-§2.4)."""
    assert set(HANDLERS) == {row.event_type for row in ROWS}
    assert len(SPECS) > len(ROWS)
    for (event_type, version), spec in SPECS.items():
        handler = handler_for(_event(1, event_type, {}, schema_version=version))
        assert (handler is not None) == spec.projector, event_type


def test_unknown_type_or_newer_schema_is_an_error() -> None:
    """T-P6 at the handler level: an error, never a skip (Т-§2.4)."""
    with pytest.raises(UnknownEventTypeError):
        handler_for(_event(1, "comet.sighted", {}))
    with pytest.raises(UnknownEventTypeError):
        handler_for(_event(1, "topic.renamed", {}, schema_version=2))


# --- the slice (T-P3) -----------------------------------------------------------------------


def test_handler_outside_slice_is_bug() -> None:
    batch = BatchSlice(L, SubGraph(nodes=[_SKILL, _SKILL_B, _TOPIC], rels=[]))
    view = batch.view(Need(nodes=frozenset({("Skill", SKILL)})))
    assert view.node("Skill", SKILL) == _SKILL.props
    with pytest.raises(OutsideSliceError):
        view.node("Skill", SKILL_B)
    with pytest.raises(OutsideSliceError):
        view.out_rels("Skill", SKILL)  # only the node is declared, not its relationships
    with pytest.raises(OutsideSliceError):
        view.domain_nodes(DOMAIN, "Topic")
    near = batch.view(Need(neighbourhoods=frozenset({("Topic", TOPIC)})))
    assert near.out_rels("Topic", TOPIC) == []
    assert batch.view(Need(domain_labels=frozenset({(DOMAIN, "Skill")}))).domain_nodes(
        DOMAIN, "Skill"
    ) == sorted([_SKILL, _SKILL_B], key=lambda n: n.id)


def test_needs_of_a_batch_join() -> None:
    a = Need(nodes=frozenset({("Skill", SKILL)}))
    b = Need(
        neighbourhoods=frozenset({("Topic", TOPIC)}), domain_labels=frozenset({(DOMAIN, "Skill")})
    )
    assert a | b == Need(
        nodes=a.nodes, neighbourhoods=b.neighbourhoods, domain_labels=b.domain_labels
    )


# --- structure (T-P4) -----------------------------------------------------------------------


def test_domain_created_makes_the_domain_and_its_whole_domain_hub() -> None:
    """Т-§4.8: the hub «весь домен» is created with the domain; its composition is not stored."""
    nodes, rels = _run([_event(1, "domain.created", {"domain_id": DOMAIN, "name": "Algebra"})])
    hub = deterministic_id(LEARNER, 1, 0)
    assert nodes[("Domain", DOMAIN)] == _DOMAIN.props
    assert nodes[("Hub", hub)] == {
        "learnerId": L, "domainId": DOMAIN, "name": "Algebra", "kind": "domain_all",
        "origin": "learner", "controlType": "no_goal", "deadlineAtMs": 0, "status": "active",
    }  # fmt: skip
    assert ("Learner", L, "OWNS", "Domain", DOMAIN) in rels
    assert ("Domain", DOMAIN, "HAS_HUB", "Hub", hub) in rels
    assert not any(key[2] == "INCLUDES" for key in rels)


@pytest.mark.parametrize(("event_type", "status"), [("topic.created", "active"),
                                                    ("topic.proposed", "proposed")])  # fmt: skip
def test_topic_created_or_proposed(event_type: str, status: str) -> None:
    payload = {"topic_id": TOPIC, "domain_id": DOMAIN, "name": "Fractions", "origin": "session"}
    nodes, rels = _run([_event(2, event_type, payload)], [_DOMAIN])
    assert nodes[("Topic", TOPIC)] == _TOPIC.props | {"status": status}
    assert rels[("Domain", DOMAIN, "HAS_TOPIC", "Topic", TOPIC)] == {}


def test_topic_renamed_and_hidden() -> None:
    nodes, _ = _run(
        [
            _event(3, "topic.renamed", {"topic_id": TOPIC, "name": "Fraction sums"}),
            _event(4, "topic.hidden", {"topic_id": TOPIC}),
        ],
        [_DOMAIN, _TOPIC],
    )
    assert nodes[("Topic", TOPIC)] == _TOPIC.props | {"name": "Fraction sums", "status": "hidden"}


def test_skill_created_is_covered_by_its_home_topic() -> None:
    payload = {"skill_id": SKILL, "topic_id": TOPIC, "domain_id": DOMAIN, "name": "add fractions",
               "summary": "s", "status": "active", "origin": "session"}  # fmt: skip
    nodes, rels = _run([_event(5, "skill.created", payload)], [_DOMAIN, _TOPIC])
    assert nodes[("Skill", SKILL)] == _SKILL.props
    assert rels[("Topic", TOPIC, "COVERS", "Skill", SKILL)] == {}


def test_edges_added_and_removed() -> None:
    requires = {"kind": "requires", "from_id": SKILL, "to_id": SKILL_B}
    _, rels = _run(
        [
            _event(6, "edge.added", requires | {"origin": "model", "confidence": 0.7}),
            _event(
                7,
                "edge.added",
                {
                    "kind": "same_idea",
                    "from_id": SKILL,
                    "to_id": SKILL_B,
                    "origin": "model",
                    "confidence": 0.8,
                },
            ),
        ],
        [_SKILL, _SKILL_B],
    )
    assert rels[("Skill", SKILL, "REQUIRES", "Skill", SKILL_B)] == {
        "origin": "model",
        "confidence": 0.7,
    }
    assert rels[("Skill", SKILL, "SAME_IDEA", "Skill", SKILL_B)] == {"confidence": 0.8}
    _, rels = _run(
        [_event(8, "edge.removed", requires)],
        [_SKILL, _SKILL_B],
        [_rel(("Skill", SKILL), "REQUIRES", ("Skill", SKILL_B), origin="model", confidence=0.7)],
    )
    assert ("Skill", SKILL, "REQUIRES", "Skill", SKILL_B) not in rels


def test_hub_created_deadline_and_topics() -> None:
    created = {"hub_id": HUB, "domain_id": DOMAIN, "name": "Exam", "kind": "request",
               "origin": "learner", "control_type": "tasks"}  # fmt: skip
    nodes, rels = _run(
        [
            _event(9, "hub.created", created),
            _event(
                10,
                "hub.deadline_set",
                {"hub_id": HUB, "deadline_at_ms": 1_800_000_000_000, "source": "learner"},
            ),
            _event(
                11,
                "hub.topics_changed",
                {
                    "hub_id": HUB,
                    "topics": [
                        {"topic_id": TOPIC, "required_levels": [3, 4]},
                        {"topic_id": TOPIC_B, "required_levels": [2]},
                    ],
                },
            ),
            _event(
                12,
                "hub.topics_changed",
                {
                    "hub_id": HUB,
                    "topics": [
                        {"topic_id": TOPIC, "required_levels": [3]},
                    ],
                },
            ),
        ],
        [_DOMAIN, _TOPIC, _TOPIC_B],
    )
    assert nodes[("Hub", HUB)] == _HUB.props | {"deadlineAtMs": 1_800_000_000_000}
    assert ("Domain", DOMAIN, "HAS_HUB", "Hub", HUB) in rels
    assert rels[("Hub", HUB, "INCLUDES", "Topic", TOPIC)] == {"requiredLevels": [3]}
    assert ("Hub", HUB, "INCLUDES", "Topic", TOPIC_B) not in rels  # the event gives the set
    nodes, _ = _run(
        [
            _event(
                13, "hub.deadline_set", {"hub_id": HUB, "deadline_at_ms": None, "source": "learner"}
            )
        ],
        [_DOMAIN, _HUB],
    )
    assert nodes[("Hub", HUB)]["deadlineAtMs"] == 0  # law 8: removed deadline — 0 «не было»


# --- aliases and the empty application (T-P5) -----------------------------------------------


def _vector(values: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()


def test_alias_and_empty_apply() -> None:
    """`embedding.ready` for a merged skill lands on the target; for a missing one nothing
    changes (Т-§2.4: the event is applied as empty, the watermark still moves)."""
    ready = {"node_kind": "skill", "model": "m", "dim": 2, "vector": _vector([0.5, -1.0])}
    nodes, _ = _run(
        [_event(14, "embedding.ready", ready | {"node_id": SKILL_OLD})],
        [_SKILL, _ALIAS],
        [_ALIAS_OF],
    )
    assert nodes[("Skill", SKILL)]["embedding"] == [0.5, -1.0]
    assert ("Skill", SKILL_OLD) not in nodes
    before = _run([], [_SKILL], [])
    after = _run([_event(15, "embedding.ready", ready | {"node_id": SKILL_B})], [_SKILL], [])
    assert after == before
