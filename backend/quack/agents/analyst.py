"""The frontier analyst, WP16.1 (ТЗ Ф4; Т-§13.5, Т-§13.2, Т-§9.5; `T-AG1`). D-B-176.

- Roles: `analyst` (Spark); `analyst_deep` (Wonder) at the end of the session and after a digest
  with `plan_divergence`; both render `analyst@1`.
- Input: structure only (law 10) — the target skills and their prerequisites, misconceptions,
  evidence of the recent episodes, the session plan, goals, the profile; the previous digest and
  manner are never an input (`T-AG1`). The memory blocks are rendered by the caller from
  `quack.graph.read`; the evidence block is rendered here from `observation.extracted`.
- Output `AnalystOutput` with labels; a label the call did not give goes back once (Т-§4.5), an
  item still wrong after that is dropped.
- Write: `digest.written {domain_id, text, as_of_seq, structured, plan_divergence, manner}` and
  one `agent.requested` from actor `agent:analyst` per forecast item (Т-§13.2), in one
  transaction (law 7), with keys from the trigger (law 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid5

from quack.agents.schemas import AnalystOutput
from quack.config import Settings
from quack.db.db import Db
from quack.events.event_types import AgentRequested, DigestWritten, ObservationExtracted
from quack.events.log import NewEvent, StoredEvent, append_events
from quack.events.records import (
    AgentParamsRecord,
    DigestStructuredRecord,
    FrontierItemRecord,
    GapHypothesisRecord,
    PreparationRecord,
    SuggestedMoveRecord,
    UncertaintyRecord,
)
from quack.llm.gateway import LLMGateway
from quack.llm.labels import LabelMap

ANALYST_ROLE = "analyst"
DEEP_ROLE = "analyst_deep"
ANALYST_ACTOR = "agent:analyst"
NONE_LINE = "(none)"

_OUTCOME = {"correct": "correct", "incorrect": "incorrect", "partial": "partly correct"}
_HELP = {"none": "on their own", "hint": "after a hint", "shown_solution": "after the solution"}


@dataclass(frozen=True)
class AnalystInput:
    """The blocks of `analyst@1` rendered by the caller, and the labels they use."""

    domain_id: UUID
    session_id: UUID | None
    as_of_seq: int
    skills_state: str
    misconceptions: str
    session_plan: str
    goals: str
    profile: str
    labels: LabelMap


def render_evidence(observations: Sequence[StoredEvent], labels: LabelMap) -> str:
    """Accepted elements of `observation.extracted`, one line each: skill, level, outcome, help,
    gap type, quote. Skills without a label are not in the input."""
    lines: list[str] = []
    for event in observations:
        for element in ObservationExtracted.model_validate(event.payload).elements:
            skill = labels.label("skill", element.skill_id) if element.skill_id else None
            if skill is None or element.kind != "evidence":
                continue
            outcome = _OUTCOME.get(element.outcome or "", "not judged")
            level = f" level {element.level}" if element.level is not None else ""
            gap = f", gap: {element.gap_type}" if element.gap_type != "none" else ""
            lines.append(
                f'{skill}{level}: {outcome}, {_HELP[element.help]}{gap}; "{element.quote}"'
            )
    return "\n".join(lines) or NONE_LINE


def _skill_ok(labels: LabelMap, label: str | None) -> bool:
    return label is None or label in labels.labels("skill")


def _misconception_ok(labels: LabelMap, label: str | None) -> bool:
    return label is None or label in labels.labels("misconception")


def analyst_errors(output: AnalystOutput, labels: LabelMap) -> str | None:
    """Т-§4.5: labels of the frontier, the hypotheses and the forecast must be given ones."""
    unknown = [
        *(f.skill for f in output.frontier if not _skill_ok(labels, f.skill)),
        *(g.skill for g in output.gap_hypotheses if not _skill_ok(labels, g.skill)),
        *(p.skill for p in output.forecast if p.skill and not _skill_ok(labels, p.skill)),
        *(
            p.misconception
            for p in output.forecast
            if p.misconception and not _misconception_ok(labels, p.misconception)
        ),
    ]
    if not unknown:
        return None
    return "unknown labels: " + ", ".join(dict.fromkeys(unknown)) + "; use only the given labels"


def digest_structured(output: AnalystOutput, labels: LabelMap) -> DigestStructuredRecord:
    """Labels become ids; an item with an unknown label is dropped."""
    skills = labels.labels("skill")
    misconceptions = labels.labels("misconception")
    forecast = [
        PreparationRecord(
            kind=p.kind,
            skill_id=skills[p.skill] if p.skill else None,
            level=p.level,
            misconception_id=misconceptions[p.misconception] if p.misconception else None,
            description=p.description,
        )
        for p in output.forecast
        if _skill_ok(labels, p.skill) and _misconception_ok(labels, p.misconception)
    ]
    return DigestStructuredRecord(
        frontier=[
            FrontierItemRecord(skill_id=skills[f.skill], level=f.level, state=f.state)
            for f in output.frontier
            if f.skill in skills
        ],
        gap_hypotheses=[
            GapHypothesisRecord(skill_id=skills[g.skill], gap_type=g.gap_type, reason=g.reason)
            for g in output.gap_hypotheses
            if g.skill in skills
        ],
        uncertainty=UncertaintyRecord(
            question=output.uncertainty.question, resolving_task=output.uncertainty.resolving_task
        )
        if output.uncertainty
        else None,
        moves=[SuggestedMoveRecord(move=m.move, reason=m.reason) for m in output.moves],
        forecast=forecast,
    )


def digest_key(domain_id: UUID, trigger_seq: int, role: str) -> str:
    return f"digest:{domain_id}:{trigger_seq}:{role}"


async def run_analyst(
    db: Db,
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    trigger_seq: int,
    deep: bool,
    facts: AnalystInput,
    observations: Sequence[StoredEvent],
) -> list[StoredEvent]:
    """One call of `analyst` or `analyst_deep`; the digest and the forecast requests."""
    role = DEEP_ROLE if deep else ANALYST_ROLE
    prompt = settings.llm_roles[role].prompt
    if prompt is None:
        raise ValueError(f"role {role!r} has no prompt")
    role_of_prompt, version = prompt.rsplit("@", 1)
    key = digest_key(facts.domain_id, trigger_seq, role)
    result = await gateway.generate_structured(
        role,
        int(version),
        AnalystOutput,
        {
            "skills_state": facts.skills_state or NONE_LINE,
            "misconceptions": facts.misconceptions or NONE_LINE,
            "evidence": render_evidence(observations, facts.labels),
            "session_plan": facts.session_plan or NONE_LINE,
            "goals": facts.goals or NONE_LINE,
            "profile": facts.profile or NONE_LINE,
        },
        learner_id,
        facts.session_id,
        None,
        key,
        prompt_role=role_of_prompt,
        check=lambda output: analyst_errors(output, facts.labels),
    )
    output = result.value
    structured = digest_structured(output, facts.labels)
    digest = NewEvent(
        type="digest.written",
        payload=DigestWritten(
            domain_id=facts.domain_id,
            text=output.text,
            as_of_seq=facts.as_of_seq,
            structured=structured,
            plan_divergence=output.plan_divergence,
            manner=output.manner,
        ),
        actor=prompt,
        idempotency_key=key,
        domain_id=facts.domain_id,
        session_id=facts.session_id,
        causation_seq=trigger_seq,
    )
    namespace = uuid5(facts.domain_id, key)
    requests = [
        NewEvent(
            type="agent.requested",
            payload=AgentRequested(
                request_id=uuid5(namespace, str(index)),
                kind=item.kind,
                params=AgentParamsRecord(
                    skill_id=item.skill_id,
                    level=item.level,
                    misconception_id=item.misconception_id,
                    description=item.description,
                ),
                needed_in_session=False,
            ),
            actor=ANALYST_ACTOR,
            idempotency_key=f"{key}:request:{index}",
            domain_id=facts.domain_id,
            session_id=facts.session_id,
            causation_seq=trigger_seq,
        )
        for index, item in enumerate(structured.forecast)
    ]
    async with db.transaction():
        return await append_events(db, learner_id, [digest, *requests])
