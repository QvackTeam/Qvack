"""ТЗ Ф4 WP4: the skill fold (`Т-§8.2` «как это работает на числах» — T-F1; `Т-§8.3` — T-F6)."""

from __future__ import annotations

from typing import Any

from quack.graph.projection.skill_fold import FoldEvidence, FoldExposure, FoldParams, fold_skill

P = FoldParams()
H = 3_600_000
DAY = 24 * H


def _ev(n: int, outcome: str = "correct", *, at: int | None = None, **kw: Any) -> FoldEvidence:
    fields: dict[str, Any] = {
        "id": f"e{n}",
        "at_ms": at if at is not None else n * DAY,
        "seq": n,
        "level": 3,
        "outcome": outcome,
        "tier": 1,
        "verification": "code",
        "family_id": f"f{n}",
    } | kw
    return FoldEvidence(**fields)


def _status(evidence: list[FoldEvidence], level: int = 3) -> str:
    return str(fold_skill(evidence, [], P).skill[f"l{level}Status"])


def test_numbers_of_t82() -> None:
    """T-F1: the five examples of `Т-§8.2` with the starting values."""
    one = fold_skill([_ev(1)], [], P).skill
    assert (one["l3Status"], one["l3Basis"], one["l3SuccessW"]) == ("proven", "direct", 1.0)
    assert (one["l1Status"], one["l2Status"]) == ("implied", "unknown")  # 3 ⇒ 1, not 2

    assert _status([_ev(1, options=4)]) == "unknown"  # 0.75
    assert _status([_ev(1, options=4), _ev(2, options=4)]) == "proven"

    transfer: dict[str, Any] = {"derived_kind": "transfer"}
    assert _status([_ev(1, **transfer)]) == "unknown"  # 0.6
    two = fold_skill([_ev(1, **transfer), _ev(2, **transfer)], [], P).skill
    assert (two["l3Status"], two["l3Basis"]) == ("proven", "transfer")  # ≈ 0.96

    five = [_ev(n, at=n * H) for n in range(1, 6)]  # an hour apart: not a memory failure
    assert _status([*five, _ev(6, "incorrect", at=6 * H)]) == "unstable"
    assert _status([*five, _ev(6, "incorrect", at=6 * H), _ev(7, at=7 * H)]) == "proven"

    month = fold_skill([_ev(1), _ev(31, "incorrect")], [], P).skill
    assert month["l3Status"] == "proven"  # forgetting, not misunderstanding
    assert (month["retLapses"], month["retLastLapseAtMs"]) == (1, 31 * DAY)


def test_gate_pair_novelty_and_bypass() -> None:
    model: dict[str, Any] = {"verification": "model", "tier": 2}
    assert _status([_ev(1, **model)]) == "unknown"  # one model verdict — never alone
    assert _status([_ev(1, **model), _ev(2, **model)]) == "proven"  # another family
    assert (
        _status([_ev(1, **model), _ev(2, family_id="f1", verification="model", tier=2)])
        == "unknown"
    )
    assert _status([_ev(1, tier=3), _ev(2, tier=3), _ev(3, tier=3)]) == "unknown"  # T3 behind
    assert _status([_ev(1, "partial")]) == "unknown"
    same = fold_skill([_ev(1, level=4), _ev(2, level=4, family_id="f1")], [], P)
    assert same.evidence["e2"]["novelty"] == "same"
    shown = fold_skill([_ev(1, assistance="shown_solution", task_max_level=4)], [], P).skill
    assert (shown["l3Status"], shown["needsConsolidation"], shown["consolidationLevel"]) == (
        "unknown",
        True,
        4,
    )
    assert (
        fold_skill([_ev(1, assistance="shown_solution"), _ev(2)], [], P).skill["needsConsolidation"]
        is False
    )


def test_fsrs_card_and_reviews() -> None:
    """T-F6: the card starts with the first success behind the gate; a review is only a delayed
    one on a proven level; the hot window is not a review; same input — same `retDueAtMs`."""
    first = fold_skill([_ev(1)], [], P).skill
    assert (first["retState"], first["retReviews"], first["retLastRecallAtMs"]) == (
        "learning",
        1,
        DAY,
    )
    assert int(first["retDueAtMs"]) > DAY  # type: ignore[arg-type]
    hot = [FoldExposure(at_ms=3 * DAY - 60_000, seq=0, kind="example")]
    after_show = fold_skill([_ev(1), _ev(3)], hot, P)
    assert after_show.skill["retReviews"] == 1  # hot window: not a review
    assert after_show.evidence["e3"]["weight"] == 0.5
    review = fold_skill([_ev(1), _ev(3)], [], P).skill
    assert (review["retState"], review["retReviews"]) == ("review", 2)
    assert review == fold_skill([_ev(1), _ev(3)], [], P).skill
    near = fold_skill([_ev(1), _ev(2, at=DAY + H)], [], P).skill
    assert near["retReviews"] == 1  # not delayed: an hour later
