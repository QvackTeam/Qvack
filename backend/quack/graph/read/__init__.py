"""`quack.graph.read` — the shared read of memory (ТЗ Ф4 WP6.4, seam S4, §4.1).

Product packages read memory only through this package. G1 fixes the signatures and the
response models; the implementation arrives at G2 (WP6.4). The test double with fixed data is
`tests/support/graph_read.py` (`FixedGraphReader`).
"""

from quack.graph.read.models import (
    CandidateSkill,
    EvidenceFact,
    ExposureFact,
    ExtractionCandidates,
    Frontier,
    HubReadiness,
    LevelFact,
    MaterialRef,
    MemorySlice,
    MisconceptionFact,
    PastSolution,
    PrepContext,
    PrerequisiteFact,
    RequiresLink,
    ReviewCandidate,
    ReviewScope,
    RootCauseFact,
    SimilarMistake,
    SkillFact,
    SliceFocus,
    StateAt,
    TopicRequires,
    WhyFacts,
)
from quack.graph.read.reader import GraphReader

__all__ = [
    "CandidateSkill",
    "EvidenceFact",
    "ExposureFact",
    "ExtractionCandidates",
    "Frontier",
    "GraphReader",
    "HubReadiness",
    "LevelFact",
    "MaterialRef",
    "MemorySlice",
    "MisconceptionFact",
    "PastSolution",
    "PrepContext",
    "PrerequisiteFact",
    "RequiresLink",
    "ReviewCandidate",
    "ReviewScope",
    "RootCauseFact",
    "SimilarMistake",
    "SkillFact",
    "SliceFocus",
    "StateAt",
    "TopicRequires",
    "WhyFacts",
]
