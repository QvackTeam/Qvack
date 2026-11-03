"""Response models of `quack.graph.read` (ТЗ Ф4 WP6.4, seam S4).

Facts with ids, never text and never weights (Т-§10.2, Т-§7.4): the teacher context renderer
and the API turn them into words. "Not checked" is its own value, distinct from "failed"
(law 8): a level without data has status `not_tested`.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quack.events.values import GapType, Level


class _Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


type LevelStatus = Literal["proven", "implied", "unstable", "failed", "not_tested"]
# `direct` — proven by the learner's own check; `transfer` — through another domain (Т-§8.5).
type LevelBasis = Literal["direct", "transfer"]
# Т-§8.7: the tier in words is derived from it — `code`, `model`, `conversation`.
type EvidenceSource = Literal["code", "model", "conversation"]
type MisconceptionStatus = Literal["suspected", "confirmed", "in_work", "watching"]
# Т-§14.1: the reasons a skill is a review candidate.
type ReviewReason = Literal[
    "retention", "consolidation", "misconception_recheck", "hub_requirement"
]


class EvidenceFact(_Fact):
    """One piece of evidence for a level (Т-§8.7): quote, task, tier by code, date, id for
    the "disagree" action (Т-§2.8)."""

    evidence_id: UUID
    skill_id: UUID
    level: Level
    outcome: Literal["correct", "incorrect", "partial", "unclear"]
    source: EvidenceSource
    quote: str | None = None
    task_id: UUID | None = None
    session_id: UUID | None = None
    seq: int
    occurred_at_ms: int


class LevelFact(_Fact):
    """State of one level of a skill. `proven_by_direct` and `last_t1_failed` are the inputs
    of the second-opinion triggers of stream B (Т-§7.7, WP11.6): proven by a direct Т1/Т2;
    the latest Т1 of the level by time is a failure."""

    level: Level
    status: LevelStatus
    basis: LevelBasis | None = None
    deciding_evidence_id: UUID | None = None
    evidence_count: int = Field(default=0, ge=0)
    proven_by_direct: bool = False
    last_t1_failed: bool = False


class ExposureFact(_Fact):
    """A shown explanation or example (Т-§10.2, "shown")."""

    exposure_id: UUID
    kind: str
    seq: int
    occurred_at_ms: int


class RequiresLink(_Fact):
    """`REQUIRES` between skills with its confidence (Т-§7.9); the guard rule "do not jump over
    the frontier" (WP13.5) takes the links with `confidence >= requires_min_confidence`."""

    skill_id: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    has_exposure: bool = False
    has_evidence: bool = False


class SkillFact(_Fact):
    skill_id: UUID
    topic_id: UUID | None = None
    domain_id: UUID | None = None
    levels: list[LevelFact] = []
    # Retention is computed at read time with the current time (Т-§8.3, Т-§10.2).
    recall_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    due_at_ms: int | None = None
    consolidation_flag: bool = False
    # `Т-§8.4`: the weighted majority of the last negative evidence and its share of votes; the
    # teacher sees the type only above `gap_type_min_confidence` (WP14.2).
    gap_type: GapType | None = None
    gap_type_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # `Т-§8.2` п.3: the last failure after a delay on a proven level — «забыл» (retLastLapseAtMs);
    # None — no lapse yet (law 8).
    last_lapse_at_ms: int | None = None
    exposures: list[ExposureFact] = []
    requires: list[RequiresLink] = []


class MisconceptionFact(_Fact):
    """`statement` — the extractor's wording of a new one, rewritten by the analyst on
    confirmation (Т-§9.3); `check.model` shows it to the model (D-B-145). `triggers` — the
    conditions it shows in, written with the statement (`misconception.described`, WP14.2)."""

    misconception_id: UUID
    skill_id: UUID
    status: MisconceptionStatus
    statement: str
    triggers: list[str] = []
    confused_with_skill_id: UUID | None = None
    manifestation_count: int = Field(default=0, ge=0)
    quotes: list[str] = Field(default=[], max_length=2)


class RootCauseFact(_Fact):
    """A prerequisite several error hypotheses point to (Т-§9.4)."""

    skill_id: UUID
    hypothesis_count: int = Field(ge=1)


class SliceFocus(_Fact):
    """What the teacher is looking at: skills of the task, topics of the session goal (Т-§10.2)."""

    skill_ids: list[UUID] = []
    topic_ids: list[UUID] = []
    domain_id: UUID | None = None


class MemorySlice(_Fact):
    """`slice_for_turn` (Т-§10.2, Т-§2.6): `projected_seq` — the watermark the slice was read
    at; `lag_degraded` — the projector did not catch up in time and guard rules rely on the
    session overlay; `stable` — the watermark did not move during the read."""

    learner_id: UUID
    projected_seq: int
    lag_degraded: bool = False
    stable: bool = True
    skills: list[SkillFact] = []
    misconceptions: list[MisconceptionFact] = []
    root_causes: list[RootCauseFact] = []


class Frontier(_Fact):
    """`frontier`: the lowest level of the target set that is neither proven nor implied
    (Т-§8.5); `None` — the whole set is reached."""

    skill_id: UUID
    level: Level | None


class HubReadiness(_Fact):
    """`topic_readiness` (Т-§14.5): "9 of 14 topics are ready", direct basis only."""

    hub_id: UUID
    ready_topic_ids: list[UUID] = []
    not_ready_topic_ids: list[UUID] = []

    @property
    def ready_count(self) -> int:
        return len(self.ready_topic_ids)

    @property
    def total(self) -> int:
        return len(self.ready_topic_ids) + len(self.not_ready_topic_ids)


class WhyFacts(_Fact):
    """`why` (Т-§8.7): the deciding evidence of the level and the latest `why_recent_n`."""

    topic_id: UUID
    level: Level | None = None
    deciding: EvidenceFact | None = None
    recent: list[EvidenceFact] = []


class TopicRequires(_Fact):
    """A derived link between topics (Т-§4.6); weight — the number of skill links."""

    from_topic_id: UUID
    to_topic_id: UUID
    weight: int = Field(ge=1)


class ReviewScope(_Fact):
    """Narrows the candidates (Т-§14.2): a topic or a hub, a session goal, a time limit."""

    topic_id: UUID | None = None
    hub_id: UUID | None = None
    goal_skill_ids: list[UUID] = []
    max_items: int | None = Field(default=None, ge=1)


class ReviewCandidate(_Fact):
    """A skill with a reason to repeat (Т-§14.1); the queue is never stored."""

    skill_id: UUID
    priority: float
    reasons: list[ReviewReason] = Field(min_length=1)
    is_goal_prerequisite: bool = False


class MaterialRef(_Fact):
    """A found piece of a control context: a past exam variant, a question list, criteria."""

    chunk_id: UUID
    material_id: UUID
    kind: Literal["sample_exam", "past_variant", "question_list", "criteria"]
    page: int | None = None


class PrepContext(_Fact):
    """`prep_context` (Т-§14.7, WP17.4): data of slot 6 in the preparation mode."""

    hub_id: UUID
    days_to_deadline: int | None = None
    ready_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    coverage_topic_ids: list[UUID] = []
    control_materials: list[MaterialRef] = []
    candidates: list[ReviewCandidate] = []


class PrerequisiteFact(_Fact):
    skill_id: UUID
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    levels: list[LevelFact] = []


class SimilarMistake(_Fact):
    evidence_id: UUID
    skill_id: UUID
    domain_id: UUID | None = None
    quote: str | None = None


class PastSolution(_Fact):
    task_id: UUID | None = None
    skill_id: UUID
    lines: list[str] = []
    occurred_at_ms: int


class StateAt(_Fact):
    """`state_at` (WP8.3, Т-§2.6): the state replayed up to event N by the same handlers and
    folds; a fold over `seq ≤ N` is forbidden (wrong with late edits)."""

    learner_id: UUID
    seq: int
    skills: list[SkillFact] = []
