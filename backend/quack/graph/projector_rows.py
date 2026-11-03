"""Rows of the projector handlers of `rules@3` (ТЗ Ф4 WP3.2, seam S5; G1: the table).

A row per event type the projector handles (§6.3 column «Проектор»): who writes it, the payload
fields the handler reads, the graph changes and the source. The handlers are WP3.2 (G2):
`handle(event, view) -> mutations` with `needs(event)` (`Т-§2.5`). The `reads` paths are a
contract with the writers of the events: a test checks every path exists in the payload model,
so a field the projector reads cannot be renamed or dropped silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type Stream = Literal["A", "B", "C"]


@dataclass(frozen=True)
class ProjectorRow:
    """`reads` — dotted paths into the payload (through nested models and list items)."""

    event_type: str
    writers: tuple[Stream, ...]
    reads: tuple[str, ...]
    changes: str
    source: str


ROWS: tuple[ProjectorRow, ...] = ()
ROW_BY_TYPE: dict[str, ProjectorRow] = {row.event_type: row for row in ROWS}
