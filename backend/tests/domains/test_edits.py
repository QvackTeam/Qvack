"""ТЗ Ф4 §8.6 (WP8): the edits of the learner and the state at moment N."""

from __future__ import annotations

from neo4j import AsyncDriver

from quack.config import Settings
from quack.db import Db
from tests.review.test_session_summary import SKILL, late_dispute_journey, level3


async def test_state_at_n_with_late_dispute(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    """T-ED5: evidence disputed after N is valid at N; the `summary` of the session shows it
    «до» (proven) and «после» (the dispute applied — no longer proven)."""
    reader, learner, summary, stored = await late_dispute_journey(pg_db, neo4j, settings)
    assert [e.type for e in stored][-1] == "dispute.filed"
    assert summary.before_seq == 9
    at_n = await reader.state_at(learner, summary.before_seq, [SKILL])
    assert at_n.skills[0].levels[2].status == "proven"
    assert level3(summary, "before") == "proven"
    assert level3(summary, "after") != "proven"
    assert summary.skills[0].changed
