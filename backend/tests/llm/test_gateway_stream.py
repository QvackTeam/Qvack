"""ТЗ Ф4 WP10.2, WP10.3 inside the gateway (WP5 of Phase 3 stays, WP10 «adds what is missing»):
a streamed step of the teacher turn goes through the same admission, circuit breaker, pressure
flag and ledger as `generate_structured` (D-B-152). The turn graph takes the gateway stream as
its provider (seam S13 underneath)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from quack.config import Settings
from quack.db.postgres import SessionFactory
from quack.db.redis import llm_pressure_key
from quack.llm.errors import LLMRateLimitedError, LLMUnavailableError, ProviderUnavailableError
from quack.llm.gateway import LLMGateway
from quack.llm.streaming import StreamCompleted, StreamEvent, StreamingLLMProvider, TextDelta
from quack.llm.tool_loop import stream_step
from quack.prompts.build_manifest import write_manifest
from quack.prompts.registry import PromptRegistry
from tests.support.llm import ScriptedFailure, ScriptedLLMProvider

WONDER, SPARK = "m-wonder", "m-spark"
TOOL = {"type": "function", "name": "skill_history", "parameters": {}, "strict": True}


class StreamAnswer(BaseModel):
    label: str


@pytest.fixture
def prompts(tmp_path: Path) -> PromptRegistry:
    folder = tmp_path / "teacher"
    folder.mkdir()
    (folder / "v2.md").write_text("teacher: {{ text }}", encoding="utf-8")
    write_manifest(tmp_path)
    return PromptRegistry(tmp_path)


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test",
        "llm_default_model": SPARK,
        "llm_role_models": {"teacher": WONDER, "teacher_fallback": SPARK},
        "llm_retry_base_ms": 1,
        "llm_retry_attempts": 1,
    }
    return Settings(**(base | over))


def _provider() -> ScriptedLLMProvider:
    provider = ScriptedLLMProvider()
    provider.respond("StreamAnswer", lambda _r: {"label": "ok"})
    return provider


def _gateway(
    db: SessionFactory,
    provider: Any,
    prompts: PromptRegistry,
    redis: Redis | None = None,
    **over: Any,
) -> LLMGateway:
    return LLMGateway(db, provider, _settings(**over), prompts, redis=redis)


def _stream(gw: LLMGateway, learner_id: UUID, turn_id: UUID) -> tuple[Any, StreamingLLMProvider]:
    request, prompt = gw.stream_request(
        "teacher",
        2,
        StreamAnswer,
        {"text": "context"},
        reasoning_effort="high",
        tools=(TOOL,),
    )
    return request, gw.streaming(
        "teacher", prompt, learner_id=learner_id, session_id=None, turn_id=turn_id
    )


async def _collect(events: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    return [event async for event in events]


async def _ledger(db: SessionFactory, learner_id: UUID) -> list[Any]:
    async with db() as session:
        rows = await session.execute(
            text(
                "SELECT role, model, prompt_version, turn_id, status, error_code, input_tokens, "
                "output_tokens, reasoning_effort FROM ops.llm_ledger WHERE learner_id = :l "
                "ORDER BY created_at, id"
            ),
            {"l": learner_id},
        )
        return list(rows.all())


async def test_stream_step_goes_through_the_gateway(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    provider = _provider()
    gw = _gateway(db, provider, prompts)
    learner_id, turn_id = uuid4(), uuid4()
    request, stream = _stream(gw, learner_id, turn_id)

    events = await _collect(stream.stream_structured(request))

    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == '{"label":"ok"}'
    assert isinstance(events[-1], StreamCompleted)
    [sent] = provider.stream_calls
    assert sent.base.model == WONDER and sent.base.schema_name == "StreamAnswer"
    assert sent.base.prompt == "teacher: context"
    assert sent.base.reasoning_effort == "high" and sent.base.prompt_cache_key == "teacher@2"
    assert sent.base.json_schema["additionalProperties"] is False
    assert sent.tools == (TOOL,)
    [row] = await _ledger(db, learner_id)
    assert (row.role, row.model, row.prompt_version, row.turn_id) == ("teacher", WONDER, 2, turn_id)
    assert (row.status, row.error_code, row.reasoning_effort) == ("ok", None, "high")
    assert row.input_tokens > 0 and row.output_tokens > 0


async def test_unavailable_before_the_first_event_is_retried(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    provider = _provider()
    provider.fail(ScriptedFailure("unavailable", schema_name="StreamAnswer", times=1))
    gw = _gateway(db, provider, prompts)
    learner_id = uuid4()
    request, stream = _stream(gw, learner_id, uuid4())

    events = await _collect(stream.stream_structured(request))

    assert isinstance(events[-1], StreamCompleted)
    assert [(r.status, r.error_code) for r in await _ledger(db, learner_id)] == [
        ("error", "unavailable"),
        ("ok", None),
    ]


async def test_unavailable_after_retries_is_an_error(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    provider = _provider()
    provider.fail(ScriptedFailure("unavailable", schema_name="StreamAnswer", times=5))
    gw = _gateway(db, provider, prompts)
    request, stream = _stream(gw, uuid4(), uuid4())

    with pytest.raises(LLMUnavailableError):
        await _collect(stream.stream_structured(request))
    assert len(provider.stream_calls) == 2  # one retry (`llm_retry_attempts`)


async def test_rate_limited_turn_is_not_retried_and_sets_pressure(
    db: SessionFactory, prompts: PromptRegistry, redis: Redis
) -> None:
    provider = _provider()
    provider.fail(ScriptedFailure("rate_limited", schema_name="StreamAnswer", retry_after="7"))
    gw = _gateway(db, provider, prompts, redis)
    learner_id = uuid4()
    request, stream = _stream(gw, learner_id, uuid4())

    with pytest.raises(LLMRateLimitedError):
        await _collect(stream.stream_structured(request))

    assert len(provider.stream_calls) == 1
    assert await redis.exists(llm_pressure_key(WONDER))
    assert [(r.status, r.error_code) for r in await _ledger(db, learner_id)] == [
        ("error", "rate_limited")
    ]


async def test_bad_request_is_an_error(db: SessionFactory, prompts: PromptRegistry) -> None:
    provider = _provider()
    provider.fail(ScriptedFailure("bad_request", schema_name="StreamAnswer"))
    gw = _gateway(db, provider, prompts)
    request, stream = _stream(gw, uuid4(), uuid4())

    with pytest.raises(LLMUnavailableError) as raised:
        await _collect(stream.stream_structured(request))
    assert raised.value.reason == "bad_request" and len(provider.stream_calls) == 1


async def test_cut_step_is_passed_on_and_ledgered(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    """The graph retries a cut step with the doubled limit (Т-§11.1); the gateway only
    passes it on and writes `incomplete`."""
    provider = _provider()
    provider.fail(ScriptedFailure("incomplete", schema_name="StreamAnswer"))
    gw = _gateway(db, provider, prompts)
    learner_id = uuid4()
    request, stream = _stream(gw, learner_id, uuid4())

    events = await _collect(stream.stream_structured(request))

    last = events[-1]
    assert isinstance(last, StreamCompleted) and last.status == "incomplete"
    assert [(r.status, r.error_code) for r in await _ledger(db, learner_id)] == [
        ("incomplete", "incomplete")
    ]


async def test_open_circuit_short_circuits(db: SessionFactory, prompts: PromptRegistry) -> None:
    provider = _provider()
    provider.fail(ScriptedFailure("unavailable", schema_name="StreamAnswer", times=10))
    gw = _gateway(db, provider, prompts, circuit_failures=2, llm_retry_attempts=1)
    request, stream = _stream(gw, uuid4(), uuid4())
    with pytest.raises(LLMUnavailableError):
        await _collect(stream.stream_structured(request))  # two failures open the breaker
    calls = len(provider.stream_calls)

    with pytest.raises(LLMUnavailableError) as raised:
        await _collect(stream.stream_structured(request))

    assert raised.value.reason == "circuit_open" and len(provider.stream_calls) == calls


async def test_consumer_stop_releases_the_model_slot(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    """The graph stops a stream on a rejected head or a spoiler: the slot is free at once."""
    provider = _provider()
    gw = _gateway(db, provider, prompts, llm_concurrency={"api": {WONDER: 1}})
    request, stream = _stream(gw, uuid4(), uuid4())

    events = stream.stream_structured(request)
    async for event in events:
        if isinstance(event, TextDelta):
            break
    await events.aclose()  # type: ignore[attr-defined]

    second = await asyncio.wait_for(_collect(stream.stream_structured(request)), 1)
    assert isinstance(second[-1], StreamCompleted)


async def test_teacher_waits_for_a_slot_no_longer_than_admission_wait(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    provider = _provider()
    gate = provider.hold("StreamAnswer")
    gw = _gateway(
        db, provider, prompts, llm_concurrency={"api": {WONDER: 1}}, teacher_admission_wait_ms=50
    )
    request, stream = _stream(gw, uuid4(), uuid4())
    first = asyncio.create_task(_collect(stream.stream_structured(request)))
    await gate.arrived.wait()

    with pytest.raises(LLMRateLimitedError):
        await _collect(stream.stream_structured(request))

    gate.release.set()
    assert isinstance((await first)[-1], StreamCompleted)


class _BreaksMidStream:
    """Gives one text delta, then the connection drops."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured(self, request: Any) -> Any:  # pragma: no cover - unused
        raise AssertionError("not called")

    async def stream_structured(self, request: Any) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        yield TextDelta('{"label":')
        raise ProviderUnavailableError("connection dropped")


async def test_failure_after_the_first_event_is_not_retried(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    """The learner may have seen the first text: the turn fails, no second stream."""
    provider = _BreaksMidStream()
    gw = _gateway(db, provider, prompts, llm_retry_attempts=3)
    request, stream = _stream(gw, uuid4(), uuid4())

    with pytest.raises(LLMUnavailableError):
        await _collect(stream.stream_structured(request))
    assert provider.calls == 1


async def test_graph_step_stopped_by_the_consumer_frees_the_slot(
    db: SessionFactory, prompts: PromptRegistry
) -> None:
    """`stream_step` closes the stream when its text callback raises (a rejected head)."""
    provider = _provider()
    gw = _gateway(db, provider, prompts, llm_concurrency={"api": {WONDER: 1}})
    request, stream = _stream(gw, uuid4(), uuid4())

    async def reject(_text: str) -> None:
        raise RuntimeError("head rejected")

    with pytest.raises(RuntimeError):
        await stream_step(stream, request, reject)
    gw.settings.teacher_admission_wait_ms = 50  # the slot must be free now, not after GC
    second = await _collect(stream.stream_structured(request))
    assert isinstance(second[-1], StreamCompleted)
