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
from datetime import datetime
from uuid import UUID

from quack.events.event_types import (
    ChunkIndexed,
    DigestWritten,
    DomainCreated,
    EdgeAdded,
    EdgeRemoved,
    EmbeddingReady,
    HubCreated,
    HubDeadlineSet,
    HubTopicsChanged,
    KnownClaimed,
    MaterialParsed,
    MaterialUploaded,
    MisconceptionDescribed,
    PreferenceSet,
    SessionEnded,
    SkillCreated,
    SkillSplit,
    TaskCreated,
    TaskKeyDisputed,
    TaskMarkupDisputed,
    TaskVerified,
    TopicCreated,
    TopicHidden,
    TopicProposed,
    TopicRenamed,
    TopicSplit,
)
from quack.events.log import StoredEvent
from quack.events.records import TaskMarkupRecord, TestedLevelRecord
from quack.events.registry import SPECS, EventPayload, payload_model
from quack.events.values import NewSkill
from quack.graph.ids import deterministic_id
from quack.graph.projection.mutations import (
    DeleteNode,
    DeleteRel,
    MergeNode,
    MergeRel,
    Mutation,
    SetProps,
)
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


def _ref(label: str, field: str) -> Needs:
    """`needs` of a handler that reads one node named by a payload field."""
    return lambda event: _nodes((label, str(event.payload[field])))


def _none(event: StoredEvent) -> Need:
    return NOTHING


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


# --- learner edits, profile, materials, digest, misconceptions --------------------------------


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _id(value: UUID | None) -> str:
    """An optional id as a property: no id is the explicit `''` (law 8, D-A-130)."""
    return "" if value is None else str(value)


def _profile_id(event: StoredEvent) -> str:
    """The only Profile of the learner (`Т-§3.4.3`, 1:1): UUIDv5 of the learner (D-A-130)."""
    return deterministic_id(event.learner_id, 0, "profile")


def _digest_id(event: StoredEvent, domain_id: str) -> str:
    """The latest digest of a domain (`Т-§3.4.3`, 1:1): UUIDv5 of the learner and domain."""
    return deterministic_id(event.learner_id, 0, f"digest:{domain_id}")


def _profile(event: StoredEvent, props: Props) -> list[Mutation]:
    learner, profile = str(event.learner_id), _profile_id(event)
    return [
        MergeNode("Learner", learner, {"learnerId": learner}),
        MergeNode("Profile", profile, {"learnerId": learner} | props),
        MergeRel("Learner", learner, "HAS_PROFILE", "Profile", profile, {}),
    ]


def _known_claimed(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§4.11: the learner says «знаю»; the state does not change (the check is a job)."""
    topic = view.resolve("Topic", str(_payload(event, KnownClaimed).topic_id))
    return (
        []
        if topic is None
        else [SetProps("Topic", topic, {"knownClaimedAtMs": _ms(event.occurred_at)})]
    )


def _camel(key: str) -> str:
    return "".join(part.capitalize() for part in key.split("_"))


def _preference_set(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§9.5: `pref*` — key `language` is `prefLanguage` (WP5.3)."""
    p = _payload(event, PreferenceSet)
    return _profile(event, {f"pref{_camel(p.key)}": p.value})


def _material_uploaded(event: StoredEvent, view: SliceView) -> list[Mutation]:
    p = _payload(event, MaterialUploaded)
    return [
        MergeNode(
            "Material",
            str(p.material_id),
            {
                "learnerId": str(event.learner_id),
                "domainId": _id(event.domain_id),
                "mime": p.mime,
                "sessionId": _id(p.session_id),
                "pagesCount": 0,
            },
        ),
    ]


def _material_parsed(event: StoredEvent, view: SliceView) -> list[Mutation]:
    p = _payload(event, MaterialParsed)
    material = view.resolve("Material", str(p.material_id))
    return (
        [] if material is None else [SetProps("Material", material, {"pagesCount": p.pages_count})]
    )


def _chunk_needs(event: StoredEvent) -> Need:
    p = _payload(event, ChunkIndexed)
    skills = {("Skill", str(s)) for s in (*p.teaches, *p.uses)}
    return Need(nodes=frozenset({("Material", str(p.material_id)), *skills}))


def _chunk_indexed(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """`searchable` — has text (`Т-§3.4.6`); `learnerId`, `domainId` — filter of `chunk_emb`."""
    p = _payload(event, ChunkIndexed)
    material = view.resolve("Material", str(p.material_id))
    if material is None:
        return []
    chunk = str(p.chunk_id)
    changes: list[Mutation] = [
        MergeNode(
            "Chunk",
            chunk,
            {
                "learnerId": str(event.learner_id),
                "domainId": _id(event.domain_id),
                "page": p.page,
                "text": p.text,
                "notation": list(p.notation),
                "searchable": bool(p.text.strip()),
            },
        ),
        MergeRel("Material", material, "HAS_CHUNK", "Chunk", chunk, {}),
    ]
    for rel_type, skills in (("TEACHES", p.teaches), ("USES", p.uses)):
        for skill in skills:
            live = view.resolve("Skill", str(skill))
            if live is not None:
                changes.append(MergeRel("Chunk", chunk, rel_type, "Skill", live, {}))
    return changes


def _digest_written(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """`Т-§13.5`: the latest digest of the domain replaces the earlier one; the teacher manner
    is `Profile.learnedManner` (§6.2, WP5.3)."""
    p = _payload(event, DigestWritten)
    domain = str(p.domain_id)
    if view.node("Domain", domain) is None:
        return []
    digest = _digest_id(event, domain)
    props: Props = {"learnerId": str(event.learner_id), "domainId": domain, "text": p.text,
                    "asOfSeq": p.as_of_seq}  # fmt: skip
    return [
        MergeNode("Digest", digest, props),
        MergeRel("Domain", domain, "HAS_DIGEST", "Digest", digest, {}),
        *_profile(event, {"learnedManner": p.manner}),
    ]


def _misconception_described(event: StoredEvent, view: SliceView) -> list[Mutation]:
    p = _payload(event, MisconceptionDescribed)
    node = view.resolve("Misconception", str(p.misconception_id))
    props: Props = {"statement": p.statement, "triggers": list(p.triggers)}
    return [] if node is None else [SetProps("Misconception", node, props)]


def _session_ended_needs(event: StoredEvent) -> Need:
    if event.domain_id is None:
        return NOTHING
    return Need(domain_labels=frozenset({(str(event.domain_id), "Misconception")}))


def _session_ended(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§9.1: the targeting of the session ends with it; a session has one domain (Т-§22.9)."""
    if event.domain_id is None:
        return []
    session = str(_payload(event, SessionEnded).session_id)
    return [
        SetProps("Misconception", m.id, {"targetedInSessionId": ""})
        for m in view.domain_nodes(str(event.domain_id), "Misconception")
        if m.props.get("targetedInSessionId") == session
    ]


# --- merges and splits (Т-§2.8) ---------------------------------------------------------------

_MERGED = {
    "skill.merged": "Skill",
    "topic.merged": "Topic",
    "misconception.merged": "Misconception",
}
# Relations of which the target keeps its own and the old ones are not moved, `(type, out)`: one
# home topic of a skill, one domain of a topic, one main skill of a misconception (`Т-§3.4.3`).
_OWN_RELS: dict[str, frozenset[tuple[str, bool]]] = {
    "Skill": frozenset({("COVERS", False)}),
    "Topic": frozenset({("HAS_TOPIC", False)}),
    "Misconception": frozenset({("ABOUT", True), ("CONFUSED_WITH", True)}),
}


def _merge_needs(event: StoredEvent) -> Need:
    label = _MERGED[event.type]
    ends = {(label, str(event.payload["from_id"])), (label, str(event.payload["into_id"]))}
    return Need(neighbourhoods=frozenset(ends))


def _merged(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Relations and evidence go to the target, the old node is deleted and its id becomes an
    `Alias` of the target; aliases of the old node move with its other relations (Т-§2.8). A
    relation the target already has, or one that would lead to the target itself, is dropped.
    The target's state is folded again in phase B."""
    label = _MERGED[event.type]
    old_ref, into_ref = str(event.payload["from_id"]), str(event.payload["into_id"])
    old, target = view.resolve(label, old_ref), view.resolve(label, into_ref)
    if old is None or target is None or old == target:
        return []
    own = _OWN_RELS[label]
    target_out = {(r.rel_type, r.to_label, r.to_id) for r in view.out_rels(label, into_ref)}
    target_in = {(r.rel_type, r.from_label, r.from_id) for r in view.in_rels(label, into_ref)}
    changes: list[Mutation] = []
    for r in view.out_rels(label, old_ref):
        if (r.rel_type, True) in own or (r.to_label, r.to_id) == (label, target):
            continue
        if (r.rel_type, r.to_label, r.to_id) not in target_out:
            changes.append(MergeRel(label, target, r.rel_type, r.to_label, r.to_id, r.props))
    for r in view.in_rels(label, old_ref):
        if (r.rel_type, False) in own or (r.from_label, r.from_id) == (label, target):
            continue
        if (r.rel_type, r.from_label, r.from_id) not in target_in:
            changes.append(MergeRel(r.from_label, r.from_id, r.rel_type, label, target, r.props))
    return [
        *changes,
        DeleteNode(label, old),
        MergeNode("Alias", old, {"learnerId": str(event.learner_id)}),
        MergeRel("Alias", old, "ALIAS_OF", label, target, {}),
    ]


def _topic_split_needs(event: StoredEvent) -> Need:
    p = _payload(event, TopicSplit)
    return Need(
        nodes=frozenset(("Topic", str(part.topic_id)) for part in p.into),
        neighbourhoods=frozenset(
            {("Topic", str(p.topic_id))}
            | {("Skill", str(skill)) for part in p.into for skill in part.skill_ids}
        ),
    )


def _topic_split(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Skills are distributed between the parts (Т-§2.8). A part with the old id keeps the
    topic and takes the part's name; a new part is a topic of the same domain with the origin
    and status of the split one. A split topic that is not a part is left without skills and
    hidden (D-A-131)."""
    p = _payload(event, TopicSplit)
    old = view.resolve("Topic", str(p.topic_id))
    old_props = view.node("Topic", str(p.topic_id))
    if old is None or old_props is None:
        return []
    domain = str(old_props["domainId"])
    changes: list[Mutation] = []
    parts: set[str] = set()
    for part in p.into:
        topic = view.resolve("Topic", str(part.topic_id))
        if topic is None:
            topic = str(part.topic_id)
            changes += [
                MergeNode(
                    "Topic",
                    topic,
                    {
                        "learnerId": str(event.learner_id),
                        "domainId": domain,
                        "name": part.name,
                        "origin": old_props["origin"],
                        "status": old_props["status"],
                        "knownClaimedAtMs": 0,
                    },
                ),
                MergeRel("Domain", domain, "HAS_TOPIC", "Topic", topic, {}),
            ]
        else:
            changes.append(SetProps("Topic", topic, {"name": part.name}))
        parts.add(topic)
        for skill_ref in part.skill_ids:
            skill = view.resolve("Skill", str(skill_ref))
            if skill is None:
                continue
            for r in view.in_rels("Skill", str(skill_ref), "COVERS"):
                if r.from_id != topic:
                    changes.append(DeleteRel("Topic", r.from_id, "COVERS", "Skill", skill))
            changes.append(MergeRel("Topic", topic, "COVERS", "Skill", skill, {}))
    if old not in parts:
        changes.append(SetProps("Topic", old, {"status": "hidden"}))
    return changes


def _skill_split_needs(event: StoredEvent) -> Need:
    p = _payload(event, SkillSplit)
    topics = {("Topic", str(part.topic_id)) for part in p.into}
    return Need(nodes=frozenset({("Skill", str(p.skill_id)), *topics}))


def _skill_split(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """New skills appear; the old evidence stays on the old skill and the dispatcher re-extracts
    its episodes (Т-§2.8). A part takes the domain, status and origin of the split skill; its
    summary is not known yet — `''` (D-A-131)."""
    p = _payload(event, SkillSplit)
    old = view.node("Skill", str(p.skill_id))
    if old is None:
        return []
    changes: list[Mutation] = []
    for part in p.into:
        topic = view.resolve("Topic", str(part.topic_id))
        if topic is None:
            continue
        skill = str(part.skill_id)
        changes += [
            MergeNode(
                "Skill",
                skill,
                {
                    "learnerId": str(event.learner_id),
                    "domainId": old["domainId"],
                    "name": part.name,
                    "summary": "",
                    "status": old["status"],
                    "origin": old["origin"],
                },
            ),
            MergeRel("Topic", topic, "COVERS", "Skill", skill, {}),
        ]
    return changes


# --- tasks (Т-§4.4, Т-§5.1, Т-§5.2, Т-§5.6) --------------------------------------------------

_CHECKS = {"task.verified": "checked", "task.key_disputed": "disputed",
           "task.markup_disputed": "disputed"}  # fmt: skip


def _norm(name: str) -> str:
    """Normalized name (Т-§4.4): case and runs of spaces do not count."""
    return " ".join(name.casefold().split())


# The part of a task without parts (D-B-121).
MAIN_PART = "main"


def _all_tests(markup: TaskMarkupRecord) -> list[tuple[str, TestedLevelRecord]]:
    """Pairs of the markup with their part: `main` and the parts by their own markup."""
    return [(MAIN_PART, t) for t in markup.tests] + [
        (part.part, t) for part in markup.parts or [] for t in part.tests or []
    ]


def _markup_need(markup: TaskMarkupRecord, domain: UUID | None) -> Need:
    tests = [t for _, t in _all_tests(markup)]
    nodes = {("Skill", str(t.skill_id)) for t in tests if t.skill_id is not None}
    nodes |= {("Misconception", str(o.misconception_id)) for o in markup.options or []
              if o.misconception_id is not None}  # fmt: skip
    labels: set[tuple[str, str]] = set()
    if domain is not None:
        nodes.add(("Domain", str(domain)))
        if any(t.new_skill is not None for t in tests):
            labels = {(str(domain), "Skill"), (str(domain), "Topic")}
    return Need(nodes=frozenset(nodes), domain_labels=frozenset(labels))


def _task_needs(event: StoredEvent) -> Need:
    if event.type == "task.created":
        p = _payload(event, TaskCreated)
        return _markup_need(p.markup, event.domain_id)
    check = _payload(event, _CHECK_MODELS[event.type])
    need = Need(neighbourhoods=frozenset({("Task", str(check.task_id))}))
    if check.corrected_markup is not None:
        need = need | _markup_need(check.corrected_markup, event.domain_id)
    return need


class _Markup:
    """Changes of one markup of a task: provisional skills and topics, `TESTS {level}`, options
    and traps. New ids — UUIDv5 of `(learner_id, seq, key)` with a key per new node."""

    def __init__(self, event: StoredEvent, view: SliceView, task: str, domain: str) -> None:
        self.event, self.view, self.task, self.domain = event, view, task, domain
        self.learner = str(event.learner_id)
        self.changes: list[Mutation] = []
        self._skills: dict[str, str] | None = None
        self._topics: dict[str, str] = {}

    def _new_id(self, key: str) -> str:
        return deterministic_id(self.event.learner_id, self.event.seq, key)

    def _skill_for(self, description: NewSkill) -> str | None:
        """One provisional skill per normalized name in the domain; a hint without a topic of
        that name makes a temporary topic (Т-§4.4)."""
        if self.event.domain_id is None:
            return None
        if self._skills is None:
            self._skills = {_norm(str(n.props["name"])): n.id
                            for n in self.view.domain_nodes(self.domain, "Skill")}  # fmt: skip
            self._topics = {_norm(str(n.props["name"])): n.id
                            for n in self.view.domain_nodes(self.domain, "Topic")}  # fmt: skip
        key = _norm(description.name)
        if key in self._skills:
            return self._skills[key]
        topic_key = _norm(description.topic_hint)
        topic = self._topics.get(topic_key)
        if topic is None:
            topic = self._new_id(f"topic:{topic_key}")
            self.changes += [
                MergeNode(
                    "Topic",
                    topic,
                    {
                        "learnerId": self.learner,
                        "domainId": self.domain,
                        "name": description.topic_hint.strip(),
                        "origin": "session",
                        "status": "proposed",
                        "knownClaimedAtMs": 0,
                    },
                ),
                MergeRel("Domain", self.domain, "HAS_TOPIC", "Topic", topic, {}),
            ]
            self._topics[topic_key] = topic
        skill = self._new_id(f"skill:{key}")
        self.changes += [
            MergeNode(
                "Skill",
                skill,
                {
                    "learnerId": self.learner,
                    "domainId": self.domain,
                    "name": description.name.strip(),
                    "summary": "",
                    "status": "provisional",
                    "origin": "session",
                },
            ),
            MergeRel("Topic", topic, "COVERS", "Skill", skill, {}),
        ]
        self._skills[key] = skill
        return skill

    def apply(self, markup: TaskMarkupRecord, *, replace: bool) -> list[Mutation]:
        pairs: list[tuple[str, int, str]] = []
        for part, t in _all_tests(markup):
            if t.skill_id is not None:
                skill = self.view.resolve("Skill", str(t.skill_id))
            elif t.new_skill is not None:
                skill = self._skill_for(t.new_skill)
            else:
                skill = None
            if skill is not None and (skill, t.level, part) not in pairs:
                pairs.append((skill, t.level, part))
        if replace:
            for r in self.view.out_rels("Task", self.task, "TESTS"):
                level, part = r.props["level"], r.props["part"]
                if (r.to_id, level, part) not in pairs:
                    key: Props = {"level": level, "part": part}
                    self.changes.append(
                        DeleteRel("Task", self.task, "TESTS", "Skill", r.to_id, key)
                    )
            options = self.view.out_rels("Task", self.task, "HAS_OPTION")
            self.changes += [DeleteNode("Option", r.to_id) for r in options]
        self.changes += [
            MergeRel("Task", self.task, "TESTS", "Skill", skill, {"level": level, "part": part})
            for skill, level, part in pairs
        ]
        self._options(markup, pairs[0][0] if pairs else None)
        return self.changes

    def _options(self, markup: TaskMarkupRecord, first_skill: str | None) -> None:
        """Options of a choice answer and their traps (Т-§5.2). A trap on a hypothesis is a
        misconception with status `unknown` about the first tested skill (WP3.2, D-A-132)."""
        traps = {o.option_id: o for o in markup.options or []}
        for option in markup.answer.options or []:
            trap = traps.get(option.option_id)
            node = self._new_id(f"option:{option.option_id}")
            self.changes += [
                MergeNode(
                    "Option",
                    node,
                    {
                        "learnerId": self.learner,
                        "label": option.option_id,
                        "isCorrect": option.correct,
                        "neighborIdea": trap.neighbor_idea if trap is not None else False,
                    },
                ),
                MergeRel("Task", self.task, "HAS_OPTION", "Option", node, {}),
            ]
            if trap is None:
                continue
            if trap.misconception_id is not None:
                misconception = self.view.resolve("Misconception", str(trap.misconception_id))
                if misconception is not None:
                    self.changes.append(
                        MergeRel("Option", node, "TRAPS", "Misconception", misconception, {})
                    )
            elif trap.hypothesis is not None and first_skill is not None:
                misconception = self._new_id(f"misconception:{option.option_id}")
                self.changes += [
                    MergeNode(
                        "Misconception",
                        misconception,
                        {
                            "learnerId": self.learner,
                            "domainId": self.domain,
                            "statement": trap.hypothesis,
                            "status": "unknown",
                            "triggers": [],
                            "targetedInSessionId": "",
                            "searchable": bool(trap.hypothesis.strip()),
                        },
                    ),
                    MergeRel("Misconception", misconception, "ABOUT", "Skill", first_skill, {}),
                    MergeRel("Option", node, "TRAPS", "Misconception", misconception, {}),
                ]


def _task_created(event: StoredEvent, view: SliceView) -> list[Mutation]:
    p = _payload(event, TaskCreated)
    task, domain = str(p.task_id), _id(event.domain_id)
    head: list[Mutation] = [
        MergeNode(
            "Task",
            task,
            {
                "learnerId": str(event.learner_id),
                "domainId": domain,
                "familyId": str(p.family_id),
                "source": p.source,
                "verification": p.verification,
                "methodNamed": p.markup.method_named,
            },
        ),
    ]
    return head + _Markup(event, view, task, domain).apply(p.markup, replace=False)


def _task_checked(event: StoredEvent, view: SliceView) -> list[Mutation]:
    """Т-§5.6: the result of the check of a task; a corrected markup replaces the old one.
    Lowering the verdicts of a disputed task to class model — with the evidence (D-A-132)."""
    p = _payload(event, _CHECK_MODELS[event.type])
    task = str(p.task_id)
    props = view.node("Task", task)
    if props is None:
        return []
    changes: list[Mutation] = [SetProps("Task", task, {"verification": _CHECKS[event.type]})]
    if p.corrected_markup is not None:
        markup = p.corrected_markup
        changes.append(SetProps("Task", task, {"methodNamed": markup.method_named}))
        changes += _Markup(event, view, task, str(props["domainId"])).apply(markup, replace=True)
    return changes


_CHECK_MODELS = {"task.verified": TaskVerified, "task.key_disputed": TaskKeyDisputed,
                 "task.markup_disputed": TaskMarkupDisputed}  # fmt: skip


# Event type -> handler; exactly the types of `ROWS` (T-P4).
HANDLERS: dict[str, Handler] = {
    "domain.created": Handler(_none, _domain_created),
    "topic.proposed": Handler(_topic_new_needs, _topic_new),
    "topic.created": Handler(_topic_new_needs, _topic_new),
    "topic.renamed": Handler(_ref("Topic", "topic_id"), _topic_set),
    "topic.hidden": Handler(_ref("Topic", "topic_id"), _topic_set),
    "skill.created": Handler(_ref("Topic", "topic_id"), _skill_created),
    "edge.added": Handler(_edge_needs, _edge),
    "edge.removed": Handler(_edge_needs, _edge),
    "hub.created": Handler(_ref("Domain", "domain_id"), _hub_created),
    "hub.deadline_set": Handler(_ref("Hub", "hub_id"), _hub_deadline_set),
    "hub.topics_changed": Handler(_hub_topics_needs, _hub_topics_changed),
    "embedding.ready": Handler(_embedding_needs, _embedding_ready),
    "known.claimed": Handler(_ref("Topic", "topic_id"), _known_claimed),
    "preference.set": Handler(lambda e: _nodes(("Profile", _profile_id(e))), _preference_set),
    "material.uploaded": Handler(_none, _material_uploaded),
    "material.parsed": Handler(_ref("Material", "material_id"), _material_parsed),
    "chunk.indexed": Handler(_chunk_needs, _chunk_indexed),
    "digest.written": Handler(_ref("Domain", "domain_id"), _digest_written),
    "misconception.described": Handler(
        _ref("Misconception", "misconception_id"), _misconception_described
    ),
    "session.ended": Handler(_session_ended_needs, _session_ended),
    "skill.merged": Handler(_merge_needs, _merged),
    "topic.merged": Handler(_merge_needs, _merged),
    "misconception.merged": Handler(_merge_needs, _merged),
    "topic.split": Handler(_topic_split_needs, _topic_split),
    "skill.split": Handler(_skill_split_needs, _skill_split),
    "task.created": Handler(_task_needs, _task_created),
    "task.verified": Handler(_task_needs, _task_checked),
    "task.key_disputed": Handler(_task_needs, _task_checked),
    "task.markup_disputed": Handler(_task_needs, _task_checked),
}
