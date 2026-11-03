"""The extractor by episodes, WP15 п.1–3 (ТЗ Ф4; Т-§7.5, Т-§7.6; `T-X1` window part): the
window, the input of `extractor@3` with labels, the call of the role (D-B-162)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from quack.agents.extract_episode import (
    GAP_TYPE_TABLE,
    NONE_LINE,
    CandidateSkill,
    KnownMisconception,
    call_extractor,
    candidate_skill_ids,
    extraction_key,
    extraction_window,
    extractor_variables,
    label_errors,
    window_labels,
)
from quack.agents.schemas import ExtractedElement, ExtractorOutputV3
from quack.config import Settings
from quack.events.event_types import (
    AnswerSubmitted,
    CanvasLineCommitted,
    HintShown,
    ItemFlaggedUnclear,
    MessageSent,
    TurnCommitted,
    VoiceTranscribed,
)
from quack.events.log import StoredEvent
from quack.events.records import (
    BodyBlockRecord,
    ElementRecord,
    ExposureRecord,
    PlanUpdateRecord,
    TaskElementRecord,
    TestedLevelRecord,
    TurnHeadRecord,
    TurnMarkupRecord,
    TurnTaskRecord,
)
from quack.events.values import AnswerSpec, LearnerAnswer, MathValue, Verdict
from quack.llm.gateway import LLMGateway, LLMResult
from quack.prompts.registry import PromptRegistry

SETTINGS = Settings()
LEARNER = uuid4()
SESSION = uuid4()
SKILL = uuid4()
OTHER_SKILL = uuid4()
MISCONCEPTION = uuid4()
TASK = uuid4()


class _Log:
    def __init__(self) -> None:
        self.events: list[StoredEvent] = []

    def add(self, type_: str, payload: BaseModel, causation_seq: int | None = None) -> int:
        seq = len(self.events) + 1
        self.events.append(
            StoredEvent(
                learner_id=LEARNER,
                seq=seq,
                id=seq,
                type=type_,
                schema_version=1,
                actor="learner",
                domain_id=None,
                session_id=SESSION,
                causation_seq=causation_seq,
                correlation_id=None,
                idempotency_key=f"k{seq}",
                payload_hash="h",
                occurred_at=datetime(2026, 11, 3, tzinfo=UTC),
                payload=payload.model_dump(mode="json"),
                source_refs=[],
            )
        )
        return seq


def _committed(action_seq: int, text: str, *, task: bool = False) -> TurnCommitted:
    tasks = (
        [
            TurnTaskRecord(
                element_id="e1",
                task_id=TASK,
                tests=[TestedLevelRecord(skill_id=SKILL, level=3)],
                method_named=True,
                answer=AnswerSpec(type="number", value=MathValue(latex="4", sympy="4")),
            )
        ]
        if task
        else []
    )
    elements: list[ElementRecord] = (
        [
            TaskElementRecord(
                element_id="e1",
                kind="task",
                prompt="Find the limit of a_n",
                canvas=True,
                ask_confidence=False,
            )
        ]
        if task
        else []
    )
    return TurnCommitted(
        action_seq=action_seq,
        text=text,
        blocks=[BodyBlockRecord(block_id="b1", text=text, element_id=None)],
        head=TurnHeadRecord(
            intent="practice",
            target_skill_ids=[SKILL],
            verdict_stance=None,
            branch_type=None,
            approach="attempt_first",
        ),
        markup=TurnMarkupRecord(
            tasks=tasks,
            elements=elements,
            exposures=[ExposureRecord(skill_id=SKILL, kind="example", approach="example_first")]
            if task
            else [],
            targets_misconception_id=None,
            plan_update=PlanUpdateRecord(
                completed_steps=[],
                current_step="s",
                next_steps=[],
                branches=[],
                cancel_request_ids=[],
            ),
            agent_requests=[],
            corrections_acknowledged=[],
            decision_reason="r",
            deadline=None,
        ),
        role="teacher",
        model="m",
        effort="low",
        degraded_mode=None,
        guard_retries=0,
        manifest_id=uuid4(),
    )


def _turn(log: _Log, n: int) -> int:
    action = log.add("message.sent", MessageSent(text=f"question {n}"))
    log.add("turn.committed", _committed(action, f"reply {n}"), causation_seq=action)
    # an event of the turn's own append, written after `turn.committed` (WP2.2)
    log.add("hint.shown", HintShown(task_id=TASK, step=1, source="teacher"), causation_seq=action)
    return action


def test_extraction_window() -> None:
    """`T-X1` (window): the episode plus `episode_context_turns` turns before it; a turn keeps
    the events of its own append; nothing after the episode."""
    log = _Log()
    for n in range(1, 6):
        _turn(log, n)
    from_seq = len(log.events) + 1
    for n in range(6, 8):
        _turn(log, n)
    to_seq = len(log.events)
    _turn(log, 8)  # after the episode

    window = extraction_window(log.events, from_seq, to_seq, SETTINGS)
    assert [e.seq for e in window.episode] == list(range(from_seq, to_seq + 1))
    texts = [e.payload.get("text") for e in window.before if e.type == "message.sent"]
    assert texts == ["question 3", "question 4", "question 5"]
    # turn 2 is outside: its `hint.shown` (written after its commit) stays out too
    assert min(e.seq for e in window.before) == 7
    assert len(window.before) == 9

    two = extraction_window(log.events, from_seq, to_seq, Settings(episode_context_turns=2))
    assert [e.payload.get("text") for e in two.before if e.type == "message.sent"] == [
        "question 4",
        "question 5",
    ]
    none = extraction_window(log.events, from_seq, to_seq, Settings(episode_context_turns=0))
    assert none.before == []
    # zero context turns and no turn before the episode: still nothing before it
    assert extraction_window(log.events, 2, 3, Settings(episode_context_turns=0)).before == []
    # fewer turns than the setting: all of them
    first = extraction_window(log.events, 4, 6, SETTINGS)
    assert [e.seq for e in first.before] == [1, 2, 3]


def _episode() -> tuple[_Log, int]:
    log = _Log()
    _turn(log, 1)
    start = len(log.events) + 1
    action = log.add("message.sent", MessageSent(text="give me a task"))
    log.add("turn.committed", _committed(action, "Try this one", task=True), causation_seq=action)
    answer = log.add(
        "answer.submitted",
        AnswerSubmitted(
            task_id=TASK,
            answer=LearnerAnswer(kind="number", value="5"),
            text="I used the root test",
            source="chat",
        ),
    )
    log.add(
        "verdict.recorded",
        Verdict(
            answer_seq=answer, part="main", outcome="incorrect", method="exact", verification="code"
        ),
    )
    log.add(
        "canvas.line_committed",
        CanvasLineCommitted(
            canvas_id=uuid4(),
            line_id="l1",
            text="sqrt[n]{n!} -> ?",
            kind="text",
            bbox=(0.0, 0.0, 1.0, 1.0),
            stroke_ids=[],
            started_at_ms=0,
            ended_at_ms=1,
            source="pen",
            recognition_confidence=0.9,
            crossed_out=True,
        ),
    )
    log.add(
        "voice.transcribed", VoiceTranscribed(text="hmm the root", started_at_ms=0, ended_at_ms=1)
    )
    log.add("item.flagged_unclear", ItemFlaggedUnclear(turn_seq=2, block_id="b1", text="why n!"))
    return log, start


def test_extractor_input() -> None:
    """Т-§7.6: the events of the window as numbered lines (replies, markup, verdicts, canvas,
    voice, "unclear"); candidates and their known misconceptions with labels; the gap types of
    П-6.4; no ids; `extractor@3` renders with exactly these variables."""
    log, start = _episode()
    window = extraction_window(log.events, start, len(log.events), SETTINGS)
    candidates = [
        CandidateSkill(SKILL, "D'Alembert test"),
        CandidateSkill(OTHER_SKILL, "Root test"),
    ]
    known = [
        KnownMisconception(MISCONCEPTION, SKILL, "uses the root test for factorials"),
        KnownMisconception(uuid4(), uuid4(), "a misconception of a skill that is no candidate"),
    ]
    labels = window_labels(window, candidates, known, SETTINGS)
    variables = extractor_variables(window, candidates, known, labels)
    # only the misconceptions of the candidates get labels
    assert list(labels.labels("misconception").values()) == [MISCONCEPTION]

    assert variables["events_before"].splitlines() == [
        "[1] learner: question 1",
        "[2] teacher: reply 1",
        "[3] hint, step 1 of 3, on K1",
    ]
    s = start
    assert variables["episode"].splitlines() == [
        f"[{s}] learner: give me a task",
        f"[{s + 1}] teacher: Try this one",
        f"[{s + 1}] problem given K1 (tests: S1 level 3): Find the limit of a_n",
        f"[{s + 1}] teacher showed for S1: example",
        f"[{s + 2}] learner's answer to K1: 5",
        f"[{s + 2}] learner's reasoning: I used the root test",
        f"[{s + 3}] check by the checking code of the answer [{s + 2}] to K1: incorrect",
        f"[{s + 4}] learner wrote on the canvas (crossed out): sqrt[n]{{n!}} -> ?",
        f"[{s + 5}] learner said: hmm the root",
        f'[{s + 6}] learner marked as unclear: "why n!"',
    ]
    assert variables["candidate_skills"] == "S1: D'Alembert test\nS2: Root test"
    assert variables["known_misconceptions"] == "M1 (skill S1): uses the root test for factorials"
    assert variables["gap_types"] == GAP_TYPE_TABLE
    for code in ("no_idea", "when_to_apply", "confusion", "execution", "slip", "misconception"):
        assert f"{code} — " in GAP_TYPE_TABLE
    rendered = PromptRegistry().load("extractor", 3).render(variables)
    for object_id in (SKILL, OTHER_SKILL, MISCONCEPTION, TASK, LEARNER, SESSION):
        assert str(object_id) not in rendered

    empty = extractor_variables(extraction_window([], 1, 1, SETTINGS), [], [], labels)
    assert empty["events_before"] == empty["episode"] == empty["candidate_skills"] == NONE_LINE


def test_candidate_skills() -> None:
    """WP15 п.2: session skills first, then the nearest by vector, at most
    `candidate_skills_k`; Modal down — only the session's."""
    session = [uuid4() for _ in range(3)]
    nearest = [session[1], *(uuid4() for _ in range(20))]
    chosen = candidate_skill_ids(session, nearest, SETTINGS)
    assert chosen[:3] == session
    assert len(chosen) == SETTINGS.candidate_skills_k
    assert chosen[3] == nearest[1]
    assert candidate_skill_ids(session, [], SETTINGS) == session


def _element(**kw: Any) -> ExtractedElement:
    base: dict[str, Any] = {
        "kind": "evidence",
        "skill": "S1",
        "new_skill": None,
        "skill_unclear": False,
        "level": 3,
        "outcome": "incorrect",
        "help": "none",
        "hint_step": None,
        "gap_type": "confusion",
        "misconception": None,
        "new_misconception": None,
        "root_cause": None,
        "quote": "root test",
        "events": [5],
    }
    base.update(kw)
    return ExtractedElement.model_validate(base)


@dataclass
class _Gateway:
    answer: ExtractorOutputV3
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate_structured(
        self,
        role: str,
        prompt_version: int,
        response_model: type[BaseModel],
        variables: dict[str, Any],
        learner_id: UUID,
        session_id: UUID | None,
        turn_id: UUID | None,
        idempotency_key: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> LLMResult[Any]:
        self.calls.append(
            {
                "role": role,
                "version": prompt_version,
                "model": response_model,
                "variables": variables,
                "key": idempotency_key,
                "check": kwargs.get("check"),
            }
        )
        return LLMResult(
            value=self.answer, from_cache=False, prompt_hash="h", model="m", usage=None
        )


async def test_call_extractor() -> None:
    """WP15 п.3: `extractor@3`, strict `ExtractorOutputV3`, the key of the observation; an
    unknown label goes back to the model through `check` (Т-§4.5)."""
    log, start = _episode()
    window = extraction_window(log.events, start, len(log.events), SETTINGS)
    candidates = [CandidateSkill(SKILL, "D'Alembert test")]
    known = [KnownMisconception(MISCONCEPTION, SKILL, "uses the root test for factorials")]
    labels = window_labels(window, candidates, known, SETTINGS)
    variables = extractor_variables(window, candidates, known, labels)
    answer = ExtractorOutputV3(elements=[_element()])
    gateway = _Gateway(answer)
    out = await call_extractor(
        cast(LLMGateway, gateway),
        SETTINGS,
        learner_id=LEARNER,
        session_id=SESSION,
        episode_seq=40,
        trigger_seq=40,
        variables=variables,
        labels=labels,
    )
    assert out == answer
    (call,) = gateway.calls
    assert call["role"] == "extractor" and call["version"] == 3
    assert call["model"] is ExtractorOutputV3
    assert call["key"] == extraction_key(40, "extractor@3", 40) == "obs:40:extractor@3:40"
    assert call["variables"] == variables
    check = call["check"]
    assert check(answer) is None
    assert label_errors(ExtractorOutputV3(elements=[_element(skill="S9")]), labels) == (
        "unknown labels: S9; use only the given labels"
    )
    wrong = ExtractorOutputV3(
        elements=[_element(misconception="M4", root_cause={"skill": "S7", "confidence": "low"})]
    )
    assert check(wrong) == "unknown labels: M4, S7; use only the given labels"
    assert check(ExtractorOutputV3(elements=[_element(skill=None, skill_unclear=True)])) is None
