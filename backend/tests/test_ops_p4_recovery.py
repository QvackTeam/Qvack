"""Recovery commands of WP9.6 (Д-§8.3, Д-§8.7): `orphan-objects` (T-OPS4), `resume`,
`replay-deletions` and `rebuild --concurrency` (D-C-211)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from quack import cli
from quack.config import Settings
from quack.db import Db
from quack.ops.orphan_objects import orphan_objects
from quack.storage.keys import (
    canvas_chunk_key,
    material_original_key,
    photo_original_key,
)
from tests.db.fixtures import create_learner
from tests.support.storage import InMemoryObjectStore

LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


class _Shared:
    """The test resources outlive the command: `close` does nothing."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)

    async def close(self) -> None: ...


async def _put(store: InMemoryObjectStore, key: str) -> None:
    await store.put(key, b"x", "application/octet-stream")


async def test_orphan_objects_lists_what_postgres_does_not_know(pg_db: Db) -> None:
    """T-OPS4: an object newer than the mark without a reference is listed; with a reference,
    not; an older one is not looked at."""
    learner = await create_learner(pg_db)
    store = InMemoryObjectStore()
    material, photo_kept, photo_lost = uuid4(), uuid4(), uuid4()
    session, canvas_kept, canvas_lost = uuid4(), uuid4(), uuid4()

    kept_material = material_original_key(learner, material, "pdf")
    await pg_db.execute(
        "INSERT INTO content.materials (material_id, learner_id, object_key, mime, status) "
        "VALUES (%(m)s, %(l)s, %(k)s, 'application/pdf', 'ready')",
        {"m": material, "l": learner, "k": kept_material},
    )
    kept_photo = photo_original_key(learner, photo_kept)
    await pg_db.execute(
        "INSERT INTO core.events (learner_id, seq, type, schema_version, actor, "
        "idempotency_key, payload_hash, occurred_at, payload) "
        "VALUES (%(l)s, 1, 'photo.uploaded', 1, 'learner', 'k1', 'h', now(), "
        "jsonb_build_object('object_key', %(k)s::text))",
        {"l": learner, "k": kept_photo},
    )
    await pg_db.execute(
        "INSERT INTO content.canvas_boards (canvas_id, learner_id, session_id) "
        "VALUES (%(c)s, %(l)s, %(s)s)",
        {"c": canvas_kept, "l": learner, "s": session},
    )
    kept_chunk = canvas_chunk_key(learner, session, canvas_kept, 0)
    lost_photo = photo_original_key(learner, photo_lost)
    lost_chunk = canvas_chunk_key(learner, session, canvas_lost, 0)
    for key in (kept_material, kept_photo, kept_chunk, lost_photo, lost_chunk):
        await _put(store, key)
    old_key = photo_original_key(learner, uuid4())
    await _put(store, old_key)
    mark = datetime.now(UTC) - timedelta(minutes=1)
    data, content_type, _ = store.objects[old_key]
    store.objects[old_key] = (data, content_type, mark - timedelta(days=1))

    report = await orphan_objects(pg_db, store, mark, dry_run=True)

    assert report.orphans == sorted([lost_photo, lost_chunk])
    assert report.checked == 5
    assert report.deleted == 0
    assert set(store.objects) == {
        kept_material,
        kept_photo,
        kept_chunk,
        lost_photo,
        lost_chunk,
        old_key,
    }

    report = await orphan_objects(pg_db, store, mark)

    assert report.deleted == 2
    assert set(store.objects) == {kept_material, kept_photo, kept_chunk, old_key}


async def test_orphan_objects_keeps_a_key_named_in_an_artifact_version(pg_db: Db) -> None:
    learner = await create_learner(pg_db)
    store = InMemoryObjectStore()
    key = photo_original_key(learner, uuid4())
    await _put(store, key)
    artifact = uuid4()
    await pg_db.execute(
        "INSERT INTO content.artifacts (artifact_id, learner_id, kind) "
        "VALUES (%(a)s, %(l)s, 'notes')",
        {"a": artifact, "l": learner},
    )
    await pg_db.execute(
        "INSERT INTO content.artifact_versions (artifact_id, version, learner_id, content, "
        "created_by) VALUES (%(a)s, 1, %(l)s, jsonb_build_object('image', %(k)s::text), 'learner')",
        {"a": artifact, "l": learner, "k": key},
    )

    report = await orphan_objects(pg_db, store, LONG_AGO)

    assert report.orphans == []
    assert key in store.objects


async def test_another_learners_record_does_not_hold_an_object(pg_db: Db) -> None:
    """The reference is looked up for the learner of the key only (isolation, T-DB4)."""
    owner, other = await create_learner(pg_db), await create_learner(pg_db)
    store = InMemoryObjectStore()
    key = material_original_key(owner, uuid4(), "pdf")
    await _put(store, key)
    await pg_db.execute(
        "INSERT INTO content.materials (material_id, learner_id, object_key, mime, status) "
        "VALUES (%(m)s, %(l)s, %(k)s, 'application/pdf', 'ready')",
        {"m": uuid4(), "l": other, "k": key},
    )

    report = await orphan_objects(pg_db, store, LONG_AGO, dry_run=True)

    assert report.orphans == [key]


async def test_an_object_outside_the_learner_tree_is_an_orphan(pg_db: Db) -> None:
    store = InMemoryObjectStore()
    await _put(store, "learners/not-a-uuid/file.bin")

    report = await orphan_objects(pg_db, store, LONG_AGO)

    assert report.orphans == ["learners/not-a-uuid/file.bin"]
    assert store.objects == {}


async def test_the_orphan_command_prints_the_report(
    pg_db: Db,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learner = await create_learner(pg_db)
    store = InMemoryObjectStore()
    lost = photo_original_key(learner, uuid4())
    await _put(store, lost)

    async def open_db(settings: Settings, **_: Any) -> _Shared:
        return _Shared(pg_db)

    monkeypatch.setattr(cli, "open_db", open_db)
    monkeypatch.setattr(cli, "create_object_store", lambda settings: store)
    args = cli.build_parser().parse_args(
        ["ops", "orphan-objects", "--since", "2020-01-01", "--dry-run"]
    )

    code = await cli._ops(settings, args)  # pyright: ignore[reportPrivateUsage]

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "checked": 1,
        "deleted": 0,
        "dry_run": True,
        "orphans": [lost],
    }
    assert lost in store.objects


async def test_resume_releases_the_stopped_stream(
    pg_db: Db, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    learner = await create_learner(pg_db)
    other = await create_learner(pg_db)
    for who in (learner, other):
        await pg_db.execute(
            "INSERT INTO ops.projector_failures (learner_id, seq, error) VALUES (%(l)s, 1, 'boom')",
            {"l": who},
        )

    async def open_db(settings: Settings, **_: Any) -> _Shared:
        return _Shared(pg_db)

    monkeypatch.setattr(cli, "open_db", open_db)
    args = cli.build_parser().parse_args(["ops", "resume", "--learner", str(learner)])

    assert await cli._ops(settings, args) == 0  # pyright: ignore[reportPrivateUsage]

    rows = await pg_db.fetch_all("SELECT learner_id FROM ops.projector_failures")
    assert [row["learner_id"] for row in rows] == [other]


async def test_replay_deletions_passes_the_mark_and_prints_the_count(
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Closable:
        async def aclose(self) -> None: ...

        async def close(self) -> None: ...

    async def open_db(settings: Settings, **_: Any) -> Closable:
        return Closable()

    async def replay(*args: Any, **kwargs: Any) -> int:
        seen["since"] = args[5]
        seen["redis"] = kwargs["redis"]
        return 3

    monkeypatch.setattr(cli, "open_db", open_db)
    monkeypatch.setattr(cli, "create_driver", lambda settings: Closable())
    monkeypatch.setattr(cli, "create_redis", lambda settings: Closable())
    monkeypatch.setattr(cli, "create_object_store", lambda settings: Closable())
    monkeypatch.setattr(cli, "create_deletion_journal", lambda settings: Closable())
    monkeypatch.setattr(cli, "replay_deletions", replay)
    args = cli.build_parser().parse_args(
        ["ops", "replay-deletions", "--since", "2026-11-03T10:00:00+03:00"]
    )

    code = await cli._ops(settings, args)  # pyright: ignore[reportPrivateUsage]

    assert code == 0
    assert seen["since"] == datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
    assert json.loads(capsys.readouterr().out) == {"replayed": 3}


def test_the_parser_of_the_recovery_commands() -> None:
    parser = cli.build_parser()
    learner = uuid4()
    assert parser.parse_args(["ops", "resume", "--learner", str(learner)]).learner == learner
    assert parser.parse_args(["ops", "orphan-objects", "--since", "2026-11-01"]).dry_run is False
    assert parser.parse_args(["ops", "rebuild", "--all"]).concurrency is None
    assert parser.parse_args(["ops", "rebuild", "--all", "--concurrency", "4"]).concurrency == 4
    for bad in (
        ["ops", "resume"],
        ["ops", "replay-deletions"],
        ["ops", "orphan-objects"],
        ["ops", "rebuild", "--all", "--concurrency", "0"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(bad)


async def test_rebuild_runs_at_most_concurrency_learners_at_once() -> None:
    running = peak = 0

    async def rebuild(learner_id: UUID) -> SimpleNamespace:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return SimpleNamespace(status="rebuilt")

    learners = [uuid4() for _ in range(6)]
    code = await cli._rebuild_each(learners, rebuild, 3)  # pyright: ignore[reportPrivateUsage]

    assert code == 0
    assert peak == 3


async def test_a_failed_learner_is_exit_1_and_the_others_go_on() -> None:
    done: list[UUID] = []

    async def rebuild(learner_id: UUID) -> SimpleNamespace:
        done.append(learner_id)
        return SimpleNamespace(status="busy" if len(done) == 1 else "rebuilt")

    learners = [uuid4() for _ in range(3)]

    assert await cli._rebuild_each(learners, rebuild, 1) == 1  # pyright: ignore[reportPrivateUsage]
    assert done == learners
