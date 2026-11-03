"""Phase A of a batch (Т-§2.4): the events of one learner in `seq` order through the handlers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from quack.events.log import StoredEvent
from quack.graph.projection.mutations import Mutation
from quack.graph.projection.view import BatchSlice, Need


@dataclass
class PhaseAResult:
    mutations: list[Mutation] = field(default_factory=list)


def batch_need(events: Sequence[StoredEvent]) -> Need:
    """Union of `needs(event)` of the batch: the slice is read with one query (Т-§2.4)."""
    raise NotImplementedError


def apply_events(events: Sequence[StoredEvent], batch: BatchSlice) -> PhaseAResult:
    """Each event sees the slice plus the changes of the earlier events of the batch."""
    raise NotImplementedError
