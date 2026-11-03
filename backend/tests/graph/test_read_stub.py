"""ТЗ Ф4 WP6.4, seam S4: signatures of `quack.graph.read` and the double with fixed data."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from pydantic import ValidationError

from quack.graph.read import GraphReader, LevelFact, MisconceptionFact, SliceFocus
from tests.support import graph_read as fx


def _reader(lag_degraded: bool = False) -> GraphReader:
    return fx.FixedGraphReader(lag_degraded=lag_degraded)


def test_slice_has_level_states_for_second_opinion() -> None:
    sl = asyncio.run(_reader().slice_for_turn(fx.LEARNER, UUID(int=1), SliceFocus()))
    by_skill = {s.skill_id: s for s in sl.skills}
    assert by_skill[fx.SKILL_PROVEN].levels[0].proven_by_direct
    assert by_skill[fx.SKILL_FAILED].levels[0].last_t1_failed
    # law 8: unchecked is not failed
    assert by_skill[fx.SKILL_QUIET].levels[0].status == "not_tested"
    assert sl.projected_seq == fx.PROJECTED_SEQ
    assert not sl.lag_degraded


def test_slice_can_be_lagging() -> None:
    sl = asyncio.run(
        _reader(lag_degraded=True).slice_for_turn(fx.LEARNER, UUID(int=1), SliceFocus())
    )
    assert sl.lag_degraded


def test_slice_focus_narrows_skills() -> None:
    focus = SliceFocus(skill_ids=[fx.SKILL_FAILED])
    sl = asyncio.run(_reader().slice_for_turn(fx.LEARNER, UUID(int=1), focus))
    assert [s.skill_id for s in sl.skills] == [fx.SKILL_FAILED]


def test_frontier_is_lowest_open_level_of_the_set() -> None:
    f = asyncio.run(_reader().frontier(fx.SKILL_PROVEN, [4, 3]))
    assert f.level == 4
    assert asyncio.run(_reader().frontier(fx.SKILL_PROVEN, [3])).level is None


def test_readiness_counts_topics() -> None:
    r = asyncio.run(_reader().topic_readiness(fx.HUB))
    assert (r.ready_count, r.total) == (1, 2)


def test_review_candidates_respect_max_items() -> None:
    from quack.graph.read import ReviewScope

    found = asyncio.run(
        _reader().review_candidates(fx.LEARNER, fx.NOW_MS, ReviewScope(max_items=1))
    )
    assert [c.skill_id for c in found] == [fx.SKILL_PROVEN]


def test_prep_context_and_state_at() -> None:
    prep = asyncio.run(_reader().prep_context(fx.HUB, fx.NOW_MS))
    assert prep.days_to_deadline == 5 and prep.candidates
    at = asyncio.run(_reader().state_at(fx.LEARNER, 50, [fx.SKILL_PROVEN]))
    assert at.seq == 50 and at.skills[0].skill_id == fx.SKILL_PROVEN


def test_models_reject_unknown_fields_and_bad_values() -> None:
    with pytest.raises(ValidationError):
        LevelFact.model_validate({"level": 3, "status": "proven", "weight": 0.5})
    with pytest.raises(ValidationError):
        LevelFact.model_validate({"level": 7, "status": "proven"})
    with pytest.raises(ValidationError):
        MisconceptionFact(
            misconception_id=UUID(int=1),
            skill_id=UUID(int=2),
            status="suspected",
            statement="adds denominators",
            quotes=["a", "b", "c"],
        )
    with pytest.raises(ValidationError):  # Т-§9.3: a misconception always has its statement
        MisconceptionFact.model_validate(
            {"misconception_id": UUID(int=1), "skill_id": UUID(int=2), "status": "suspected"}
        )


def test_misconception_carries_its_statement() -> None:
    """D-B-145: `check.model` shows the model `M1. <statement>`."""
    sl = asyncio.run(_reader().slice_for_turn(fx.LEARNER, UUID(int=1), SliceFocus()))
    (found,) = sl.misconceptions
    assert found.misconception_id == fx.MISCONCEPTION
    assert found.statement == fx.MISCONCEPTION_STATEMENT


def test_requires_carry_confidence_for_the_guard_rule() -> None:
    sl = asyncio.run(_reader().slice_for_turn(fx.LEARNER, UUID(int=1), SliceFocus()))
    failed = next(s for s in sl.skills if s.skill_id == fx.SKILL_FAILED)
    assert [(link.confidence, link.has_evidence) for link in failed.requires] == [
        (0.9, True),
        (0.4, False),
    ]
