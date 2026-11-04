"""The periodic job `calibration.weekly` (ТЗ Ф4 WP7.5; Т-§18.2, Т-§18.5; D-A-219…D-A-221).

Once a week it measures how well the state predicts the next Т1 attempt and **proposes** new
values of the probabilities `p_*`. The proposal goes to the log (`calibration_proposal`); the job
changes nothing: not `Settings`, not the database, no event (Т-§18.5: a person applies it as
`rules@N+1` and a rebuild; the weights never change by themselves).

- The window is the ISO week before the period of the job (D-A-219): the week is over, the
  result of a retry is the same.
- Before each Т1 attempt (a code verdict of a marked task) the state at that moment —
  `GraphReader.state_at(answer_seq − 1)` — gives the probability by the rule of Т-§18.2; the
  outcome is the verdict. Every (skill, level) the task tests is one observation of one rule.
- Per rule: the Brier score, the calibration curve (buckets of the predicted probability) and the
  proposed value. A rule predicts `p × R` (proven direct: `p_proven`; implied or transfer:
  `p_derived`) or `p` alone; the proposal is the value of `p` that makes the predictions of the
  rule add up to the observed successes: `Σ outcome / Σ R` (`R = 1` for a constant rule), kept
  in [0, 1]. Under `calibration_min_reports` observations the rule gets no proposal (law 8).
- The weights of the evidence kinds (Т-§7.4) get no proposal: the documents say «a kind that
  systematically fails to confirm is lowered» without a threshold, a step or the way to blame a
  kind for an attempt (D-A-221).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from quack.config import Settings
from quack.db import Db
from quack.graph.read import GraphReader, LevelFact, SkillFact, create_graph_reader
from quack.jobs.runner import JobContext, register_job_handler
from quack.jobs.types import ClaimedJob
from quack.logging import get_logger

log = get_logger(__name__)

CURVE_DIGITS = 1
RULES: tuple[str, ...] = ("p_proven", "p_derived", "p_unstable", "p_failed", "p_unknown")

# T1 attempts of every learner in the window: a code verdict that is right or wrong, the answer
# and the levels its task tests (the same attempt as the metric `next_attempt_brier`).
_ATTEMPTS = (
    "SELECT v.learner_id, a.seq AS answer_seq, v.payload->>'outcome' AS outcome, "
    "t.payload->'markup'->'tests' AS tests "
    "FROM core.events v "
    "JOIN core.events a ON a.learner_id = v.learner_id AND a.type = 'answer.submitted' "
    "AND a.seq = (v.payload->>'answer_seq')::bigint "
    "JOIN core.events t ON t.learner_id = v.learner_id AND t.type = 'task.created' "
    "AND t.payload->>'task_id' = a.payload->>'task_id' "
    "WHERE v.type = 'verdict.recorded' AND v.occurred_at >= %(since)s "
    "AND v.occurred_at < %(until)s AND v.payload->>'verification' = 'code' "
    "AND v.payload->>'outcome' IN ('correct', 'incorrect') "
    "ORDER BY v.occurred_at, v.learner_id, v.seq"
)


@dataclass
class _Rule:
    """The observations of one rule: predicted probability, `R` (1 for a constant), outcome."""

    predicted: list[float] = field(default_factory=list)
    recall: list[float] = field(default_factory=list)
    outcome: list[float] = field(default_factory=list)


def rule_of(skill: SkillFact | None, level: int) -> tuple[str, float | None]:
    """The rule of Т-§18.2 for the state of one level and its `R`; `R` is `None` when the rule
    needs the recall probability and the state does not know it, and 1.0 for a constant rule."""
    fact: LevelFact | None = (
        next((f for f in skill.levels if f.level == level), None) if skill else None
    )
    if fact is None or fact.status == "not_tested":
        return "p_unknown", 1.0
    if fact.status in {"unstable", "failed"}:
        return f"p_{fact.status}", 1.0
    recall = None if skill is None else skill.recall_probability
    return (
        "p_proven" if fact.status == "proven" and fact.basis == "direct" else "p_derived"
    ), recall


def week_before(period: str) -> tuple[datetime, datetime]:
    """The ISO week before `period` (`2026-45`): Monday 00:00 UTC to the next Monday."""
    year, week = period.split("-")
    start = datetime.fromisocalendar(int(year), int(week), 1).replace(tzinfo=UTC)
    return start - timedelta(days=7), start


async def calibration_proposal(
    db: Db,
    settings: Settings,
    reader: Callable[[UUID], GraphReader],
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """Brier score, calibration curve and the proposed `p_*` per rule over `[since, until)`.
    Reads only; JSON-ready."""
    rows = await db.fetch_all(_ATTEMPTS, {"since": since, "until": until})
    rows = rows[-settings.metrics_brier_max_attempts :]
    observed: dict[str, _Rule] = {name: _Rule() for name in RULES}
    skipped = 0
    for row in rows:
        tested = [t for t in row["tests"] or [] if t.get("skill_id") is not None]
        if not tested:
            continue
        skill_ids = [UUID(str(t["skill_id"])) for t in tested]
        state = await reader(row["learner_id"]).state_at(
            row["learner_id"], int(row["answer_seq"]) - 1, skill_ids
        )
        by_id = {s.skill_id: s for s in state.skills}
        for skill_id, level in dict.fromkeys(
            (UUID(str(t["skill_id"])), int(t["level"])) for t in tested
        ):
            name, recall = rule_of(by_id.get(skill_id), level)
            if recall is None:
                skipped += 1
                continue
            bucket = observed[name]
            bucket.predicted.append(getattr(settings, name) * recall)
            bucket.recall.append(recall)
            bucket.outcome.append(1.0 if row["outcome"] == "correct" else 0.0)
    every = [
        pair
        for rule in observed.values()
        for pair in zip(rule.predicted, rule.outcome, strict=True)
    ]
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "attempts": len(rows),
        "observations": len(every),
        "skipped_unknown_recall": skipped,
        "brier": _brier(every),
        "rules": {name: _rule_report(settings, name, rule) for name, rule in observed.items()},
        "evidence_weights": None,
        "evidence_weights_reason": "no recalculation rule in Т-§7.4, Т-§7.11, Т-§18.5 (D-A-221)",
    }


def _brier(pairs: list[tuple[float, float]]) -> float | None:
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs) if pairs else None


def _rule_report(settings: Settings, name: str, rule: _Rule) -> dict[str, Any]:
    count = len(rule.outcome)
    curve: dict[float, list[float]] = defaultdict(list)
    for p, o in zip(rule.predicted, rule.outcome, strict=True):
        curve[round(p, CURVE_DIGITS)].append(o)
    proposed = None
    if count >= max(1, settings.calibration_min_reports) and sum(rule.recall) > 0:
        proposed = min(1.0, max(0.0, sum(rule.outcome) / sum(rule.recall)))
    return {
        "current": getattr(settings, name),
        "observations": count,
        "brier": _brier(list(zip(rule.predicted, rule.outcome, strict=True))),
        "observed_rate": sum(rule.outcome) / count if count else None,
        "calibration": [
            {"predicted": p, "observed": sum(o) / len(o), "of": len(o)}
            for p, o in sorted(curve.items())
        ],
        "proposed": proposed,
    }


@register_job_handler("calibration.weekly")
async def handle_calibration_weekly(job: ClaimedJob, ctx: JobContext) -> None:
    period = str(job.payload.get("period", ""))
    since, until = week_before(period)

    def reader(learner_id: UUID) -> GraphReader:
        return create_graph_reader(ctx.neo4j, ctx.settings, learner_id=learner_id, db=ctx.db)

    proposal = await calibration_proposal(ctx.db, ctx.settings, reader, since, until)
    log.info("calibration_proposal", period=period, **proposal)
