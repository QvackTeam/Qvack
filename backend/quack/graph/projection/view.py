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

from quack.graph.projection.mutations import Mutation
from quack.graph.projection.types import NodeRecord, NodeRef, Props, RelRecord, SubGraph


@dataclass(frozen=True)
class Need:
    """What one handler reads.

    `nodes` — the nodes themselves (through their aliases, Т-§2.8); `neighbourhoods` — the nodes,
    every relationship of theirs and the nodes at the other end; `domain_labels` — every node
    of a label in a domain, `(domain_id, label)` (e.g. skills by normalized name, Т-§4.4).
    """

    nodes: frozenset[NodeRef] = frozenset()
    neighbourhoods: frozenset[NodeRef] = frozenset()
    domain_labels: frozenset[tuple[str, str]] = frozenset()

    def __or__(self, other: Need) -> Need:
        raise NotImplementedError


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


class BatchSlice:
    """The slice of one learner's batch: the store read plus the changes of the batch."""

    def __init__(self, learner_id: str, loaded: SubGraph) -> None:
        raise NotImplementedError

    def view(self, need: Need) -> SliceView:
        """The view of one handler: reads outside `need` raise `OutsideSliceError`."""
        raise NotImplementedError

    def apply(self, mutations: Sequence[Mutation]) -> None:
        """Apply the changes of one event, so later events of the batch see them."""
        raise NotImplementedError

    def snapshot(self) -> SubGraph:
        """Every node and relationship of the slice now (for tests and rebuild)."""
        raise NotImplementedError
