"""`calibration.weekly` (ТЗ Ф4 WP7.5; Т-§18.2, Т-§18.5; D-A-219…D-A-221): the Brier score, the
curve and the proposed `p_*` of the week before the period equal the hand count; nothing is
written."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from quack.config import Settings
from quack.db import Db
from quack.events.event_types import AnswerSubmitted, TaskCreated
from quack.events.log import NewEvent, append_events
from quack.events.records import TaskMarkupRecord, TestedLevelRecord
from quack.events.values import AnswerSpec, LearnerAnswer, MathValue, Verdict
from quack.graph.read import GraphReader, StateAt
from quack.jobs.calibration_p4 import calibration_proposal, week_before
from tests.db.fixtures import create_learner
from tests.support import graph_read as fx

SETTINGS = Settings(calibration_min_reports=2)


class _RecallReader(fx.FixedGraphReader):
    """The fixed memory where every skill is recalled with the probability 0.9."""

    async def state_at(self, learner_id: UUID, seq_n: int, skill_ids: Any) -> StateAt:
        state = await super().state_at(learner_id, seq_n, skill_ids)
        skills = [s.model_copy(update={"recall_probability": 0.9}) for s in state.skills]
        return state.model_copy(update={"skills": skills})


async def _attempt(
    db: Db, learner_id: UUID, skill_id: UUID, outcome: str, at: datetime, key: str
) -> None:
    session_id, task_id = uuid4(), uuid4()
    markup = TaskMarkupRecord(
        tests=[TestedLevelRecord(skill_id=skill_id, level=3)],
        method_named=False,
        answer=AnswerSpec(type="number", value=MathValue(latex="1", sympy="1")),
    )

    def event(type_: str, payload: Any, tail: str) -> NewEvent:
        return NewEvent(
            type=type_,
            payload=payload,
            actor="learner" if type_ == "answer.submitted" else "system",
            idempotency_key=f"{key}-{tail}",
            session_id=session_id,
            domain_id=fx.DOMAIN,
            occurred_at=at,
        )

    stored = await append_events(
        db,
        learner_id,
        [
            event(
                "task.created",
                TaskCreated(
                    task_id=task_id,
                    family_id=uuid4(),
                    source="teacher",
                    markup=markup,
                    verification="checked",
                ),
                "t",
            ),
            event(
                "answer.submitted",
                AnswerSubmitted(
                    task_id=task_id,
                    answer=LearnerAnswer(kind="number", value="1"),
                    source="chat",
                ),
                "a",
            ),
        ],
    )
    verdict = Verdict(
        answer_seq=stored[-1].seq,
        part="main",
        outcome=outcome,  # type: ignore[arg-type]  # a literal of the model
        method="exact",
        verification="code",
    )
    await append_events(db, learner_id, [event("verdict.recorded", verdict, "v")])


async def test_calibration_proposal_matches_the_hand_count(pg_db: Db) -> None:
    since, until = week_before("2026-46")
    assert (since, until) == (
        datetime(2026, 11, 2, tzinfo=UTC),
        datetime(2026, 11, 9, tzinfo=UTC),
    )
    inside = since + timedelta(days=2)
    first, second = await create_learner(pg_db), await create_learner(pg_db)
    proven, failed, quiet = fx.SKILL_PROVEN, fx.SKILL_FAILED, fx.SKILL_QUIET
    attempts = [
        (first, proven, "correct"),
        (first, proven, "incorrect"),
        (first, failed, "incorrect"),
        (second, proven, "correct"),
        (second, failed, "correct"),
        (second, quiet, "incorrect"),
    ]
    for i, (learner_id, skill_id, outcome) in enumerate(attempts):
        await _attempt(pg_db, learner_id, skill_id, outcome, inside, f"in{i}")
    # A week earlier: not in the window.
    await _attempt(pg_db, first, proven, "incorrect", since - timedelta(days=1), "old")
    events_before = (await pg_db.fetch_one("SELECT count(*) AS n FROM core.events"))["n"]  # type: ignore[index]

    def reader(_learner: UUID) -> GraphReader:
        return _RecallReader()

    result = await calibration_proposal(pg_db, SETTINGS, reader, since, until)

    # p_proven × R = 0.9 × 0.9 = 0.81 on outcomes 1, 0, 1; p_failed 0.2 on 0, 1; p_unknown 0.4 on 0.
    assert result["attempts"] == 6 and result["observations"] == 6
    assert result["brier"] == pytest.approx((2 * 0.19**2 + 0.81**2 + 0.2**2 + 0.8**2 + 0.4**2) / 6)
    rules = result["rules"]
    assert rules["p_proven"]["brier"] == pytest.approx((2 * 0.19**2 + 0.81**2) / 3)
    assert rules["p_proven"]["calibration"] == [{"predicted": 0.8, "observed": 2 / 3, "of": 3}]
    assert rules["p_proven"]["proposed"] == pytest.approx(2 / (3 * 0.9))
    assert rules["p_failed"]["observed_rate"] == pytest.approx(0.5)
    assert rules["p_failed"]["proposed"] == pytest.approx(0.5)
    # One observation of `p_unknown` is under `calibration_min_reports`: no proposal.
    assert rules["p_unknown"]["observations"] == 1 and rules["p_unknown"]["proposed"] is None
    assert rules["p_derived"]["observations"] == 0 and rules["p_derived"]["brier"] is None
    assert result["evidence_weights"] is None
    # Reading only: no event, no new value of the settings.
    events_after = (await pg_db.fetch_one("SELECT count(*) AS n FROM core.events"))["n"]  # type: ignore[index]
    assert events_after == events_before
    assert SETTINGS.p_proven == 0.9 and SETTINGS.p_failed == 0.2
