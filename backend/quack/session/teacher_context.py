"""Slots of the teacher context (Т-§10.1; ТЗ Ф4 WP14.1): the variables of `teacher@2`.

Nine slots in the fixed order of Т-§10.1, English (Т-§22.2): 1 — doctrine (the prompt text);
2 — tools, elements, output schema; 3 — profile; 4 — domain and goals; 5 — conversation
(`quack.session.conversation`); 6 — goal and plan of the session; 7 — memory picture
(`quack.session.memory_picture`); 8 — material chunks; 9 — label table. Then the tail.

Slots 3 and 4 come from the snapshot at the session start: a change in the middle of the session
is a line of the tail until the session ends and moves into its slot with the next session, so
the prefix cache is not reset (Т-§10.1). A learner skill called with `/name` puts its text into
the tail of this turn only (Т-§17.8). Material text is data: a quote with its source (Т-§19.8).
D-B-159.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from quack.events.records import PlanUpdateRecord
from quack.events.values import Level
from quack.llm.labels import LabelMap

# The slot variables of `teacher@2` in the order of Т-§10.1 (slot 1 is the prompt text), then
# the tail and the guard feedback.
SLOT_VARIABLES = (
    "tools_and_elements",
    "profile",
    "domain_and_goals",
    "conversation",
    "session_plan",
    "memory_picture",
    "materials",
    "labels",
    "tail",
)

# Т-§12.3: the interactive elements the teacher may give.
ELEMENT_KINDS = (
    "choice",
    "why_choice",
    "short_answer",
    "task",
    "scaffold",
    "prediction",
    "free_answer",
    "pair",
    "card_series",
    "timed_quiz",
    "visualization",
    "material_link",
    "reference_card",
)

_CONTROL_WORDS = {
    "tasks": "tasks",
    "colloquium_proofs": "colloquium with proofs",
    "oral_theory": "oral theory",
    "no_goal": "no control",
}

_INTENT_WORDS = {"learn": "Learn", "practice": "Practice", "review": "Review"}


@dataclass(frozen=True)
class Profile:
    """Slot 3 (Т-§9.5): explicit preferences (`preference.set`), what was learned about the
    learner and the teacher manner (`digest.written`)."""

    preferences: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    learned: Sequence[str] = ()
    manner: str | None = None


@dataclass(frozen=True)
class GoalTopic:
    topic_id: UUID
    name: str
    required_levels: Sequence[Level]


@dataclass(frozen=True)
class HubGoal:
    """A hub of slot 4 (Т-§8.5): its deadline and the required levels of its topics."""

    hub_id: UUID
    name: str
    control_type: str
    deadline_at_ms: int | None
    topics: Sequence[GoalTopic] = ()


@dataclass(frozen=True)
class LearnerState:
    """Profile and goals of the learner at one moment."""

    profile: Profile
    hubs: Sequence[HubGoal] = ()


@dataclass(frozen=True)
class FrozenSlots:
    profile: str
    domain_and_goals: str
    changes: list[str]


@dataclass(frozen=True)
class SessionGoal:
    """Slot 6: the intent the session started with (Т-§12.7) and its topic or hub."""

    intent: str
    topic_id: UUID | None = None
    hub_id: UUID | None = None


@dataclass(frozen=True)
class MaterialChunk:
    """A chunk of slot 8 (Т-§10.5): text with the reference to its page or slide."""

    chunk_id: UUID
    material_name: str
    page: int | None
    text: str


@dataclass(frozen=True)
class LearnerSkill:
    """A learner skill called with `/name` (`content.learner_skills`, Т-§17.8)."""

    name: str
    text: str


def render_tools_and_elements() -> str:
    """Slot 2: the memory tools (Т-§10.4) and the element kinds (Т-§12.3); changes with a
    release only."""
    raise NotImplementedError


def render_profile(profile: Profile) -> str:
    raise NotImplementedError


def _date(at_ms: int, timezone: str | None) -> str:
    raise NotImplementedError


def _levels(levels: Sequence[Level]) -> str:
    raise NotImplementedError


def render_goals(hubs: Sequence[HubGoal], labels: LabelMap, timezone: str | None) -> str:
    raise NotImplementedError


def frozen_slots(
    at_start: LearnerState, now: LearnerState, labels: LabelMap, timezone: str | None
) -> FrozenSlots:
    """Slots 3 and 4 from the snapshot at the session start; what changed since — lines of
    the tail (Т-§10.1)."""
    raise NotImplementedError


def render_session_plan(goal: SessionGoal, plan: PlanUpdateRecord | None, labels: LabelMap) -> str:
    """Slot 6 (Т-§12.5): the intent and its target, the plan document of the session."""
    raise NotImplementedError


def render_materials(chunks: Sequence[MaterialChunk], labels: LabelMap) -> str:
    """Slot 8: each chunk as a quote from the material with its source (Т-§19.8)."""
    raise NotImplementedError


def render_labels(labels: LabelMap, names: Mapping[UUID, str]) -> str:
    """Slot 9: every label of the call with what it names; never an id (Т-§4.5)."""
    raise NotImplementedError


def render_tail(changes: Sequence[str], skill: LearnerSkill | None) -> str:
    """The tail: changes of slots 3–4 during the session; a called learner skill — this turn
    only."""
    raise NotImplementedError


@dataclass(frozen=True)
class TeacherSlots:
    frozen: FrozenSlots
    conversation: str
    session_plan: str
    memory_picture: str
    materials: str
    labels: str
    skill: LearnerSkill | None = None


def teacher_variables(slots: TeacherSlots) -> dict[str, str]:
    """The variables of `teacher@2` (WP14.1); `guard_feedback` is empty on the first draft."""
    raise NotImplementedError
