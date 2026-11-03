"""Memory picture of the teacher context — `renderer@1` (Т-§10.2; ТЗ Ф4 WP14.2, slot 7).

Code renders facts of `quack.graph.read` (seam S4) as words: no numbers of strength, no weights,
no tiers (Т-§7.4); little data is named plainly ("1 time", "not checked"); an empty slot is
better than an irrelevant one. The slice is read with the watermark check and the session
overlay by the caller (Т-§2.6); "due for review" and "fresh in mind" are computed here with the
current time (Т-§8.6). English, like every slot (Т-§10.1, Т-§22.2). D-B-157.

Skills, in this order of importance, at most `memory_skills_max`: the skills of the current task,
the skills of the topics of the session goal, their prerequisites one or two steps away with a
target level not proven or implied, skills of other domains with a proven level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from quack.config import Settings
from quack.events.values import GapType, Level
from quack.graph.read import (
    EvidenceFact,
    LevelFact,
    MemorySlice,
    MisconceptionFact,
    SkillFact,
    SliceFocus,
)
from quack.llm.labels import LabelMap

RENDERER_VERSION = "renderer@1"

# What slot 7 says when the slice could not be read (`teacher@2`, WP6.1 degraded read).
MEMORY_UNAVAILABLE = "memory temporarily unavailable"

_DAY_MS = 86_400_000
_MINUTE_MS = 60_000

# The level names of the doctrine (`teacher@2`, step 1; П-6.1).
LEVEL_NAMES: dict[Level, str] = {
    1: "Recognizes",
    2: "Recalls",
    3: "Applies",
    4: "Knows when to apply",
    5: "Tells apart",
    6: "Composes and explains",
}

_STATUS_WORDS = {
    "proven": "proven",
    "unstable": "not always",
    "failed": "failed",
}

_OUTCOME_WORDS = {
    "correct": "right",
    "incorrect": "wrong",
    "partial": "partly right",
    "unclear": "unclear",
}

# Т-§8.7: the source in words, never a tier.
_SOURCE_WORDS = {
    "code": "checked by code",
    "model": "judged by a model",
    "conversation": "from the conversation",
}

_EXPOSURE_WORDS = {
    "explained": "explanation",
    "example": "worked example",
    "method_named": "method named",
    "solution_shown": "solution shown",
}

# The gap types of the doctrine (`teacher@2`, step 3; П-6.4).
_GAP_WORDS: dict[GapType, str] = {
    "no_idea": "no idea",
    "when_to_apply": "doesn't recognize when to apply",
    "confusion": "mixes it up with a similar idea",
    "execution": "execution error",
    "slip": "slip",
    "misconception": "misconception",
}

_MISCONCEPTION_WORDS = {
    "suspected": "Suspected",
    "confirmed": "Confirmed",
    "in_work": "In work",
    "watching": "Watching",
}


@dataclass(frozen=True)
class RevisedCheck:
    """A revised verdict the teacher has not corrected yet (Т-§5.6, Т-§6.3): the number of the
    answer (`correctionsAcknowledged`) and what changed, in words."""

    answer_seq: int
    text: str


@dataclass(frozen=True)
class PictureInputs:
    """What slot 7 is rendered from. `target_levels` — the target set of each skill (Т-§8.5);
    a skill without one shows the levels it has data on. `evidence` — the deciding evidence by
    id. `gap_type_confidence` — `gapTypeConfidence` (Т-§8.4) by skill; without it the gap type
    is not shown."""

    slice: MemorySlice
    focus: SliceFocus
    skill_names: Mapping[UUID, str]
    target_levels: Mapping[UUID, Sequence[Level]] = field(default_factory=dict)
    evidence: Mapping[UUID, EvidenceFact] = field(default_factory=dict)
    gap_type_confidence: Mapping[UUID, float] = field(default_factory=dict)
    analyst_summary: str | None = None
    agent_results: Sequence[str] = ()
    revised_checks: Sequence[RevisedCheck] = ()


def _reached(level: LevelFact) -> bool:
    raise NotImplementedError


def _targets(skill: SkillFact, inputs: PictureInputs) -> list[LevelFact]:
    raise NotImplementedError


def _below_target(skill: SkillFact, inputs: PictureInputs) -> bool:
    """A prerequisite enters if a level of its target set is not reached, or nothing is known."""
    raise NotImplementedError


def picture_skills(inputs: PictureInputs, settings: Settings) -> list[SkillFact]:
    """The skills of the picture in the order of importance, cut at `memory_skills_max`."""
    raise NotImplementedError


def _when(at_ms: int, now_ms: int) -> str:
    raise NotImplementedError


def _times(count: int) -> str:
    raise NotImplementedError


def _name(skill_id: UUID, inputs: PictureInputs, labels: LabelMap) -> str:
    raise NotImplementedError


def _level_part(level: LevelFact, inputs: PictureInputs, now_ms: int) -> str:
    raise NotImplementedError


def _misconception_part(item: MisconceptionFact, inputs: PictureInputs, labels: LabelMap) -> str:
    raise NotImplementedError


def _retention(skill: SkillFact, settings: Settings, now_ms: int) -> str | None:
    raise NotImplementedError


def _skill_line(
    skill: SkillFact,
    inputs: PictureInputs,
    labels: LabelMap,
    settings: Settings,
    now_ms: int,
) -> str:
    raise NotImplementedError


def render_memory_picture(
    inputs: PictureInputs, labels: LabelMap, settings: Settings, now_ms: int
) -> str:
    """Slot 7 as text; `""` when nothing relevant is known."""
    raise NotImplementedError
