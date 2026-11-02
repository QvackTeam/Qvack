"""ТЗ Ф4 §8.9 T-TT8: the effort of the teacher call by the table of Т-§12.9 (WP13.8): `high`
— session start and goal change, building a plan, review of a proof, the second failure in a
row on the same skill; `low` otherwise; `teacher_fallback` — always `low`."""

from __future__ import annotations

from typing import Any

import pytest

from quack.session.turn_policy import teacher_reasoning_effort

HIGH_SITUATIONS = ["is_first_turn", "goal_changed", "builds_plan", "proof_answer"]


def _effort(role: str = "teacher", **situation: Any) -> str:
    return teacher_reasoning_effort(
        role=role,  # type: ignore[arg-type]
        is_first_turn=situation.pop("is_first_turn", False),
        session_evaluations=[],
        **situation,
    )


@pytest.mark.parametrize("situation", HIGH_SITUATIONS)
def test_table_situations_are_high(situation: str) -> None:
    assert _effort(**{situation: True}) == "high"


@pytest.mark.parametrize("situation", HIGH_SITUATIONS)
def test_fallback_is_always_low(situation: str) -> None:
    assert _effort("teacher_fallback", **{situation: True}) == "low"


def test_everything_else_is_low() -> None:
    """Reaction to an answer, a hint, an explanation, a «why» question (Т-§12.9)."""
    assert _effort() == "low"
