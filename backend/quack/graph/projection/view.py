"""Slice of a batch and the read-only view a handler gets (Т-§2.4, Т-§2.5).

Every handler declares `needs(event)`. The slice of the whole batch is read with one query
before phase A; then each event sees what was read plus the changes of the earlier events of
the batch. A handler that reads outside its own `needs(event)` is a program error
(`OutsideSliceError`, T-P3), even if the node is in the slice for another event.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from quack.events.log import StoredEvent
from quack.graph.projection.mutations import (
    DeleteNode,
    DeleteRel,
    MergeNode,
    MergeRel,
    Mutation,
    SetProps,
)
from quack.graph.projection.types import (
    NodeRecord,
    NodeRef,
    Props,
    RelKey,
    RelRecord,
    SubGraph,
    rel_key,
)


@dataclass(frozen=True)
class Need:
    """What one handler reads.

    `nodes` — the nodes themselves (through their aliases, Т-§2.8); `neighbourhoods` — the nodes,
    every relationship of theirs and the nodes at the other end; `domain_labels` — every node
    of a label in a domain, `(domain_id, label)` (e.g. skills by normalized name, Т-§4.4);
    `events` — events of the learner by `seq` (folds and handlers read events «через
    представление», WP3.2); `event_refs` — `(seq, payload field, label)`: the node named by a
    field of that event, with its neighbourhood (the task of an answer for its verdict).
    """

    nodes: frozenset[NodeRef] = frozenset()
    neighbourhoods: frozenset[NodeRef] = frozenset()
    domain_labels: frozenset[tuple[str, str]] = frozenset()
    events: frozenset[int] = frozenset()
    event_refs: frozenset[tuple[int, str, str]] = frozenset()

    def __or__(self, other: Need) -> Need:
        return Need(
            nodes=self.nodes | other.nodes,
            neighbourhoods=self.neighbourhoods | other.neighbourhoods,
            domain_labels=self.domain_labels | other.domain_labels,
            events=self.events | other.events,
            event_refs=self.event_refs | other.event_refs,
        )


NOTHING = Need()


class OutsideSliceError(Exception):
    """A handler read what its `needs(event)` does not declare (Т-§2.4: a program error)."""


class SliceView(Protocol):
    """Read-only view of one handler, limited to its `needs(event)`."""

    def node(self, label: str, node_id: str) -> Props | None:
        """Props of a live node, `None` if there is none (after alias resolution)."""
        ...

    def resolve(self, label: str, node_id: str) -> str | None:
        """Live id of the node through `Alias` (Т-§2.8); `None` — no node and no alias."""
        ...

    def out_rels(
        self, label: str, node_id: str, rel_type: str | None = None
    ) -> list[RelRecord]: ...

    def in_rels(self, label: str, node_id: str, rel_type: str | None = None) -> list[RelRecord]: ...

    def domain_nodes(self, domain_id: str, label: str) -> list[NodeRecord]: ...

    def event(self, seq: int) -> StoredEvent | None:
        """An event of the learner by `seq`; `None` — no such event (deleted, Т-§2.9)."""
        ...


class BatchSlice:
    """The slice of one learner's batch: the store read plus the changes of the batch.

    Applying is strict: `SetProps` on a missing node and `MergeRel` with a missing end are
    handler errors (a handler resolves its references first and applies nothing if they are
    gone, Т-§2.4).
    """

    def __init__(
        self, learner_id: str, loaded: SubGraph, events: Sequence[StoredEvent] = ()
    ) -> None:
        self.learner_id = learner_id
        self._events: dict[int, StoredEvent] = {e.seq: e for e in events}
        self._nodes: dict[NodeRef, Props] = {(n.label, n.id): dict(n.props) for n in loaded.nodes}
        self._rels: dict[RelKey, RelRecord] = {r.key: _copy(r) for r in loaded.rels}

    def view(self, need: Need) -> SliceView:
        """The view of one handler: reads outside `need` raise `OutsideSliceError`."""
        return _View(self, need)

    def add_event(self, event: StoredEvent) -> None:
        """An event of the batch, so the later events of the batch can read it."""
        raise NotImplementedError

    def apply(self, mutations: Sequence[Mutation]) -> None:
        """Apply the changes of one event, so later events of the batch see them."""
        for m in mutations:
            match m:
                case MergeNode(label, node_id, props):
                    self._nodes[(label, node_id)] = {
                        **self._nodes.get((label, node_id), {}),
                        **props,
                    }
                case SetProps(label, node_id, props):
                    if (label, node_id) not in self._nodes:
                        raise ValueError(f"SetProps on a missing node {label} {node_id}")
                    self._nodes[(label, node_id)].update(props)
                case MergeRel(from_label, from_id, rel_type, to_label, to_id, props):
                    for end in ((from_label, from_id), (to_label, to_id)):
                        if end not in self._nodes:
                            raise ValueError(f"MergeRel {rel_type} with a missing end {end}")
                    key = rel_key(from_label, from_id, rel_type, to_label, to_id, props)
                    old = self._rels.get(key)
                    merged = {**(old.props if old else {}), **props}
                    self._rels[key] = RelRecord(
                        from_label, from_id, rel_type, to_label, to_id, merged
                    )
                case DeleteRel(from_label, from_id, rel_type, to_label, to_id, key_props):
                    key = rel_key(from_label, from_id, rel_type, to_label, to_id, key_props)
                    self._rels.pop(key, None)
                case DeleteNode(label, node_id):
                    self._nodes.pop((label, node_id), None)
                    for key, r in list(self._rels.items()):
                        if (label, node_id) in ((r.from_label, r.from_id), (r.to_label, r.to_id)):
                            del self._rels[key]

    def snapshot(self) -> SubGraph:
        """Every node and relationship of the slice now (for tests and rebuild)."""
        return SubGraph(
            nodes=[NodeRecord(label, i, dict(p)) for (label, i), p in sorted(self._nodes.items())],
            rels=[_copy(r) for _, r in sorted(self._rels.items(), key=lambda item: str(item[0]))],
        )

    # --- reads without the guard (the view checks the need first) ---

    def _resolve(self, label: str, node_id: str) -> str | None:
        seen: set[str] = set()
        while (label, node_id) not in self._nodes:
            if node_id in seen or ("Alias", node_id) not in self._nodes:
                return None
            seen.add(node_id)
            targets = [
                r.to_id
                for r in self._rels.values()
                if (r.from_label, r.from_id, r.rel_type) == ("Alias", node_id, "ALIAS_OF")
            ]
            if len(targets) != 1:
                return None
            node_id = targets[0]
        return node_id

    def _rels_of(self, label: str, node_id: str, *, out: bool) -> list[RelRecord]:
        return [
            _copy(r)
            for _, r in sorted(self._rels.items(), key=lambda item: str(item[0]))
            if ((r.from_label, r.from_id) if out else (r.to_label, r.to_id)) == (label, node_id)
        ]

    def _neighbours(self, label: str, node_id: str) -> set[NodeRef]:
        return {(r.to_label, r.to_id) for r in self._rels_of(label, node_id, out=True)} | {
            (r.from_label, r.from_id) for r in self._rels_of(label, node_id, out=False)
        }


def _copy(r: RelRecord) -> RelRecord:
    return RelRecord(r.from_label, r.from_id, r.rel_type, r.to_label, r.to_id, dict(r.props))


class _View:
    def __init__(self, batch: BatchSlice, need: Need) -> None:
        self._batch = batch
        self._need = need

    def _check_node(self, label: str, node_id: str) -> None:
        ref = (label, node_id)
        if ref in self._need.nodes or ref in self._need.neighbourhoods:
            return
        for near_label, near_id in self._need.neighbourhoods:
            live = self._batch._resolve(near_label, near_id)
            if live is not None and ref in self._batch._neighbours(near_label, live):
                return
        raise OutsideSliceError(f"{label} {node_id} is not in needs()")

    def node(self, label: str, node_id: str) -> Props | None:
        self._check_node(label, node_id)
        live = self._batch._resolve(label, node_id)
        return None if live is None else dict(self._batch._nodes[(label, live)])

    def resolve(self, label: str, node_id: str) -> str | None:
        self._check_node(label, node_id)
        return self._batch._resolve(label, node_id)

    def _rels(
        self, label: str, node_id: str, rel_type: str | None, *, out: bool
    ) -> list[RelRecord]:
        if (label, node_id) not in self._need.neighbourhoods:
            raise OutsideSliceError(f"relationships of {label} {node_id} are not in needs()")
        live = self._batch._resolve(label, node_id)
        if live is None:
            return []
        rels = self._batch._rels_of(label, live, out=out)
        return [r for r in rels if rel_type is None or r.rel_type == rel_type]

    def out_rels(self, label: str, node_id: str, rel_type: str | None = None) -> list[RelRecord]:
        return self._rels(label, node_id, rel_type, out=True)

    def in_rels(self, label: str, node_id: str, rel_type: str | None = None) -> list[RelRecord]:
        return self._rels(label, node_id, rel_type, out=False)

    def event(self, seq: int) -> StoredEvent | None:
        raise NotImplementedError

    def domain_nodes(self, domain_id: str, label: str) -> list[NodeRecord]:
        if (domain_id, label) not in self._need.domain_labels:
            raise OutsideSliceError(f"{label} nodes of domain {domain_id} are not in needs()")
        return [
            NodeRecord(node_label, node_id, dict(props))
            for (node_label, node_id), props in sorted(self._batch._nodes.items())
            if node_label == label and props.get("domainId") == domain_id
        ]
