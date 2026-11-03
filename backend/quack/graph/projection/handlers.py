"""Handlers of phase A, `rules@3` (ТЗ Ф4 WP3.2; Т-§2.4, Т-§2.5).

One handler per row of the S5 table (`quack.graph.projector_rows.ROWS`): `needs(event)` — the
slice it reads; `handle(event, view)` — pure, no I/O and no current time, returns the changes.
Ids of new nodes are UUIDv5 of `(learner_id, seq, n)` (`quack.graph.ids.deterministic_id`).
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Callable
from dataclasses import dataclass

from quack.events.event_types import (
    DomainCreated,
    EdgeAdded,
    EdgeRemoved,
    EmbeddingReady,
    HubCreated,
    HubDeadlineSet,
    HubTopicsChanged,
    SkillCreated,
    TopicCreated,
    TopicHidden,
    TopicProposed,
    TopicRenamed,
)
from quack.events.log import StoredEvent
from quack.events.registry import SPECS, EventPayload, payload_model
from quack.graph.ids import deterministic_id
from quack.graph.projection.mutations import DeleteRel, MergeNode, MergeRel, Mutation, SetProps
from quack.graph.projection.types import Props
from quack.graph.projection.view import NOTHING, Need, SliceView

type Needs = Callable[[StoredEvent], Need]
type Handle = Callable[[StoredEvent, SliceView], list[Mutation]]


@dataclass(frozen=True)
class Handler:
    needs: Needs
    handle: Handle


def handler_for(event: StoredEvent) -> Handler | None:
    """The handler of the event type.

    `None` — a catalog type marked «без обработчика»: the graph does not change, the watermark
    moves (Т-§2.4). An unknown type or a newer schema version than the code knows raises
    `UnknownEventTypeError`: the learner's stream stops (Т-§2.4, T-P6).
    """
    payload_model(event.type, event.schema_version)
    if not SPECS[(event.type, event.schema_version)].projector:
        return None
    return HANDLERS[event.type]


def _payload[P: EventPayload](event: StoredEvent, model: type[P]) -> P:
    return model.model_validate(event.payload)


def _nodes(*refs: tuple[str, str]) -> Need:
    return Need(nodes=frozenset(refs))


# --- structure (Т-§4) -------------------------------------------------------------------------
# Domain and Hub statuses: «active» — the catalog has no event that changes them (D-A-129).


def _domain_created(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§4.8: the hub «весь домен» is created with the domain; its composition is not stored
    (the hub covers every topic of the domain). Origin «learner», control type «no_goal»
    (D-A-129)."""
    p = _payload(event, DomainCreated)
    learner, domain = str(event.learner_id), str(p.domain_id)
    hub = deterministic_id(event.learner_id, event.seq, 0)
    return [
        MergeNode("Learner", learner, {"learnerId": learner}),
        MergeNode("Domain", domain, {"learnerId": learner, "name": p.name, "status": "active"}),
        MergeRel("Learner", learner, "OWNS", "Domain", domain, {}),
        MergeNode(
            "Hub",
            hub,
            {
                "learnerId": learner,
                "domainId": domain,
                "name": p.name,
                "kind": "domain_all",
                "origin": "learner",
                "controlType": "no_goal",
                "deadlineAtMs": 0,
                "status": "active",
            },
        ),
        MergeRel("Domain", domain, "HAS_HUB", "Hub", hub, {}),
    ]


def _topic_new_needs(event: StoredEvent) -> Need:
    p = _payload(event, TopicCreated if event.type == "topic.created" else TopicProposed)
    return _nodes(("Domain", str(p.domain_id)), ("Topic", str(p.topic_id)))


def _topic_new(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """`topic.proposed` / `topic.created` (Т-§4.3, Т-§4.7). A proposed topic that is created
    later keeps what it had (`knownClaimedAtMs`); only name, origin and status change."""
    p = _payload(event, TopicCreated if event.type == "topic.created" else TopicProposed)
    domain, topic = str(p.domain_id), str(p.topic_id)
    if view.node("Domain", domain) is None:
        return []
    status = "active" if event.type == "topic.created" else "proposed"
    props: Props = {"name": p.name, "origin": p.origin, "status": status}
    live = view.resolve("Topic", topic)
    if live is not None:
        return [SetProps("Topic", live, props)]
    learner = str(event.learner_id)
    base: Props = {"learnerId": learner, "domainId": domain, "knownClaimedAtMs": 0}
    return [
        MergeNode("Topic", topic, base | props),
        MergeRel("Domain", domain, "HAS_TOPIC", "Topic", topic, {}),
    ]


def _topic_set(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """`topic.renamed` — the name; `topic.hidden` — status `hidden` (Т-§4.11)."""
    props: Props
    if event.type == "topic.renamed":
        renamed = _payload(event, TopicRenamed)
        topic = str(renamed.topic_id)
        props = {"name": renamed.name}
    else:
        topic = str(_payload(event, TopicHidden).topic_id)
        props = {"status": "hidden"}
    live = view.resolve("Topic", topic)
    return [] if live is None else [SetProps("Topic", live, props)]


def _topic_ref(event: StoredEvent) -> Need:
    return _nodes(("Topic", str(event.payload["topic_id"])))


def _skill_created(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§4.1, Т-§4.4: the skill and `COVERS` from its home topic. The state of the skill
    (`Т-§3.4.4`) is written by its fold in phase B."""
    p = _payload(event, SkillCreated)
    topic = view.resolve("Topic", str(p.topic_id))
    if topic is None:
        return []
    learner, skill = str(event.learner_id), str(p.skill_id)
    return [
        MergeNode(
            "Skill",
            skill,
            {
                "learnerId": learner,
                "domainId": str(p.domain_id),
                "name": p.name,
                "summary": p.summary,
                "status": p.status,
                "origin": p.origin,
            },
        ),
        MergeRel("Topic", topic, "COVERS", "Skill", skill, {}),
    ]


_EDGE_TYPES = {"requires": "REQUIRES", "same_idea": "SAME_IDEA"}


def _edge_needs(event: StoredEvent) -> Need:
    return _nodes(("Skill", str(event.payload["from_id"])), ("Skill", str(event.payload["to_id"])))


def _edge(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """`REQUIRES {origin, confidence}` or `SAME_IDEA {confidence}` between skills (Т-§4.6). On
    removal the evidence derived over the relation becomes `superseded` — with the derived
    evidence of WP4.6."""
    p = _payload(event, EdgeAdded if event.type == "edge.added" else EdgeRemoved)
    a, b = view.resolve("Skill", str(p.from_id)), view.resolve("Skill", str(p.to_id))
    if a is None or b is None or a == b:
        return []
    rel_type = _EDGE_TYPES[p.kind]
    if not isinstance(p, EdgeAdded):
        return [DeleteRel("Skill", a, rel_type, "Skill", b)]
    props: Props = {"confidence": p.confidence}
    if p.kind == "requires":
        props["origin"] = p.origin
    return [MergeRel("Skill", a, rel_type, "Skill", b, props)]


def _hub_created(event: StoredEvent, view: SliceView) -> list[Mutation]:
    p = _payload(event, HubCreated)
    domain, hub = str(p.domain_id), str(p.hub_id)
    if view.node("Domain", domain) is None:
        return []
    return [
        MergeNode(
            "Hub",
            hub,
            {
                "learnerId": str(event.learner_id),
                "domainId": domain,
                "name": p.name,
                "kind": p.kind,
                "origin": p.origin,
                "controlType": p.control_type,
                "deadlineAtMs": 0,
                "status": "active",
            },
        ),
        MergeRel("Domain", domain, "HAS_HUB", "Hub", hub, {}),
    ]


def _hub_deadline_set(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """A removed deadline is 0, «не было» (`Т-§3.4.4`, law 8)."""
    p = _payload(event, HubDeadlineSet)
    hub = view.resolve("Hub", str(p.hub_id))
    deadline = p.deadline_at_ms if p.deadline_at_ms is not None else 0
    return [] if hub is None else [SetProps("Hub", hub, {"deadlineAtMs": deadline})]


def _hub_topics_needs(event: StoredEvent) -> Need:
    p = _payload(event, HubTopicsChanged)
    return Need(
        nodes=frozenset(("Topic", str(t.topic_id)) for t in p.topics),
        neighbourhoods=frozenset({("Hub", str(p.hub_id))}),
    )


def _hub_topics_changed(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """The event gives the whole set of topics of the hub with their required levels (Т-§4.8,
    Т-§8.5); topics not in it leave the hub. The default levels by `controlType` — WP6.3."""
    p = _payload(event, HubTopicsChanged)
    hub = str(p.hub_id)
    if view.node("Hub", hub) is None:
        return []
    wanted: dict[str, list[int]] = {}
    for item in p.topics:
        topic = view.resolve("Topic", str(item.topic_id))
        if topic is not None:
            wanted[topic] = list(item.required_levels)
    changes: list[Mutation] = [
        DeleteRel("Hub", hub, "INCLUDES", "Topic", r.to_id)
        for r in view.out_rels("Hub", hub, "INCLUDES")
        if r.to_id not in wanted
    ]
    changes += [
        MergeRel("Hub", hub, "INCLUDES", "Topic", topic, {"requiredLevels": levels})
        for topic, levels in wanted.items()
    ]
    return changes


# --- vectors (Т-§1.7, Т-§2.4) ----------------------------------------------------------------

_VECTOR_LABELS = {
    "evidence": "Evidence",
    "misconception": "Misconception",
    "chunk": "Chunk",
    "skill": "Skill",
    "topic": "Topic",
}


def _embedding_needs(event: StoredEvent) -> Need:
    return _nodes((_VECTOR_LABELS[event.payload["node_kind"]], str(event.payload["node_id"])))


def _embedding_ready(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """The vector on the node through its aliases; no node — nothing changes (Т-§2.4, T-P5).
    `vector` — base64 of float32 little-endian (ТЗ Ф4 WP20.2; byte order D-A-129)."""
    p = _payload(event, EmbeddingReady)
    label = _VECTOR_LABELS[p.node_kind]
    node = view.resolve(label, str(p.node_id))
    if node is None:
        return []
    raw = base64.b64decode(p.vector)
    vector = list(struct.unpack(f"<{len(raw) // 4}f", raw))
    return [SetProps(label, node, {"embedding": vector})]


# Event type -> handler; exactly the types of `ROWS` (T-P4).
HANDLERS: dict[str, Handler] = {
    "domain.created": Handler(lambda _: NOTHING, _domain_created),
    "topic.proposed": Handler(_topic_new_needs, _topic_new),
    "topic.created": Handler(_topic_new_needs, _topic_new),
    "topic.renamed": Handler(_topic_ref, _topic_set),
    "topic.hidden": Handler(_topic_ref, _topic_set),
    "skill.created": Handler(_topic_ref, _skill_created),
    "edge.added": Handler(_edge_needs, _edge),
    "edge.removed": Handler(_edge_needs, _edge),
    "hub.created": Handler(lambda e: _nodes(("Domain", str(e.payload["domain_id"]))), _hub_created),
    "hub.deadline_set": Handler(
        lambda e: _nodes(("Hub", str(e.payload["hub_id"]))), _hub_deadline_set
    ),
    "hub.topics_changed": Handler(_hub_topics_needs, _hub_topics_changed),
    "embedding.ready": Handler(_embedding_needs, _embedding_ready),
}
