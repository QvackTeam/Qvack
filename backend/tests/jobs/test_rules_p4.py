"""ТЗ Ф4 WP7.1, seam S6, T-D1 (G1 part): every event-only row of the table puts its own kind,
class, `lock_key`, `coalesce_key`, `required_seq`; kinds without a rule are forbidden."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from quack.config import Settings
from quack.events.log import StoredEvent
from quack.jobs import rules_p4 as r
from tests.events.samples import sample_payload, uid

SETTINGS = Settings()
LEARNER = UUID(int=7)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _event(event_type: str, seq: int = 10, **changes: Any) -> StoredEvent:
    payload = {**sample_payload(event_type), **changes.pop("payload", {})}
    return StoredEvent(
        learner_id=LEARNER,
        seq=seq,
        id=seq,
        type=event_type,
        schema_version=1,
        actor="api",
        domain_id=None,
        session_id=changes.pop("session_id", UUID(int=99)),
        causation_seq=None,
        correlation_id=None,
        idempotency_key=f"k{seq}",
        payload_hash="h",
        occurred_at=NOW,
        payload=payload,
        source_refs=[],
    )


def _kinds(event: StoredEvent) -> list[str]:
    return [p.kind for p in r.plan_jobs(event, SETTINGS)]


def _one(event: StoredEvent) -> r.JobPlan:
    (plan,) = r.plan_jobs(event, SETTINGS)
    return plan


def _answer(kind: str, **extra: Any) -> StoredEvent:
    answer = {"kind": kind, "value": "x", **extra}
    return _event("answer.submitted", payload={"answer": answer})


def test_every_kind_of_the_spec_is_listed_once_and_removed_ones_are_gone() -> None:
    assert len(set(r.JOB_KINDS + r.PERIODIC_JOB_KINDS)) == 24 + 5
    assert not set(r.REMOVED_JOB_KINDS) & set(r.JOB_KINDS + r.PERIODIC_JOB_KINDS)


def test_every_rule_row_names_known_kinds() -> None:
    known = set(r.KIND_SPEC)
    for row in r.RULES:
        assert set(row.job_kinds) <= known, row


def test_every_non_periodic_kind_has_a_row() -> None:
    covered = {k for row in r.RULES for k in row.job_kinds}
    assert covered >= set(r.JOB_KINDS) - {"export.data"}  # export.data — by request (WP25)


def test_rows_with_events_exist_in_the_catalog() -> None:
    from quack.events.registry import payload_model

    for row in r.RULES:
        if row.event_type != "*":
            payload_model(row.event_type)


def test_fast_answer_puts_check_symbolic_after_the_delay() -> None:
    plan = _one(_answer("expression", sympy="x+1", latex="x+1"))
    assert plan.kind == "check.symbolic"
    assert plan.priority_class == "P1" and plan.visible
    assert plan.run_at == NOW + timedelta(milliseconds=SETTINGS.symbolic_check_delay_ms)
    assert plan.required_seq is None  # reads only the log
    assert plan.payload["answer_seq"] == 10 and plan.payload["part"] == "main"
    assert _one(_answer("quantity")).kind == "check.symbolic"


def test_number_as_expression_is_fast_plain_number_is_instant() -> None:
    assert _kinds(_answer("number", sympy="2*sqrt(3)")) == ["check.symbolic"]
    assert _kinds(_answer("number")) == []
    assert _kinds(_answer("choice")) == []


@pytest.mark.parametrize("kind", ["proof", "free_text", "drawing"])
def test_slow_answer_puts_check_model(kind: str) -> None:
    plan = _one(_answer(kind))
    assert plan.kind == "check.model" and plan.priority_class == "P1"
    assert plan.job_key.endswith(":10:main")


def test_check_failed_goes_to_check_model_with_the_key_of_its_answer() -> None:
    failed = _event("check.failed", seq=12, payload={"answer_seq": 10, "part": "main"})
    assert _one(failed).job_key == _one(_answer("proof")).job_key  # never doubled


def test_episode_closed_only_with_content() -> None:
    plan = _one(_event("episode.closed"))
    assert plan.kind == "extract.episode" and plan.required_seq == 10
    assert plan.payload["from_seq"] == 1 and plan.payload["to_seq"] == 9
    assert _kinds(_event("episode.closed", payload={"has_content": False})) == []


def test_task_closed_and_session_ended_put_the_analyst_with_one_lock() -> None:
    run = _one(_event("task.closed"))
    assert run.kind == "analyst.run"
    assert run.lock_key == run.coalesce_key == f"analyst:{LEARNER}"
    assert run.required_seq == 10
    run2, deep = r.plan_jobs(_event("session.ended"), SETTINGS)
    assert (run2.kind, deep.kind) == ("analyst.run", "analyst.deep")
    assert deep.lock_key == run2.lock_key
    assert deep.coalesce_key != run2.coalesce_key  # coalescing must not merge the two kinds


def test_digest_with_divergence_puts_analyst_deep() -> None:
    assert _kinds(_event("digest.written", payload={"plan_divergence": True})) == ["analyst.deep"]
    assert _kinds(_event("digest.written", payload={"plan_divergence": False})) == []


def test_verdict_with_misconception_id_puts_analyst_and_describe() -> None:
    event = _event("verdict.recorded", payload={"misconception_id": uid("m")})
    run, describe = r.plan_jobs(event, SETTINGS)
    assert (run.kind, describe.kind) == ("analyst.run", "misconception.describe")
    assert describe.lock_key == f"misconception:{uid('m')}"
    assert describe.priority_class == "P3" and not describe.visible


def test_hypothesis_without_id_gets_the_analyst_only() -> None:
    event = _event("verdict.recorded", payload={"misconception_hypothesis": "drops the minus"})
    assert _kinds(event) == ["analyst.run"]
    assert _kinds(_event("verdict.recorded")) == []


def test_uncertain_diagnosis_asks_for_a_second_opinion() -> None:
    base = sample_payload("observation.diagnosed")["diagnosis"]
    question = {**base, "kind": "question"}
    assert "second_opinion.diagnosis" in _kinds(
        _event("observation.diagnosed", payload={"diagnosis": question})
    )
    error = {**base, "kind": "error"}
    assert "second_opinion.diagnosis" not in _kinds(
        _event("observation.diagnosed", payload={"diagnosis": error})
    )


def test_turn_with_tasks_puts_task_check() -> None:
    plan = _one(_event("turn.committed"))
    assert plan.kind == "task.check" and plan.priority_class == "P1"
    assert plan.payload["task_ids"] == [uid("task")]


def test_photo_uploaded_locks_the_canvas() -> None:
    plan = _one(_event("photo.uploaded", payload={"canvas_id": uid("canvas")}))
    assert plan.kind == "photo.pipeline" and plan.lock_key == f"canvas:{uid('canvas')}"
    # a photo outside a canvas has no canvas lock (D-A-110)
    loose = _one(_event("photo.uploaded", payload={"canvas_id": None}))
    assert loose.lock_key == f"photo:{uid('photo')}"


def test_material_class_depends_on_the_session() -> None:
    inside = _event("material.uploaded", payload={"session_id": uid("s")})
    assert _one(inside).priority_class == "P1"
    outside = _event("material.uploaded", payload={"session_id": None})
    assert _one(outside).priority_class == "P2"


def test_bank_task_gets_a_solution_space_teacher_task_does_not() -> None:
    assert _kinds(_event("task.created", payload={"source": "seminar"})) == ["task.solution_space"]
    assert _kinds(_event("task.created", payload={"source": "teacher"})) == []


def test_agent_request_class_and_kind() -> None:
    event = _event("agent.requested", payload={"kind": "viz", "needed_in_session": True})
    plan = _one(event)
    assert plan.kind == "agent.viz" and plan.priority_class == "P1"
    later = _event("agent.requested", payload={"kind": "artifact", "needed_in_session": False})
    assert _one(later).priority_class == "P2"


def test_known_check_request_is_the_known_claim_check() -> None:
    """B's answer to D-A-110 p.7: `agent.requested {kind: known_check}` -> `check.known_claim`,
    P1 if needed in the session, else P2; keys as for `known.claimed`."""
    topic = uid("topic")
    params = {"topic_id": topic}
    now = _one(
        _event(
            "agent.requested",
            payload={"kind": "known_check", "params": params, "needed_in_session": True},
        )
    )
    claimed = _one(_event("known.claimed"))
    assert now.kind == claimed.kind == "check.known_claim"
    assert now.priority_class == "P1"
    assert (now.lock_key, now.coalesce_key) == (claimed.lock_key, claimed.coalesce_key)
    assert now.required_seq == 10
    assert now.payload["topic_id"] == str(topic)
    assert now.payload["request_id"] == str(uid("request"))
    later = _event(
        "agent.requested",
        payload={"kind": "known_check", "params": params, "needed_in_session": False},
    )
    assert _one(later).priority_class == "P2"


def test_plan_update_cancels_agent_requests() -> None:
    """WP7.4, Т-§13.7: the teacher's `planUpdate.cancel_requests` cancels those requests."""
    first, second = UUID(int=31), UUID(int=32)
    plan_update = {
        **sample_payload("turn.committed")["markup"]["plan_update"],
        "cancel_request_ids": [str(first), str(second)],
    }
    markup = {**sample_payload("turn.committed")["markup"], "plan_update": plan_update}
    event = _event("turn.committed", payload={"markup": markup})
    assert r.cancelled_requests(event) == [first, second]
    assert r.cancelled_requests(_event("turn.committed")) == []
    assert r.cancelled_requests(_event("message.sent")) == []


def test_today_shown_coalesces_per_learner() -> None:
    plan = _one(_event("today.shown"))
    assert plan.kind == "today.prepare"
    assert plan.lock_key == plan.coalesce_key == f"today:{LEARNER}"
    assert plan.job_key == f"today:{LEARNER}:10"


def test_handwriting_known_claim_and_reextraction_rows() -> None:
    assert _one(_event("handwriting.corrected")).kind == "canvas.rediagnose"
    assert _one(_event("known.claimed")).kind == "check.known_claim"
    assert _one(_event("episode.reassigned")).kind == "extract.episode"
    split = _one(_event("skill.split"))
    assert split.kind == "extract.episode" and split.payload["restrict_skill_ids"]


def test_visible_kinds_follow_t_13_8() -> None:
    for kind in ("check.symbolic", "check.model", "material.parse", "photo.pipeline", "agent.viz"):
        assert kind in r.VISIBLE_KINDS
    for kind in ("extract.episode", "embedding.compute", "graph.hygiene", "analyst.run"):
        assert kind not in r.VISIBLE_KINDS
    assert "misconception.describe" not in r.VISIBLE_KINDS


def test_no_rule_for_events_outside_the_table() -> None:
    assert r.plan_jobs(_event("message.sent"), SETTINGS) == []
