"""The extractor by episodes, WP15 п.1–3 (ТЗ Ф4; Т-§7.5, Т-§7.6, Т-§4.5): the window, the
input of `extractor@3` and the call of the role. D-B-162.

- **Window** (п.1, Т-§7.5): the episode `[from_seq, to_seq]` plus `episode_context_turns` turns
  before it, for understanding only; only the episode is interpreted.
- **Input** (п.2, Т-§7.6): the events of the window as numbered text lines — learner and teacher
  replies, markup, verdicts, canvas lines, voice, "unclear"; candidate skills — the skills of
  the topics active in the session plus the nearest by the episode vector (with Modal down —
  only the session's), at most `candidate_skills_k`; known misconceptions of the candidates;
  the table of gap types (П-6.4). Everything with short labels.
- **Call** (п.3): `extractor@3` through the gateway, strict schema `ExtractorOutputV3`; an
  unknown label goes back to the model once (the gateway's repair path, Т-§4.5).

The check of the elements (п.4) and the write of `observation.extracted` with coverage (п.5)
stand on the seams of stream A.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from quack.agents.schemas import ExtractorOutputV3
from quack.config import Settings
from quack.events.event_types import (
    TurnCommitted,
)
from quack.events.log import StoredEvent
from quack.llm.gateway import LLMGateway
from quack.llm.labels import LabelMap

EXTRACTOR_ROLE = "extractor"
NONE_LINE = "(none)"

# П-6.4, in the words of the doctrine (`extractor@3`, «Caution in diagnosis» п.2).
GAP_TYPE_TABLE = (
    "no_idea — only naming the idea itself helps; their own prediction is empty or random.\n"
    "when_to_apply — solves the problem when the method is named, but not otherwise; a hint "
    "about the kind of technique helps.\n"
    "confusion — used a neighboring idea or picked an option built on a neighboring rule; it "
    "repeats on similar problems.\n"
    "execution — the method is right, the working has a mistake; showing the step helps.\n"
    "slip — a one-off; they did the same operation correctly before, or noticed it themselves "
    'after a short "check this".\n'
    "misconception — they are wrong confidently and on different problems, or picked an option "
    "built from this distortion.\n"
    "none — the outcome is correct."
)

_OUTCOME = {"correct": "correct", "incorrect": "incorrect", "partial": "partly correct"}


@dataclass(frozen=True)
class EpisodeWindow:
    """`before` — the context turns (record nothing from them); `episode` — the episode."""

    before: list[StoredEvent]
    episode: list[StoredEvent]


@dataclass(frozen=True)
class CandidateSkill:
    skill_id: UUID
    name: str


@dataclass(frozen=True)
class KnownMisconception:
    misconception_id: UUID
    skill_id: UUID
    statement: str


def extraction_window(
    session_events: Sequence[StoredEvent], from_seq: int, to_seq: int, settings: Settings
) -> EpisodeWindow:
    """The episode and the `episode_context_turns` turns before it (Т-§7.5). A turn ends with
    its `turn.committed`; the events of its own append (`causation_seq` = its `action_seq`,
    WP2.2) stay with it."""
    raise NotImplementedError


def candidate_skill_ids(
    session_skill_ids: Sequence[UUID], nearest_skill_ids: Sequence[UUID], settings: Settings
) -> list[UUID]:
    """Skills of the session topics first, then the nearest by vector; `candidate_skills_k`."""
    raise NotImplementedError


def _task(labels: LabelMap, task_id: UUID) -> str:
    raise NotImplementedError


def _turn_lines(seq: int, turn: TurnCommitted, labels: LabelMap) -> list[str]:
    raise NotImplementedError


def event_lines(event: StoredEvent, labels: LabelMap, answers: dict[int, UUID]) -> list[str]:
    """One event as numbered lines (`[seq] who: text`); events without text give none."""
    raise NotImplementedError


def render_events(events: Sequence[StoredEvent], labels: LabelMap, answers: dict[int, UUID]) -> str:
    raise NotImplementedError


def window_labels(
    window: EpisodeWindow,
    candidates: Sequence[CandidateSkill],
    misconceptions: Sequence[KnownMisconception],
    settings: Settings,
) -> LabelMap:
    """Labels of the call: candidates in their order, the tasks of the window by appearance,
    the known misconceptions of the candidates."""
    raise NotImplementedError


def extractor_variables(
    window: EpisodeWindow,
    candidates: Sequence[CandidateSkill],
    misconceptions: Sequence[KnownMisconception],
    labels: LabelMap,
) -> dict[str, str]:
    """The five input blocks of `extractor@3`."""
    raise NotImplementedError


def label_errors(output: ExtractorOutputV3, labels: LabelMap) -> str | None:
    """Т-§4.5: a label the call did not give goes back to the model once."""
    raise NotImplementedError


def extraction_key(episode_seq: int, prompt: str, trigger_seq: int) -> str:
    """WP15 п.5: `obs:{episode_seq}:{extractor@3}:{trigger_seq}` — the call carries the same key."""
    raise NotImplementedError


async def call_extractor(
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    session_id: UUID | None,
    episode_seq: int,
    trigger_seq: int,
    variables: dict[str, str],
    labels: LabelMap,
) -> ExtractorOutputV3:
    """One call of `extractor@3` per episode and trigger; no second opinion (Т-§7.7)."""
    raise NotImplementedError
