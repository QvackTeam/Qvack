"""`GraphReader` — signatures of the shared memory read (ТЗ Ф4 WP6.4, seam S4).

Every method reads with the watermark check (Т-§2.6, `snapshot_read_retries`); methods that
serve a turn take the session overlay. The real implementation is WP6.4 (G2); streams B and C
test against `tests/support/graph_read.py`. `materials_prefetch` / `materials_search` live in
`quack/graph/read/materials.py` (stream C).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from quack.events.values import Level
from quack.graph.overlay import SessionOverlay
from quack.graph.read.models import (
    EvidenceFact,
    ExtractionCandidates,
    Frontier,
    HubReadiness,
    MemorySlice,
    PastSolution,
    PrepContext,
    PrerequisiteFact,
    ReviewCandidate,
    ReviewScope,
    SimilarMistake,
    SliceFocus,
    StateAt,
    TopicRequires,
    WhyFacts,
)


class GraphReader(Protocol):
    async def slice_for_turn(
        self,
        learner_id: UUID,
        session_id: UUID,
        focus: SliceFocus,
        overlay: SessionOverlay | None = None,
    ) -> MemorySlice: ...

    async def frontier(
        self, skill_id: UUID, target_levels: Sequence[Level], overlay: SessionOverlay | None = None
    ) -> Frontier: ...

    async def topic_readiness(self, hub_id: UUID) -> HubReadiness: ...

    async def why(self, topic_id: UUID, level: Level | None = None) -> WhyFacts: ...

    async def topic_requires(self, domain_id: UUID) -> list[TopicRequires]: ...

    async def recall_probability(self, skill_id: UUID, now_ms: int) -> float | None: ...

    async def review_candidates(
        self, learner_id: UUID, now_ms: int, scope: ReviewScope | None = None
    ) -> list[ReviewCandidate]: ...

    async def prep_context(self, hub_id: UUID, now_ms: int) -> PrepContext: ...

    async def skill_history(
        self, skill_id: UUID, level: Level | None = None, limit: int = 10
    ) -> list[EvidenceFact]: ...

    async def prerequisites(self, skill_id: UUID, limit: int = 10) -> list[PrerequisiteFact]: ...

    async def similar_mistakes(
        self, learner_id: UUID, evidence_id: UUID | None = None, text: str | None = None
    ) -> list[SimilarMistake]: ...

    async def past_solution(
        self, learner_id: UUID, task_id: UUID | None = None, skill_id: UUID | None = None
    ) -> list[PastSolution]: ...

    async def state_at(
        self, learner_id: UUID, seq_n: int, skill_ids: Sequence[UUID]
    ) -> StateAt: ...

    async def extraction_candidates(
        self,
        learner_id: UUID,
        session_id: UUID,
        episode_vector: Sequence[float] | None,
        k: int,
        *,
        topic_id: UUID | None = None,
        skill_ids: Sequence[UUID] | None = None,
    ) -> ExtractionCandidates:
        """Candidates of the extractor (WP15 п.2, п.6; D-A-135): the skills of the topics active
        in the session plus the nearest to `episode_vector` by `skill_emb`, at most `k`; no
        vector (Modal is down) — the session's skills only. `topic_id` / `skill_ids` restrict
        re-extraction to a topic (`episode.reassigned`) or to skills (`skill.split`)."""
        ...
