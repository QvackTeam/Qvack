"""Handlers of phase A, `rules@3` (ТЗ Ф4 WP3.2; Т-§2.4, Т-§2.5).

One handler per row of the S5 table (`quack.graph.projector_rows.ROWS`): `needs(event)` — the
slice it reads; `handle(event, view)` — pure, no I/O and no current time, returns the changes.
Ids of new nodes are UUIDv5 of `(learner_id, seq, n)` (`quack.graph.ids.deterministic_id`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from quack.events.log import StoredEvent
from quack.graph.projection.mutations import Mutation
from quack.graph.projection.view import Need, SliceView

type Needs = Callable[[StoredEvent], Need]
type Handle = Callable[[StoredEvent, SliceView], list[Mutation]]


@dataclass(frozen=True)
class Handler:
    needs: Needs
    handle: Handle


# Event type -> handler; exactly the types of `ROWS` (T-P4).
HANDLERS: dict[str, Handler] = {}


def handler_for(event: StoredEvent) -> Handler | None:
    """The handler of the event type.

    `None` — a catalog type marked «без обработчика»: the graph does not change, the watermark
    moves (Т-§2.4). An unknown type or a newer schema version than the code knows raises
    `UnknownEventTypeError`: the learner's stream stops (Т-§2.4, T-P6).
    """
    raise NotImplementedError
