"""Conversation of the teacher context — slot 5 (Т-§10.3; ТЗ Ф4 WP14.3).

Built by code from the events of the session only: past sessions never come in raw (П-2.1).
The last turns go in full — learner actions, the teacher text, elements, answers and verdicts,
canvas lines with their numbers (Т-§15.6), "unclear" flags. Past
`conversation_verbatim_max_turns` the oldest `conversation_collapse_turns` turns fold at once
into episode lines (`collapsed_turn_count` of Phase 3 WP13): the start of the visible part
changes once per batch, so the prefix cache of Meta holds (Т-§10.1). Episode lines are written
by code from events and markup, never by a model (law 10). English (Т-§22.2). D-B-158.

A turn is a `turn.committed` with the events before it since the previous turn and the events
of its own append (`causation_seq` = its `action_seq`, WP2.2). Events after the last turn are
the learner's current action: they go last.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from quack.config import Settings
from quack.events.log import StoredEvent
from quack.llm.labels import LabelKind, LabelMap

_INTENT_BUTTONS = {"learn": "Learn", "practice": "Practice", "review": "Review"}

_OUTCOME_WORDS = {
    "correct": "right",
    "incorrect": "wrong",
    "partial": "partly right",
    "unclear": "unclear",
}

_CLOSED_WORDS = {"solved": "solved", "skipped": "skipped", "solution_shown": "solution shown"}

_EXPOSURE_WORDS = {
    "explained": "explained",
    "example": "worked example",
    "method_named": "method named",
    "solution_shown": "solution shown",
}


@dataclass
class Turn:
    """One turn of the session: its events in order and its number from the session start."""

    number: int
    events: list[StoredEvent] = field(default_factory=list)


@dataclass(frozen=True)
class SessionTurns:
    turns: list[Turn]
    current: list[StoredEvent]


def split_turns(events: Sequence[StoredEvent]) -> SessionTurns:
    """The turns of the session and the events of the current action (after the last turn)."""
    raise NotImplementedError


class _Lines:
    """Canvas lines numbered in the order of the session (Т-§15.6); the numbers stay put."""

    def __init__(self) -> None:
        self._numbers: dict[tuple[UUID, str], int] = {}

    def number(self, canvas_id: UUID, line_id: str) -> int:
        return self._numbers.setdefault((canvas_id, line_id), len(self._numbers) + 1)


def _ref(labels: LabelMap, kind: LabelKind, object_id: UUID | None, fallback: str) -> str:
    raise NotImplementedError


def _task(labels: LabelMap, task_id: UUID) -> str:
    raise NotImplementedError


def _answer_seqs(turn_events: Sequence[StoredEvent]) -> dict[int, UUID]:
    raise NotImplementedError


def _verbatim(
    event: StoredEvent, labels: LabelMap, lines: _Lines, answers: dict[int, UUID]
) -> list[str]:
    raise NotImplementedError


def _episode_line(turn: Turn, labels: LabelMap, answers: dict[int, UUID]) -> str:
    """One line of a folded turn: what the teacher did and what happened with the tasks."""
    raise NotImplementedError


def render_conversation(events: Sequence[StoredEvent], labels: LabelMap, settings: Settings) -> str:
    """Slot 5: episode lines of the folded turns, the later turns in full, the current action
    last."""
    raise NotImplementedError
