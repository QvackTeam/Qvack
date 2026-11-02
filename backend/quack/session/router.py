"""HTTP surface of the session stream (ТЗ §3); thin delegation to lifecycle/turns/stream."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from quack.api.auth import CurrentSession, get_current_session, require_terms
from quack.api.errors import ApiError
from quack.api.resources import AppResources, get_resources
from quack.compute_client.client import ComputeClient
from quack.config import Settings
from quack.events.errors import IdempotencyConflictError
from quack.llm.gateway import LLMGateway
from quack.session import lifecycle, sessions, stream, turns
from quack.session.action_turn import TurnContextSource, turn_frames
from quack.session.actions import Action, ActionAccepted, ActionFrame
from quack.session.deps import (
    current_learner_id,
    enforce_turn_rate_limit,
    get_compute_client,
    get_llm_gateway,
    get_settings_dep,
)
from quack.session.keepalive import sse_keepalive_response
from quack.session.record import record_action
from quack.session.schemas import (
    ActiveSession,
    FinishResponse,
    FinishSessionRequest,
    HeartbeatResponse,
    SessionDetail,
    SessionListResponse,
    SessionStarted,
    StartSessionRequest,
    TurnRequest,
)
from quack.session.turn_graph import TurnSlots

router = APIRouter(prefix="/v1")

LearnerId = Annotated[UUID, Depends(current_learner_id)]
Resources = Annotated[AppResources, Depends(get_resources)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
CurrentSessionDep = Annotated[CurrentSession, Depends(get_current_session)]


_SSE_ITEM = {
    "type": "object",
    "properties": {
        "data": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/components/schemas/ActionFrame"},
        },
        "event": {"type": "string"},
        "id": {"type": "string"},
        "retry": {"type": "integer", "minimum": 0},
    },
    "required": ["data"],
}


class _EventStream(StreamingResponse):
    """Documents the SSE media type of `/actions`; the route returns its responses itself."""

    media_type = "text/event-stream"


# ТЗ Ф4 WP13.2: one active turn per session in this process (D-B-148 п.е).
PROCESS_TURN_SLOTS = TurnSlots()


def get_turn_context_source(request: Request) -> TurnContextSource:
    """The context of the teacher turn (WP14): set by the assembly as
    `app.state.turn_context_source`; without it the turn cannot run — `503`."""
    source = getattr(request.app.state, "turn_context_source", None)
    if source is None:
        raise ApiError(
            "SERVICE_UNAVAILABLE", "the context of the teacher turn is not set up", status_code=503
        )
    return source


# ТЗ Ф4 WP13.1, WP18.4 (D-C-112 п.3): no session without `consent.given {kind: terms}` of the
# current `terms_version` — `403 CONSENT_REQUIRED`.
@router.post("/sessions", status_code=201, dependencies=[Depends(require_terms)])
async def start_session(
    body: StartSessionRequest, learner_id: LearnerId, resources: Resources, settings: SettingsDep
) -> SessionStarted:
    return await lifecycle.start_session(resources, settings, learner_id, body)


@router.get("/sessions")
async def list_sessions(
    learner_id: LearnerId,
    resources: Resources,
    settings: SettingsDep,
    domain_id: UUID | None = None,
    limit: int | None = Query(None),
) -> SessionListResponse:
    effective_limit = settings.session_list_default_limit if limit is None else limit
    if effective_limit < 1 or effective_limit > settings.session_list_max_limit:
        raise ApiError(
            "VALIDATION_ERROR",
            f"limit must be between 1 and {settings.session_list_max_limit}",
            status_code=422,
        )
    return await lifecycle.list_sessions(resources, learner_id, domain_id, effective_limit)


@router.get("/sessions/active")
async def get_active_session(learner_id: LearnerId, resources: Resources) -> ActiveSession | None:
    return await lifecycle.get_active_session(resources, learner_id)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID, learner_id: LearnerId, resources: Resources
) -> SessionDetail:
    return await lifecycle.get_session(resources, learner_id, session_id)


@router.post("/sessions/{session_id}/heartbeat")
async def heartbeat(
    session_id: UUID, learner_id: LearnerId, resources: Resources, settings: SettingsDep
) -> HeartbeatResponse:
    return await lifecycle.heartbeat(resources, settings, learner_id, session_id)


@router.post("/sessions/{session_id}/finish")
async def finish_session(
    session_id: UUID, body: FinishSessionRequest, learner_id: LearnerId, resources: Resources
) -> FinishResponse:
    return await lifecycle.finish_session(resources, learner_id, session_id, body)


@router.post("/sessions/{session_id}/turns")
async def post_turn(
    session_id: UUID,
    body: TurnRequest,
    request: Request,
    learner_id: LearnerId,
    resources: Resources,
    settings: SettingsDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
    compute: Annotated[ComputeClient, Depends(get_compute_client)],
) -> StreamingResponse:
    await enforce_turn_rate_limit(resources, settings, learner_id)
    events = await turns.open_turn(
        resources,
        settings,
        gateway,
        compute,
        learner_id,
        session_id,
        body,
        str(getattr(request.state, "request_id", "")),
    )
    return sse_keepalive_response(events, settings.sse_keepalive_s)


@router.post(
    "/sessions/{session_id}/actions",
    response_class=_EventStream,
    response_model=None,
    responses={
        200: {
            "description": "Actions with a teacher turn: SSE frames in the order of ТЗ Ф4 §4.7.",
            # `model` keeps `ActionFrame` among the components; the event is documented as one
            # SSE item, as FastAPI does for a streamed route (seam S11, unchanged from #75).
            "model": ActionFrame,
            "content": {"text/event-stream": {"itemSchema": _SSE_ITEM}},
        },
        201: {
            "description": "Actions without a teacher turn (`confidence`): the action event seq.",
            "content": {"application/json": {"schema": ActionAccepted.model_json_schema()}},
        },
    },
)
async def post_action(
    session_id: UUID,
    body: Action,
    current: CurrentSessionDep,
    resources: Resources,
    settings: SettingsDep,
    source: Annotated[TurnContextSource, Depends(get_turn_context_source)],
) -> Response:
    """ТЗ Ф4 WP13.1 (`Т-§1.4`): one learner action of an open session of the learner. A kind
    without a teacher turn answers `201 {seq}`; a kind with one — SSE frames of §4.7 (D-B-156);
    a session the inactivity sweep ended comes back first (WP13.10). The learner is the one of
    the session cookie (Т-§19.1)."""
    learner_id = current.learner_id
    try:
        open_session = await sessions.get_session(
            resources.db, learner_id=learner_id, session_id=session_id
        )
        if open_session.status != "active" and not await sessions.resume_if_swept(
            resources.db, learner_id=learner_id, session_id=session_id
        ):
            raise LookupError(f"session {session_id} is ended")
        recorded = await record_action(
            resources.db,
            body,
            learner_id=learner_id,
            session_id=session_id,
            domain_id=open_session.domain_id,
            settings=settings,
            redis=resources.redis,
        )
    except LookupError as exc:
        raise ApiError("NOT_FOUND", str(exc), status_code=404) from exc
    except IdempotencyConflictError as exc:
        raise ApiError("IDEMPOTENCY_CONFLICT", str(exc), status_code=409) from exc
    if not recorded.starts_turn:
        return JSONResponse(ActionAccepted(seq=recorded.seq).model_dump(), status_code=201)
    frames = turn_frames(
        db=resources.db,
        redis=resources.redis,
        settings=settings,
        source=source,
        slots=PROCESS_TURN_SLOTS,
        learner_id=learner_id,
        session_id=session_id,
        domain_id=open_session.domain_id,
        recorded=recorded,
        action=body,
    )
    return sse_keepalive_response(frames, settings.sse_keepalive_s)


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: UUID, learner_id: LearnerId, resources: Resources, settings: SettingsDep
) -> StreamingResponse:
    events = await stream.stream_session_events(resources, learner_id, session_id)
    return sse_keepalive_response(events, settings.sse_keepalive_s)
