"""Full-text search over the learner's events (ТЗ Ф4 WP20.5; Т-§3.1, П-3.7).

«Where did I solve the integral»: the query uses the same expression as the index of WP1.1,
`to_tsvector('english', payload ->> 'text')`, over the same event types. Deleted events are
gone from the log (Т-§2.9), so they are never found.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from quack.db import Db

# The event types of the index `idx_events_text` (WP1.1, WP2.3).
TEXT_EVENT_TYPES = (
    "message.sent",
    "answer.submitted",
    "element.responded",
    "turn.committed",
    "canvas.line_committed",
    "voice.transcribed",
    "item.flagged_unclear",
    "chunk.indexed",
    "artifact.updated",
)


@dataclass(frozen=True)
class SearchHit:
    session_id: UUID | None
    seq: int
    type: str
    snippet: str


async def search_events(
    db: Db, *, learner_id: UUID, query: str, domain_id: UUID | None = None, limit: int
) -> list[SearchHit]:
    """Events of the learner whose text matches `query`, best first."""
    raise NotImplementedError
