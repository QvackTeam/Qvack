"""Routes of stream C (ТЗ Ф4 §7.3): auth, consents, learner settings, materials, canvases,
artifacts (notes, blocks, cards, cheatsheets), the learner stream and health.

Stages 20-30 are the consents, 190-270 the artifacts, blocks, cards and the canvas line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from quack.artifacts.cards import write_system_cards
from quack.artifacts.documents import Card, SystemBlock, write_system_blocks
from quack.canvas.boards import open_canvas
from quack.canvas.recognition import commit_typed
from quack.events import records
from quack.events.log import NewEvent, append_events
from quack.events.values import AnswerSpec, MathValue
from quack.practice.role_outputs import TaskCondition
from quack.practice.task_store import create_task
from tests.e2e.journey import ok
from tests.e2e.routes import NO_ID, Ids, Route, Stream

if TYPE_CHECKING:
    from tests.e2e.system import Learner, System


async def _note_created(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    return ids.replace(artifact_id=UUID(payload["artifact_id"]))


async def _note_deleted(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    """WP23.1 reads topics from the Phase 4 log (`topic.created`), which the Phase 3 structure
    of the walk does not write (D-C-112): one topic is recorded there for the notes routes."""
    topic_id, domain_id = uuid4(), uuid4()
    await append_events(
        system.resources.db,
        learner.learner_id,
        [
            NewEvent(
                type="topic.created",
                payload={
                    "topic_id": topic_id,
                    "domain_id": domain_id,
                    "name": "Limits",
                    "origin": "session",
                },
                actor="code",
                idempotency_key=f"te2:topic:{topic_id}",
                domain_id=domain_id,
            )
        ],
    )
    notes = ok(await system.client.get(f"/v1/topics/{topic_id}/notes", headers=learner.headers))
    block_id = uuid4()
    return ids.replace(
        topic_id=topic_id,
        artifact_id=UUID(notes["artifact_id"]),
        learner_block_id=block_id,
        block_id=block_id,
    )


async def _block_written(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    """WP23.1: the system adds a supplement to the learner's block; the walk accepts it."""
    notes = await write_system_blocks(
        system.resources.db,
        learner_id=learner.learner_id,
        kind="notes",
        owner_id=ids.topic_id,
        blocks=[SystemBlock(block_id=ids.block_id, kind="summary", content="More")],
        created_by="artifact_writer@1",
    )
    return ids.replace(block_id=notes.blocks[1].block_id)


async def _supplement_accepted(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    return ids.replace(block_id=ids.learner_block_id)


async def _block_deleted(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    ids = ids.replace(card_id=await _card_of_topic(system, learner, ids))
    return await _canvas_with_a_line(system, learner, ids)


async def _card_edited(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    return ids.replace(card_id=UUID(payload["cards"][0]["card_id"]))


async def _canvas_with_a_line(system: System, learner: Learner, ids: Ids) -> Ids:
    """WP21.3: a canvas of a Phase 4 session with one typed line for the correction route."""
    db = system.resources.db
    session_id = uuid4()
    started = NewEvent(
        type="session.started",
        payload={"session_id": str(session_id), "domain_id": str(uuid4()), "intent": "learn"},
        actor="learner",
        idempotency_key=f"te2:session:{session_id}",
    )
    await append_events(db, learner.learner_id, [started])
    canvas = await open_canvas(db, learner_id=learner.learner_id, session_id=session_id)
    await commit_typed(
        db, learner_id=learner.learner_id, session_id=session_id, canvas_id=canvas.canvas_id,
        block_id="t1", latex="x=1", at_ms=0,
    )  # fmt: skip
    return ids.replace(canvas_id=canvas.canvas_id, line_id="t1")


async def _hub_of_the_walk(system: System, learner: Learner, ids: Ids) -> Ids:
    """WP23.5: one hub in the Phase 4 log (`hub.created`) for the cheat sheet routes."""
    hub_id, domain_id = uuid4(), uuid4()
    created = NewEvent(
        type="hub.created",
        payload={
            "hub_id": hub_id,
            "domain_id": domain_id,
            "name": "Calculus exam",
            "kind": "request",
            "origin": "learner",
            "control_type": "tasks",
        },
        actor="code",
        idempotency_key=f"te2:hub:{hub_id}",
        domain_id=domain_id,
    )
    await append_events(system.resources.db, learner.learner_id, [created])
    return ids.replace(hub_id=hub_id)


async def _card_of_topic(system: System, learner: Learner, ids: Ids) -> UUID:
    """WP23.4: a card of the walk's Phase 4 topic, as the writer leaves it — its task already in
    the bank (D-C-140)."""
    card_id = uuid4()
    await create_task(
        system.resources.db,
        learner_id=learner.learner_id,
        task_id=card_id,
        family_id=card_id,
        source="generated",
        condition=TaskCondition(text="Ratio test when?", latex=None),
        markup=records.TaskMarkupRecord(
            tests=[records.TestedLevelRecord(skill_id=uuid4(), level=3)],
            method_named=False,
            answer=AnswerSpec(type="number", value=MathValue(latex="1", sympy="1")),
        ),
        verification="unchecked",
        actor="artifact_writer@1",
        idempotency_key=f"te2:card:{card_id}",
    )
    card = Card(card_id=card_id, kind="sign_to_method", prompt="Ratio test when?", owner="system")
    await write_system_cards(
        system.resources.db,
        system.resources.settings,
        learner_id=learner.learner_id,
        topic_id=ids.topic_id,
        cards=[card],
        created_by="artifact_writer@1",
    )
    return card_id


STREAM = Stream(
    name="c",
    ids={
        "artifact_id": NO_ID,
        # The walks upload no material and open no canvas: routes with `{material_id}` or
        # `{canvas_id}` get an id nobody has.
        "material_id": NO_ID,
        "canvas_id": NO_ID,
        # WP23.1: the block the walk writes and the supplement the system adds to it.
        "learner_block_id": NO_ID,
        "block_id": NO_ID,
        # WP23.4: a card of the topic (the task behind it).
        "card_id": NO_ID,
        # WP23.5: a hub of the walk (the cheat sheet routes).
        "hub_id": NO_ID,
        # WP21.3: a recognized line of the canvas the walk opens for the correction route.
        "line_id": "none",
    },
    routes=(
        Route(
            "POST",
            "/v1/consents",
            stage=20,
            body=lambda ids, v: {"kind": ["terms", "research"][v], "version": "2026-11"},
        ),
        Route(
            "DELETE",
            "/v1/consents/research",
            stage=30,
            body=lambda ids, v: {"version": ["2026-11", "2026-12"][v]},
        ),
        Route(
            "POST",
            "/v1/artifacts/notes",
            stage=190,
            body=lambda ids, v: {
                "domain_id": str(ids.domain_id),
                "title": ["Note", "Other note"][v],
                "text": "My own words",
            },
            advance=_note_created,
        ),
        Route(
            "PATCH",
            "/v1/artifacts/notes/{artifact_id}",
            stage=200,
            requires=("artifact_id",),
            body=lambda ids, v: {"title": "Note", "text": ["Edited", "Edited again"][v]},
        ),
        Route(
            "DELETE",
            "/v1/artifacts/notes/{artifact_id}",
            stage=210,
            requires=("artifact_id",),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
            advance=_note_deleted,
        ),
        Route(
            "PUT",
            "/v1/artifacts/{artifact_id}/blocks/{block_id}",
            stage=220,
            requires=("artifact_id", "block_id"),
            body=lambda ids, v: {"content": ["My words", "Other words"][v]},
            advance=_block_written,
        ),
        Route(
            "POST",
            "/v1/artifacts/{artifact_id}/blocks/{block_id}/accept",
            stage=230,
            requires=("artifact_id", "block_id"),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
            advance=_supplement_accepted,
        ),
        Route(
            "DELETE",
            "/v1/artifacts/{artifact_id}/blocks/{block_id}",
            stage=240,
            requires=("artifact_id", "block_id"),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
            advance=_block_deleted,
        ),
        Route(
            "PATCH",
            "/v1/cards/{card_id}",
            stage=250,
            requires=("card_id",),
            body=lambda ids, v: {"prompt": ["When the ratio test?", "Other"][v]},
            advance=_card_edited,
        ),
        Route(
            "DELETE",
            "/v1/cards/{card_id}",
            stage=260,
            requires=("card_id",),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
        ),
        Route(
            "POST",
            "/v1/canvases/{canvas_id}/lines/{line_id}/correct",
            stage=270,
            requires=("canvas_id", "line_id"),
            body=lambda ids, v: {"text": ["x=2", "x=3"][v], "sympy": None},
        ),
        # ТЗ Ф4 §6.4, WP23.5: the consent to a cheat sheet and the review of the learner's one.
        Route(
            "POST",
            "/v1/hubs/{hub_id}/cheatsheet",
            stage=272,
            requires=("hub_id",),
            prepare=_hub_of_the_walk,
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
        ),
        Route(
            "POST",
            "/v1/hubs/{hub_id}/cheatsheet/review",
            stage=274,
            requires=("hub_id",),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
        ),
        # --- routes without `idempotency_key`; each reason is a ТЗ rule ---
        # ТЗ Ф4 §6.4: the body is `{timezone}` only; no event, a repeat sets the same value.
        Route(
            "PATCH",
            "/v1/learner/settings",
            no_key="no event; sets core.learners.settings",
        ),
        # ТЗ Ф4 WP20.1: a multipart upload with an optional `session_id`; every upload is a new
        # material with its own `material.uploaded` key (D-C-116).
        Route(
            "POST",
            "/v1/domains/{domain_id}/materials",
            no_key="multipart; each upload is a new material",
            files={"file": ("notes.pdf", b"%PDF-1.7\n1 0 obj\n", "application/pdf")},
        ),
        # ТЗ Ф4 WP21.1: `{task_id?}` only; every call opens a new canvas of the session (D-C-118).
        Route(
            "POST",
            "/v1/sessions/{session_id}/canvases",
            no_key="each call opens a new canvas",
            body=lambda ids, v: {},
        ),
        # ТЗ Ф4 WP22.1: every call issues a new one-time token (Т-§16.1); no event to replay.
        Route(
            "POST",
            "/v1/canvases/{canvas_id}/pairing",
            no_key="no event; issues a new one-time token",
            body_key="none",
            body=lambda ids, v: {},
        ),
        # ТЗ Ф4 WP22.2: like materials, every photo of the sheet is a new snapshot (Т-§22.6).
        Route(
            "POST",
            "/v1/canvases/{canvas_id}/photos",
            no_key="multipart; each photo is a new snapshot",
            files={"file": ("sheet.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp")},
        ),
        # D-C-009: ТЗ-П3 §3 gives this endpoint no key; it writes no event and its job coalesces.
        Route(
            "POST",
            "/v1/topics/{topic_id}/cheatsheet/refresh",
            no_key="no event; the job coalesces",
            body=lambda ids, v: {"domain_id": str(ids.domain_id)},
        ),
    ),
    other_routes=frozenset(
        {
            ("GET", "/health/live"),
            ("GET", "/health/ready"),
            ("GET", "/healthz"),
            # ТЗ Ф4 WP18: sign-in routes (public ones are listed in `PUBLIC_ROUTES`).
            ("POST", "/auth/link"),
            ("GET", "/auth/link/verify"),
            ("GET", "/auth/google/start"),
            ("GET", "/auth/google/callback"),
            ("POST", "/auth/logout"),
            ("GET", "/v1/me"),
            ("POST", "/companion/pair"),
            # ТЗ Ф4 WP20.1, WP20.5
            ("GET", "/v1/domains/{domain_id}/materials"),
            ("GET", "/v1/materials/{material_id}"),
            ("GET", "/v1/search"),
            # ТЗ Ф4 WP21.1
            ("GET", "/v1/canvases/{canvas_id}"),
            ("GET", "/v1/canvases/{canvas_id}/replay"),
            ("GET", "/v1/domains/{domain_id}/canvases"),
            # ТЗ-П3 §3: artifacts, search, cheatsheets, export
            ("GET", "/v1/artifacts"),
            ("GET", "/v1/artifacts/search"),
            ("GET", "/v1/topics/{topic_id}/cheatsheet"),
            ("GET", "/v1/domains/{domain_id}/export"),
            # ТЗ Ф4 §6.4 «Артефакты», WP23.1, WP23.4
            ("GET", "/v1/topics/{topic_id}/notes"),
            ("GET", "/v1/topics/{topic_id}/cards"),
            # ТЗ Ф4 §6.4, WP23.5
            ("GET", "/v1/hubs/{hub_id}/cheatsheet"),
            # §6.4: new endpoints of Phase 3
            ("GET", "/v1/learner/stream"),
        }
    ),
    routers=(
        "quack.artifacts.router:router",
        "quack.artifacts.notes_routes:router",
        "quack.artifacts.cards_routes:router",
        "quack.artifacts.hub_cheatsheet_routes:router",
    ),
)
