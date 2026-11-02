"""ТЗ Ф4 §8.9 T-TT4 (pure part): head and markup rules of Т-§12.4 (WP13.5) — honest verdict,
the turn is marked. «Do not jump the boundary» needs `REQUIRES` from memory (S4); the retry
before the body is shown is the turn graph (WP13.2)."""

from __future__ import annotations

from typing import Any

import pytest

from quack.practice.check import Verdict
from quack.session.guards import (
    GuardViolation,
    head_violations,
    markup_violations,
    settle_stance,
)
from quack.session.teacher_output import TurnHead, TurnMarkup

SKILLS = {"S1", "S2"}
MISCONCEPTIONS = {"M1"}


def _head(**fields: Any) -> TurnHead:
    base: dict[str, Any] = {
        "intent": "feedback",
        "targetSkills": ["S1"],
        "verdict_stance": None,
        "branchType": None,
        "approach": "none",
    }
    return TurnHead.model_validate({**base, **fields})


def _verdict(verification: str) -> Verdict:
    return Verdict.model_validate(
        {
            "answer_seq": 4,
            "part": "main",
            "outcome": "incorrect",
            "method": "exact" if verification == "code" else "model",
            "verification": verification,
        }
    )


def _markup(**fields: Any) -> TurnMarkup:
    base: dict[str, Any] = {
        "tasks": [],
        "elements": [],
        "exposures": [],
        "targetsMisconception": None,
        "planUpdate": {
            "completed_steps": [],
            "current_step": "s",
            "next_steps": [],
            "branches": [],
            "cancel_requests": [],
        },
        "agentRequests": [],
        "correctionsAcknowledged": [],
        "decisionReason": "r",
        "deadline": None,
    }
    return TurnMarkup.model_validate({**base, **fields})


def _reasons(violations: list[GuardViolation]) -> list[str]:
    return [v.reason for v in violations]


@pytest.mark.parametrize(
    ("stance", "verdict", "ok"),
    [
        ("code", "code", True),
        ("code", "model", False),
        ("code", None, False),
        ("formative", "model", True),
        ("formative", "code", True),
        (None, None, True),
    ],
)
def test_honest_verdict(stance: str | None, verdict: str | None, ok: bool) -> None:
    violations = head_violations(
        _head(verdict_stance=stance),
        answered_verdict=None if verdict is None else _verdict(verdict),
        skill_labels=SKILLS,
    )
    assert _reasons(violations) == ([] if ok else ["stance_without_code_verdict"])


def test_turn_without_target_skills_is_not_marked() -> None:
    violations = head_violations(_head(targetSkills=[]), answered_verdict=None, skill_labels=SKILLS)
    assert _reasons(violations) == ["no_target_skills"]


def test_unknown_target_skill_label() -> None:
    violations = head_violations(
        _head(targetSkills=["S1", "S9"]), answered_verdict=None, skill_labels=SKILLS
    )
    assert _reasons(violations) == ["unknown_skill_label"]
    assert "S9" in violations[0].detail


def test_markup_labels_must_exist() -> None:
    markup = _markup(
        exposures=[
            {"skill": "S2", "kind": "explained", "approach": "none"},
            {"skill": "S7", "kind": "example", "approach": "none"},
        ],
        targetsMisconception="M5",
    )
    violations = markup_violations(markup, skill_labels=SKILLS, misconception_labels=MISCONCEPTIONS)
    assert _reasons(violations) == ["unknown_skill_label", "unknown_misconception_label"]


def test_marked_markup_passes() -> None:
    markup = _markup(
        exposures=[{"skill": "S1", "kind": "explained", "approach": "none"}],
        targetsMisconception="M1",
    )
    assert markup_violations(markup, skill_labels=SKILLS, misconception_labels=MISCONCEPTIONS) == []


@pytest.mark.parametrize(
    ("stance", "verdict", "settled"),
    [
        ("code", None, "formative"),
        ("code", "model", "formative"),
        ("code", "code", "code"),
        ("formative", "code", "formative"),  # code never raises the stance
        (None, "code", None),
    ],
)
def test_settle_stance_only_lowers(
    stance: str | None, verdict: str | None, settled: str | None
) -> None:
    head = settle_stance(
        _head(verdict_stance=stance), None if verdict is None else _verdict(verdict)
    )
    assert head.verdict_stance == settled
