"""The extractor by episodes, WP15 п.1–3 (ТЗ Ф4; Т-§7.5, Т-§7.6, Т-§4.5): the window, the
input of `extractor@3` and the call of the role. D-B-162.

- **Window** (п.1, Т-§7.5): the episode `[from_seq, to_seq]` plus `episode_context_turns` turns
  before it, for understanding only; only the episode is interpreted.
- **Input** (п.2, Т-§7.6): the events of the window as numbered text lines — learner and teacher
  replies, markup, verdicts, canvas lines, voice, "unclear"; candidate skills — the skills of
  the topics active in the session plus the nearest by the episode vector (with Modal down —
  only the session's), at most `candidate_skills_k`; known misconceptions of the candidates;
  the table of gap types (П-6.4). Everything with short labels.
- **Call** (п.3): `extractor@3` through the gateway, strict schema `ExtractorOutputV3`; an
  unknown label goes back to the model once (the gateway's repair path, Т-§4.5).

- **Re-extraction** (п.6): `episode.reassigned` and `skill.split` restrict the candidates to
  the skills of the named topic or of the split (Т-§2.8, Т-§4.11); the new observation has its
  own `trigger_seq` in the key.

The check of the elements (п.4) and the write of `observation.extracted` with coverage (п.5)
stand on the seams of stream A.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from quack.agents.schemas import ExtractorOutputV3
from quack.config import Settings
from quack.events.event_types import (
    AnswerSubmitted,
    CanvasLineCommitted,
    CanvasLineErased,
    CheckSkipped,
    ElementResponded,
    HandwritingCorrected,
    HintRequested,
    HintShown,
    ItemFlaggedUnclear,
    MessageSent,
    SolutionRequested,
    TaskClosed,
    TurnCommitted,
    TypoDeclared,
    VoiceTranscribed,
)
from quack.events.log import StoredEvent
from quack.events.values import CheckFailed, Verdict
from quack.llm.gateway import LLMGateway
from quack.llm.labels import LabelMap

EXTRACTOR_ROLE = "extractor"
NONE_LINE = "(none)"

# П-6.4, in the words of the doctrine (`extractor@3`, «Caution in diagnosis» п.2).
GAP_TYPE_TABLE = (
    "no_idea — only naming the idea itself helps; their own prediction is empty or random.\n"
    "when_to_apply — solves the problem when the method is named, but not otherwise; a hint "
    "about the kind of technique helps.\n"
    "confusion — used a neighboring idea or picked an option built on a neighboring rule; it "
    "repeats on similar problems.\n"
    "execution — the method is right, the working has a mistake; showing the step helps.\n"
    "slip — a one-off; they did the same operation correctly before, or noticed it themselves "
    'after a short "check this".\n'
    "misconception — they are wrong confidently and on different problems, or picked an option "
    "built from this distortion.\n"
    "none — the outcome is correct."
)

_OUTCOME = {"correct": "correct", "incorrect": "incorrect", "partial": "partly correct"}


@dataclass(frozen=True)
class EpisodeWindow:
    """`before` — the context turns (record nothing from them); `episode` — the episode."""

    before: list[StoredEvent]
    episode: list[StoredEvent]


@dataclass(frozen=True)
class CandidateSkill:
    skill_id: UUID
    name: str


@dataclass(frozen=True)
class KnownMisconception:
    misconception_id: UUID
    skill_id: UUID
    statement: str


def extraction_window(
    session_events: Sequence[StoredEvent], from_seq: int, to_seq: int, settings: Settings
) -> EpisodeWindow:
    """The episode and the `episode_context_turns` turns before it (Т-§7.5). A turn ends with
    its `turn.committed`; the events of its own append (`causation_seq` = its `action_seq`,
    WP2.2) stay with it."""
    ordered = sorted(session_events, key=lambda e: e.seq)
    episode = [e for e in ordered if from_seq <= e.seq <= to_seq]
    earlier = [e for e in ordered if e.seq < from_seq]
    commits = [e for e in earlier if e.type == "turn.committed"]
    keep = settings.episode_context_turns
    if keep <= 0:
        return EpisodeWindow(before=[], episode=episode)
    if len(commits) <= keep:
        return EpisodeWindow(before=earlier, episode=episode)
    boundary = commits[-keep - 1]
    outside = {int(e.payload["action_seq"]) for e in commits[: len(commits) - keep]}
    before = [
        e
        for e in earlier
        if e.seq > boundary.seq and (e.causation_seq is None or e.causation_seq not in outside)
    ]
    return EpisodeWindow(before=before, episode=episode)


def candidate_skill_ids(
    session_skill_ids: Sequence[UUID],
    nearest_skill_ids: Sequence[UUID],
    settings: Settings,
    *,
    restrict: Sequence[UUID] | None = None,
) -> list[UUID]:
    """Skills of the session topics first, then the nearest by vector; `candidate_skills_k`.
    A re-extraction (п.6, Т-§2.8, Т-§4.11) gives `restrict`: the skills of the topic named by
    `episode.reassigned`, or the split skill and its parts of `skill.split` — only they."""
    if restrict is not None:
        return list(dict.fromkeys(restrict))[: settings.candidate_skills_k]
    unique = list(dict.fromkeys([*session_skill_ids, *nearest_skill_ids]))
    return unique[: settings.candidate_skills_k]


def _task(labels: LabelMap, task_id: UUID) -> str:
    return labels.label("task", task_id) or "a task"


def _turn_lines(seq: int, turn: TurnCommitted, labels: LabelMap) -> list[str]:
    lines = [f"[{seq}] teacher: {turn.text}"]
    prompts = {
        element.element_id: prompt
        for element in turn.markup.elements
        if isinstance(prompt := getattr(element, "prompt", None), str)
    }
    for task in turn.markup.tasks:
        tests = ", ".join(
            f"{labels.label('skill', t.skill_id) or 'a new skill'} level {t.level}"
            if t.skill_id is not None
            else f"a new skill level {t.level}"
            for t in task.tests
        )
        line = f"[{seq}] problem given {_task(labels, task.task_id)} (tests: {tests})"
        statement = prompts.get(task.element_id)
        lines.append(f"{line}: {statement}" if statement else line)
    for exposure in turn.markup.exposures:
        skill = labels.label("skill", exposure.skill_id) or "a skill"
        lines.append(f"[{seq}] teacher showed for {skill}: {exposure.kind.replace('_', ' ')}")
    return lines


def event_lines(event: StoredEvent, labels: LabelMap, answers: dict[int, UUID]) -> list[str]:
    """One event as numbered lines (`[seq] who: text`); events without text give none."""
    data, head = event.payload, f"[{event.seq}]"
    match event.type:
        case "message.sent":
            text = MessageSent.model_validate(data).text
            return [f"{head} learner: {text}"] if text else []
        case "answer.submitted":
            answer = AnswerSubmitted.model_validate(data)
            part = f" part {answer.part}" if answer.part else ""
            lines = [
                f"{head} learner's answer to {_task(labels, answer.task_id)}{part}: "
                f"{answer.answer.latex or answer.answer.value}"
            ]
            if answer.text:
                lines.append(f"{head} learner's reasoning: {answer.text}")
            return lines
        case "verdict.recorded":
            verdict = Verdict.model_validate(data)
            task_id = answers.get(verdict.answer_seq)
            target = f" to {_task(labels, task_id)}" if task_id else ""
            by = "the checking code" if verdict.verification == "code" else "a model"
            words = _OUTCOME.get(verdict.outcome, verdict.outcome)
            return [f"{head} check by {by} of the answer [{verdict.answer_seq}]{target}: {words}"]
        case "check.failed":
            failed = CheckFailed.model_validate(data)
            return [f"{head} the checking code could not check the answer [{failed.answer_seq}]"]
        case "typo.declared":
            typo = TypoDeclared.model_validate(data)
            return [f"{head} learner says the answer [{typo.answer_seq}] was a typo"]
        case "element.responded":
            response = ElementResponded.model_validate(data)
            lines = [
                f"{head} learner's response to element {response.element_id}: {response.response}"
            ]
            if response.text:
                lines.append(f"{head} learner's reasoning: {response.text}")
            return lines
        case "hint.requested":
            task_id = HintRequested.model_validate(data).task_id
            return [f"{head} learner asked for a hint on {_task(labels, task_id)}"]
        case "solution.requested":
            task_id = SolutionRequested.model_validate(data).task_id
            return [f"{head} learner asked for the solution of {_task(labels, task_id)}"]
        case "check.skipped":
            task_id = CheckSkipped.model_validate(data).task_id
            return [f"{head} learner skipped the check of {_task(labels, task_id)}"]
        case "item.flagged_unclear":
            flag = ItemFlaggedUnclear.model_validate(data)
            return [f'{head} learner marked as unclear: "{flag.text}"']
        case "canvas.line_committed":
            line = CanvasLineCommitted.model_validate(data)
            crossed = " (crossed out)" if line.crossed_out else ""
            return [f"{head} learner wrote on the canvas{crossed}: {line.text}"]
        case "canvas.line_erased":
            erased = CanvasLineErased.model_validate(data)
            return [f"{head} learner erased the canvas line: {erased.text}"]
        case "handwriting.corrected":
            fixed = HandwritingCorrected.model_validate(data)
            return [f"{head} learner corrected the reading of a canvas line: {fixed.text}"]
        case "voice.transcribed":
            return [f"{head} learner said: {VoiceTranscribed.model_validate(data).text}"]
        case "turn.committed":
            return _turn_lines(event.seq, TurnCommitted.model_validate(data), labels)
        case "hint.shown":
            hint = HintShown.model_validate(data)
            return [f"{head} hint, step {hint.step} of 3, on {_task(labels, hint.task_id)}"]
        case "task.closed":
            closed = TaskClosed.model_validate(data)
            how = closed.how.replace("_", " ")
            return [f"{head} {_task(labels, closed.task_id)} closed: {how}"]
        case _:
            return []


def render_events(events: Sequence[StoredEvent], labels: LabelMap, answers: dict[int, UUID]) -> str:
    lines = [line for event in events for line in event_lines(event, labels, answers)]
    return "\n".join(lines) or NONE_LINE


def window_labels(
    window: EpisodeWindow,
    candidates: Sequence[CandidateSkill],
    misconceptions: Sequence[KnownMisconception],
    settings: Settings,
) -> LabelMap:
    """Labels of the call: candidates in their order, the tasks of the window by appearance,
    the known misconceptions of the candidates."""
    tasks: list[UUID] = []
    for event in [*window.before, *window.episode]:
        if event.type == "turn.committed":
            tasks.extend(
                t.task_id for t in TurnCommitted.model_validate(event.payload).markup.tasks
            )
        elif "task_id" in event.payload:
            tasks.append(UUID(str(event.payload["task_id"])))
    skills = [c.skill_id for c in candidates]
    known = [m.misconception_id for m in misconceptions if m.skill_id in set(skills)]
    return LabelMap.build(settings, skills=skills, tasks=tasks, misconceptions=known)


def extractor_variables(
    window: EpisodeWindow,
    candidates: Sequence[CandidateSkill],
    misconceptions: Sequence[KnownMisconception],
    labels: LabelMap,
) -> dict[str, str]:
    """The five input blocks of `extractor@3`."""
    answers = {
        e.seq: AnswerSubmitted.model_validate(e.payload).task_id
        for e in [*window.before, *window.episode]
        if e.type == "answer.submitted"
    }
    skill_lines = [
        f"{label}: {c.name}" for c in candidates if (label := labels.label("skill", c.skill_id))
    ]
    misconception_lines = [
        f"{label} (skill {skill}): {m.statement}"
        for m in misconceptions
        if (label := labels.label("misconception", m.misconception_id))
        and (skill := labels.label("skill", m.skill_id))
    ]
    return {
        "events_before": render_events(window.before, labels, answers),
        "episode": render_events(window.episode, labels, answers),
        "candidate_skills": "\n".join(skill_lines) or NONE_LINE,
        "known_misconceptions": "\n".join(misconception_lines) or NONE_LINE,
        "gap_types": GAP_TYPE_TABLE,
    }


def label_errors(output: ExtractorOutputV3, labels: LabelMap) -> str | None:
    """Т-§4.5: a label the call did not give goes back to the model once."""
    skills = labels.labels("skill")
    known = labels.labels("misconception")
    unknown: list[str] = []
    for element in output.elements:
        if element.skill is not None and element.skill not in skills:
            unknown.append(element.skill)
        if element.misconception is not None and element.misconception not in known:
            unknown.append(element.misconception)
        if element.root_cause is not None and element.root_cause.skill not in skills:
            unknown.append(element.root_cause.skill)
    if not unknown:
        return None
    return "unknown labels: " + ", ".join(dict.fromkeys(unknown)) + "; use only the given labels"


def extraction_key(episode_seq: int, prompt: str, trigger_seq: int) -> str:
    """WP15 п.5: `obs:{episode_seq}:{extractor@3}:{trigger_seq}` — the call carries the same key."""
    return f"obs:{episode_seq}:{prompt}:{trigger_seq}"


async def call_extractor(
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    session_id: UUID | None,
    episode_seq: int,
    trigger_seq: int,
    variables: dict[str, str],
    labels: LabelMap,
) -> ExtractorOutputV3:
    """One call of `extractor@3` per episode and trigger; no second opinion (Т-§7.7)."""
    prompt = settings.llm_roles[EXTRACTOR_ROLE].prompt
    if prompt is None:
        raise ValueError("role 'extractor' has no prompt")
    result = await gateway.generate_structured(
        EXTRACTOR_ROLE,
        int(prompt.rsplit("@", 1)[1]),
        ExtractorOutputV3,
        variables,
        learner_id,
        session_id,
        None,
        extraction_key(episode_seq, prompt, trigger_seq),
        check=lambda output: label_errors(output, labels),
    )
    return result.value
