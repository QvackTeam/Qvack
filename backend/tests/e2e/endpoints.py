"""Valid request bodies for every mutating endpoint (shared by `T-E2` and `T-E3`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI

# `(method, path)` without `idempotency_key`, with the reason (ТЗ Фазы 3 §8.7, T-E2).
NO_IDEMPOTENCY_KEY: dict[tuple[str, str], str] = {
    ("DELETE", "/v1/learner"): "one tombstone per learner; a repeat is a no-op",
    # ТЗ Ф4 §6.4: the body is `{timezone}` only; no event, a repeat sets the same value.
    ("PATCH", "/v1/learner/settings"): "no event; sets core.learners.settings",
    # ТЗ Ф4 WP20.1: a multipart upload with an optional `session_id`; every upload is a new
    # material with its own `material.uploaded` key (D-C-116).
    ("POST", "/v1/domains/{domain_id}/materials"): "multipart; each upload is a new material",
    # ТЗ Ф4 WP21.1: `{task_id?}` only; every call opens a new canvas of the session (D-C-118).
    ("POST", "/v1/sessions/{session_id}/canvases"): "each call opens a new canvas",
    ("POST", "/v1/sessions/{session_id}/heartbeat"): "no event; refreshes presence only",
    # ТЗ Ф4 WP22.1: every call issues a new one-time token (Т-§16.1); no event to replay.
    ("POST", "/v1/canvases/{canvas_id}/pairing"): "no event; issues a new one-time token",
    # ТЗ Ф4 WP22.2: like materials, every photo of the sheet is a new snapshot (Т-§22.6).
    ("POST", "/v1/canvases/{canvas_id}/photos"): "multipart; each photo is a new snapshot",
    # D-C-009: ТЗ-П3 §3 gives this endpoint no key; it writes no event and its job coalesces.
    ("POST", "/v1/topics/{topic_id}/cheatsheet/refresh"): "no event; the job coalesces",
}

# Routes without a body model: the key is not sent.
NO_BODY = {
    ("POST", "/v1/sessions/{session_id}/heartbeat"),
    ("POST", "/v1/canvases/{canvas_id}/pairing"),
}

MUTATING = {"post", "put", "patch", "delete"}


def mutating_routes(app: FastAPI) -> set[tuple[str, str]]:
    """`(METHOD, path)` of mutating `/v1` routes from the OpenAPI schema."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/v1/")
        for method in operations
        if method in MUTATING
    }


# The walks upload no material and open no canvas: routes with `{material_id}` or
# `{canvas_id}` get an id nobody has.
NO_MATERIAL = UUID(int=0)


@dataclass(frozen=True)
class Ids:
    """Objects of one learner that the bodies and paths refer to."""

    domain_id: UUID
    topic_id: UUID
    session_id: UUID
    task_id: UUID
    turn_id: UUID
    artifact_id: UUID
    diagnostic_session_id: UUID
    diagnostic_task_id: UUID
    structure_version: int
    material_id: UUID = NO_MATERIAL
    canvas_id: UUID = NO_MATERIAL


def path_for(path: str, ids: Ids) -> str:
    return path.format(
        domain_id=ids.domain_id,
        topic_id=ids.topic_id,
        session_id=ids.session_id,
        task_id=ids.task_id,
        artifact_id=ids.artifact_id,
        material_id=ids.material_id,
        canvas_id=ids.canvas_id,
    )


# Routes with a multipart body instead of JSON: the files of a valid request.
MULTIPART: dict[tuple[str, str], dict[str, tuple[str, bytes, str]]] = {
    ("POST", "/v1/domains/{domain_id}/materials"): {
        "file": ("notes.pdf", b"%PDF-1.7\n1 0 obj\n", "application/pdf")
    },
    ("POST", "/v1/canvases/{canvas_id}/photos"): {
        "file": ("sheet.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp")
    },
}


def body_for(method: str, path: str, ids: Ids, key: str, variant: int = 0) -> dict[str, Any]:
    """A valid body; `variant=1` differs from `variant=0` in a non-key field."""
    v = variant
    bodies: dict[tuple[str, str], dict[str, Any]] = {
        ("PATCH", "/v1/learner/preferences"): {"preferences": {"language": ["en", "de"][v]}},
        ("POST", "/v1/consents"): {"kind": ["terms", "research"][v], "version": "2026-11"},
        ("DELETE", "/v1/consents/research"): {"version": ["2026-11", "2026-12"][v]},
        ("POST", "/v1/domains"): {"name": ["Physics", "Chemistry"][v]},
        ("POST", "/v1/domains/{domain_id}/archive"): {"reason": ["done", "moved"][v]},
        ("POST", "/v1/domains/{domain_id}/structure/propose"): {
            "goals": ["Pass the exam", "Understand it"][v],
            "background": "School algebra",
            "focus_areas": ["Basics", "Next steps"],
        },
        ("POST", "/v1/domains/{domain_id}/structure/confirm"): {
            "structure_version": ids.structure_version + v
        },
        ("PATCH", "/v1/domains/{domain_id}/structure"): {
            "updated_topics": [{"topic_id": str(ids.topic_id), "name": ["Renamed", "Other"][v]}]
        },
        ("PATCH", "/v1/domains/{domain_id}/topics/{topic_id}/status"): {
            "status": ["active", "skipped"][v]
        },
        ("PATCH", "/v1/topics/{topic_id}/status"): {"status": ["active", "skipped"][v]},
        ("POST", "/v1/domains/{domain_id}/diagnostic/start"): {},
        ("POST", "/v1/domains/{domain_id}/diagnostic/answer"): {
            "session_id": str(ids.diagnostic_session_id),
            "task_id": str(ids.diagnostic_task_id),
            "answer": ["A", "B"][v],
        },
        ("POST", "/v1/domains/{domain_id}/diagnostic/finish"): {
            "session_id": str(ids.diagnostic_session_id if v == 0 else ids.session_id)
        },
        ("POST", "/v1/sessions"): {
            "domain_id": str(ids.domain_id),
            "mode": ["learn", "practice"][v],
        },
        ("POST", "/v1/sessions/{session_id}/finish"): {},
        ("POST", "/v1/sessions/{session_id}/heartbeat"): {},
        ("POST", "/v1/sessions/{session_id}/canvases"): {},
        ("POST", "/v1/sessions/{session_id}/turns"): {"text": ["Hello", "Bye"][v]},
        ("POST", "/v1/sessions/{session_id}/tasks/next"): {
            "topic_id": str(ids.topic_id),
            "turn_id": str(ids.turn_id),
            "kind": ["choice", "open"][v],
        },
        ("POST", "/v1/sessions/{session_id}/tasks/{task_id}/hint"): {
            "turn_id": str(ids.turn_id if v == 0 else ids.session_id)
        },
        ("POST", "/v1/sessions/{session_id}/tasks/{task_id}/submit"): {
            "turn_id": str(ids.turn_id),
            "answer": ["A", "B"][v],
        },
        ("POST", "/v1/artifacts/notes"): {
            "domain_id": str(ids.domain_id),
            "title": ["Note", "Other note"][v],
            "text": "My own words",
        },
        ("PATCH", "/v1/artifacts/notes/{artifact_id}"): {
            "title": "Note",
            "text": ["Edited", "Edited again"][v],
        },
        ("DELETE", "/v1/artifacts/notes/{artifact_id}"): {},
        ("POST", "/v1/canvases/{canvas_id}/pairing"): {},
        ("POST", "/v1/topics/{topic_id}/cheatsheet/refresh"): {"domain_id": str(ids.domain_id)},
    }
    body = dict(bodies[(method, path)])
    if (method, path) not in NO_BODY:
        body["idempotency_key"] = key
    return body
