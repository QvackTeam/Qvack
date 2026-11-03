"""WP22.3: the photo pipeline of a canvas (ТЗ Ф4 WP22.3; Т-§22.6; D-C-134)."""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from quack.canvas.boards import open_canvas
from quack.canvas.photo_pipeline import align_lines, normalized_levenshtein, run_photo_pipeline
from quack.compute_client.contracts import AlignResponse
from quack.config import Settings
from quack.db import Db
from quack.db.postgres import SessionFactory
from quack.events.event_types import PhotoUploaded
from quack.events.log import NewEvent, append_events
from quack.jobs.runner import JOB_HANDLERS
from quack.llm.provider import ImageInput
from tests.db.fixtures import create_learner
from tests.support.compute import ComputeScenario, scripted_compute
from tests.support.llm import ScriptedLLMProvider
from tests.support.resources import build_app_resources
from tests.support.storage import InMemoryObjectStore

ALIGN = "/v1/image/align"
ALIGNED = b"RIFF\x00\x00\x00\x00WEBPVP8 aligned"


def _line(text: str, top: float, *, crossed: bool = False, kind: str = "latex") -> dict[str, Any]:
    return {
        "kind": kind,
        "text": text,
        "sympy": None,
        "bbox": {"left": 0.1, "top": top, "right": 0.9, "bottom": round(top + 0.05, 2)},
        "confidence": 0.8,
        "crossed_out": crossed,
    }


def test_normalized_levenshtein() -> None:
    assert normalized_levenshtein("", "") == 0.0
    assert normalized_levenshtein("2x+4=10", "2x+4=10") == 0.0
    assert normalized_levenshtein("2x+4=10", "2x+4=12") == 1 / 7
    assert normalized_levenshtein("abc", "") == 1.0


def test_alignment_keeps_order_and_finds_inserted_lines() -> None:
    """Т-§22.6 п.3: a line written between two old ones is new; a slightly changed line matches
    its old self; a line far from every old one matches nothing."""
    previous = ["2x+4=10", "2x=6", "x=3"]
    current = ["2x+4=10", "2x=10-4", "2x=6", "x=3.0", "answer: three"]
    assert align_lines(previous, current, 0.2) == {0: 0, 2: 1}
    assert align_lines(previous, current, 0.5) == {0: 0, 2: 1, 3: 2}
    assert align_lines([], current, 0.2) == {}


async def _photo(db: Db, storage: InMemoryObjectStore, learner: UUID, canvas_id: UUID) -> UUID:
    photo_id = uuid4()
    key = f"learners/{learner}/photos/{photo_id}/original.webp"
    await storage.put(key, b"RIFF\x00\x00\x00\x00WEBPVP8 photo", "image/webp")
    uploaded = NewEvent(
        type="photo.uploaded",
        payload=PhotoUploaded(canvas_id=canvas_id, photo_id=photo_id, object_key=key),
        actor="learner",
        idempotency_key=f"photo.uploaded:{photo_id}",
    )
    await append_events(db, learner, [uploaded])
    return photo_id


async def _log(db: Db, learner: UUID) -> list[tuple[str, str, Any]]:
    rows = await db.fetch_all(
        "SELECT type, payload FROM core.events WHERE learner_id = %(learner_id)s "
        "AND type IN ('canvas.line_committed', 'canvas.line_erased') ORDER BY seq",
        {"learner_id": learner},
    )
    return [(r["type"], r["payload"]["line_id"], r["payload"]["text"]) for r in rows]


async def test_photos_of_one_sheet_write_only_new_lines(
    pg_db: Db, pg_engine: AsyncEngine, db: SessionFactory, settings: Settings
) -> None:
    """WP22.3 п.1–4: the aligned photo is read in one call; the second photo of the sheet writes
    its new and changed lines and erases the newly crossed-out one; a repeated job writes
    nothing; a photo where little of the last one matches opens a new sheet."""
    learner = await create_learner(pg_db)
    session_id = uuid4()
    started = NewEvent(
        type="session.started",
        payload={"session_id": str(session_id), "domain_id": str(uuid4()), "intent": "learn"},
        actor="learner",
        idempotency_key=str(uuid4()),
    )
    await append_events(pg_db, learner, [started])
    canvas = await open_canvas(pg_db, learner_id=learner, session_id=session_id)
    storage = InMemoryObjectStore()
    scenario = ComputeScenario()
    answer = AlignResponse(aligned=True, image_webp_b64=base64.b64encode(ALIGNED).decode())
    scenario.push_for(ALIGN, *[answer] * 5)
    sheet: dict[str, list[dict[str, Any]]] = {"lines": []}
    provider = ScriptedLLMProvider()
    provider.respond("RecognizerSheetOutput", lambda _request: dict(sheet))
    resources = build_app_resources(
        settings, pg_engine, None, None, db=pg_db, session_factory=db, provider=provider,
        compute=scripted_compute(scenario), storage=storage,
    )  # fmt: skip

    async def run(lines: list[dict[str, Any]]) -> Any:
        photo_id = await _photo(pg_db, storage, learner, canvas.canvas_id)
        sheet["lines"] = lines
        result = await run_photo_pipeline(
            resources.db, resources.llm, resources.compute, storage, settings,
            learner_id=learner, photo_id=photo_id,
        )  # fmt: skip
        return photo_id, result

    first, result = await run([_line("2x+4=10", 0.1), _line("2x=6", 0.2)])
    assert result.committed == [f"{first}:{first}:0", f"{first}:{first}:1"]
    assert not result.new_sheet
    (call,) = provider.calls
    assert call.schema_name == "RecognizerSheetOutput"
    assert call.images == (ImageInput("image/webp", ALIGNED),)

    second, result = await run(
        [
            _line("2x+4=10", 0.1),
            _line("2x=10-4", 0.15),
            _line("2x=6", 0.2, crossed=True),
            _line("", 0.3, kind="drawing"),
            _line("x+y=133", 0.4),
        ]
    )
    assert result.drawings == 1 and not result.new_sheet
    assert result.committed == [f"{first}:{second}:1", f"{first}:{second}:3"]
    assert result.erased == [f"{first}:{first}:1"]
    log = await _log(pg_db, learner)
    assert log[2:] == [
        ("canvas.line_committed", f"{first}:{second}:1", "2x=10-4"),
        ("canvas.line_erased", f"{first}:{first}:1", "2x=6"),
        ("canvas.line_committed", f"{first}:{second}:3", "x+y=133"),
    ]
    rows = await pg_db.fetch_all(
        "SELECT payload FROM core.events WHERE learner_id = %(learner_id)s "
        "AND type = 'canvas.line_committed' ORDER BY seq DESC LIMIT 1",
        {"learner_id": learner},
    )
    payload = rows[0]["payload"]
    assert payload["source"] == "photo" and payload["photo_id"] == str(second)
    assert payload["bbox"] == [0.1, 0.4, 0.9, 0.45] and payload["stroke_ids"] == []

    # A changed line keeps its id (`x+y=133` → `x+y=134`).
    third, result = await run(
        [
            _line("2x+4=10", 0.1),
            _line("2x=10-4", 0.15),
            _line("2x=6", 0.2, crossed=True),
            _line("x+y=134", 0.4),
        ]
    )
    assert result.committed == [f"{first}:{second}:3"] and result.erased == []

    # The repeated job of the third photo: the same reading, nothing new.
    before = await _log(pg_db, learner)
    again = await run_photo_pipeline(
        resources.db, resources.llm, resources.compute, storage, settings,
        learner_id=learner, photo_id=third,
    )  # fmt: skip
    assert again is not None and again.committed == [] and again.erased == []
    assert await _log(pg_db, learner) == before

    fourth, result = await run([_line("\\int_0^1 x\\,dx", 0.1), _line("2x=6", 0.2)])
    assert result.new_sheet
    assert result.committed == [f"{fourth}:{fourth}:0", f"{fourth}:{fourth}:1"]


def test_pipeline_job_is_registered() -> None:
    """`photo.pipeline` (P1, stream A's dispatcher row) has its handler in `quack.canvas`."""
    assert JOB_HANDLERS["photo.pipeline"].__module__ == "quack.canvas.photo_pipeline"
