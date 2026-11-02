"""Defensive rules of a teacher turn checked by code (Т-§12.4; ТЗ Ф4 WP13.5), pure part.

Head (`p1_head`, before any body character is shown): honest verdict — `verdict_stance =
code` only when the turn answers an answer with a code-class verdict; the turn is marked —
`targetSkills` is not empty and every label exists. Markup (`p3_markup`): exposures and
`targetsMisconception` reference existing labels. A violation returns the turn to the model
with its reasons (WP13.2 `guard`, up to `guard_max_retries`); what happens after the retries
is the caller's: `settle_stance` lowers `code` to `formative` [РЕШЕНИЕ Ф4 WP13.5], an
unmarked turn is shown and logged. «Do not jump the boundary» reads `REQUIRES` from memory
(seam S4) and lands with it.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from quack.practice.check import Verdict
from quack.session.teacher_output import TurnHead, TurnMarkup

type GuardReason = Literal[
    "stance_without_code_verdict",
    "no_target_skills",
    "unknown_skill_label",
    "unknown_misconception_label",
]


@dataclass(frozen=True)
class GuardViolation:
    reason: GuardReason
    detail: str


def head_violations(
    head: TurnHead, *, answered_verdict: Verdict | None, skill_labels: Collection[str]
) -> list[GuardViolation]:
    """Violations of the head rules (Т-§12.4: honest verdict, the turn is marked)."""
    violations: list[GuardViolation] = []
    if head.verdict_stance == "code" and not _code_verdict(answered_verdict):
        violations.append(
            GuardViolation(
                "stance_without_code_verdict",
                "verdict_stance code needs a code-class verdict of the answered answer",
            )
        )
    if not head.target_skills:
        violations.append(GuardViolation("no_target_skills", "targetSkills is empty"))
    violations.extend(_unknown("unknown_skill_label", head.target_skills, skill_labels))
    return violations


def markup_violations(
    markup: TurnMarkup, *, skill_labels: Collection[str], misconception_labels: Collection[str]
) -> list[GuardViolation]:
    """Violations of «the turn is marked» in `p3_markup`: unknown labels of exposures and of
    `targetsMisconception`."""
    violations = _unknown("unknown_skill_label", [e.skill for e in markup.exposures], skill_labels)
    if markup.targets_misconception is not None:
        violations.extend(
            _unknown(
                "unknown_misconception_label",
                [markup.targets_misconception],
                misconception_labels,
            )
        )
    return violations


def settle_stance(head: TurnHead, answered_verdict: Verdict | None) -> TurnHead:
    """After the retries: `code` without a code verdict becomes `formative`; code never
    raises the stance."""
    if head.verdict_stance == "code" and not _code_verdict(answered_verdict):
        return head.model_copy(update={"verdict_stance": "formative"})
    return head


def _code_verdict(verdict: Verdict | None) -> bool:
    return verdict is not None and verdict.verification == "code"


def _unknown(
    reason: GuardReason, labels: list[str], known: Collection[str]
) -> list[GuardViolation]:
    missing = [label for label in labels if label not in known]
    if not missing:
        return []
    return [GuardViolation(reason, f"unknown labels: {', '.join(dict.fromkeys(missing))}")]
