"""Routes of canvases (ТЗ Ф4 §6.4 «Канвас», WP21.1): `POST /v1/sessions/{id}/canvases`,
`GET /v1/canvases/{id}`, `GET /v1/domains/{id}/canvases`. The learner comes only from the
session cookie (WP18.3); a session, task, canvas or domain of another learner is 404."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from quack.api.auth import CurrentSession, get_current_session
from quack.api.errors import ApiError
from quack.api.resources import AppResources, get_resources
from quack.canvas import boards
from quack.canvas.board import BoardDoc

router = APIRouter(prefix="/v1", tags=["canvas"])

Resources = Annotated[AppResources, Depends(get_resources)]
Session = Annotated[CurrentSession, Depends(get_current_session)]


class OpenCanvas(BaseModel):
    task_id: UUID | None = None


class CanvasView(BaseModel):
    canvas_id: UUID
    session_id: UUID | None
    task_id: UUID | None
    doc: BoardDoc
    version: int
    updated_at: datetime


class CanvasList(BaseModel):
    canvases: list[CanvasView]


def _view(canvas: boards.Canvas) -> CanvasView:
    return CanvasView(
        canvas_id=canvas.canvas_id,
        session_id=canvas.session_id,
        task_id=canvas.task_id,
        doc=canvas.doc,
        version=canvas.version,
        updated_at=canvas.updated_at,
    )


def _not_found(exc: boards.CanvasNotFound) -> ApiError:
    return ApiError("NOT_FOUND", str(exc), status_code=404)


@router.post("/sessions/{session_id}/canvases", status_code=201, response_model=CanvasView)
async def open_canvas(
    session_id: UUID, body: OpenCanvas, session: Session, resources: Resources
) -> CanvasView:
    try:
        canvas = await boards.open_canvas(
            resources.db,
            learner_id=session.learner_id,
            session_id=session_id,
            task_id=body.task_id,
            redis=resources.redis,
        )
    except boards.CanvasNotFound as exc:
        raise _not_found(exc) from exc
    return _view(canvas)


@router.get("/canvases/{canvas_id}", response_model=CanvasView)
async def get_canvas(canvas_id: UUID, session: Session, resources: Resources) -> CanvasView:
    try:
        canvas = await boards.get_canvas(
            resources.db, learner_id=session.learner_id, canvas_id=canvas_id
        )
    except boards.CanvasNotFound as exc:
        raise _not_found(exc) from exc
    return _view(canvas)


@router.get("/domains/{domain_id}/canvases", response_model=CanvasList)
async def domain_canvases(domain_id: UUID, session: Session, resources: Resources) -> CanvasList:
    try:
        canvases = await boards.domain_canvases(
            resources.db, learner_id=session.learner_id, domain_id=domain_id
        )
    except boards.CanvasNotFound as exc:
        raise _not_found(exc) from exc
    return CanvasList(canvases=[_view(c) for c in canvases])
