"""FastAPI router for Stream 1 (`/v1/learner/*`, `/v1/domains/*`) wiring its HTTP endpoints to
domain service modules (ТЗ §3). Register, login and `GET /v1/auth/me` are removed with the
password and JWT (ТЗ Ф4 §2.3 row 3, WP18.3, D-A-113); sign-in is `quack.auth` (WP18).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from quack.api.auth import get_current_learner_id
from quack.api.errors import ApiError
from quack.api.ratelimit import enforce_action_rate_limit
from quack.api.resources import get_llm, get_resources
from quack.config import Settings
from quack.domains import (
    diagnostic,
    disputes,
    graph_view,
    learner,
    service,
    structure,
    topic_edits,
    topics,
)
from quack.domains.schemas import (
    AnswerDiagnosticRequest,
    AnswerDiagnosticResponse,
    ArchiveDomainRequest,
    ArchiveDomainResponse,
    ConfirmStructureRequest,
    ConfirmStructureResponse,
    CreateDomainRequest,
    CreateDomainResponse,
    DeleteLearnerResponse,
    DomainGraphResponse,
    DomainListResponse,
    DomainSummary,
    EditStructureRequest,
    EditStructureResponse,
    FinishDiagnosticRequest,
    FinishDiagnosticResponse,
    ProposeStructureRequest,
    ProposeStructureResponse,
    StartDiagnosticRequest,
    StartDiagnosticResponse,
    TopicDetailResponse,
    UpdatePreferencesRequest,
    UpdatePreferencesResponse,
    UpdateTopicStatusRequest,
    UpdateTopicStatusResponse,
)
from quack.llm.gateway import LLMGateway

# Every route authenticates at router level, so a request without a session gets 401 before
# body validation (ТЗ Фазы 3 WP1.2, T-A2), and its mutating requests count in the `actions`
# limit.
_protected = APIRouter(
    prefix="/v1",
    tags=["domains"],
    dependencies=[Depends(get_current_learner_id), Depends(enforce_action_rate_limit)],
)


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


type CurrentLearnerId = Annotated[UUID, Depends(get_current_learner_id)]
type CurrentLLMGateway = Annotated[LLMGateway, Depends(get_llm)]


# --- 1. Learner Profile ---


@_protected.patch("/learner/preferences", response_model=UpdatePreferencesResponse, status_code=200)
async def update_preferences_endpoint(
    req: UpdatePreferencesRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> UpdatePreferencesResponse:
    resources = get_resources(request)
    return await learner.update_learner_preferences(resources, learner_id, req)


@_protected.delete("/learner", response_model=DeleteLearnerResponse, status_code=200)
async def delete_learner_endpoint(
    request: Request,
    learner_id: CurrentLearnerId,
) -> DeleteLearnerResponse:
    resources = get_resources(request)
    return await learner.delete_learner_account(resources, learner_id)


# --- 2. Domains CRUD (4 endpoints) ---


@_protected.post("/domains", response_model=CreateDomainResponse, status_code=201)
async def create_domain_endpoint(
    req: CreateDomainRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> CreateDomainResponse:
    resources = get_resources(request)
    return await service.create_domain(resources, learner_id, req)


@_protected.get("/domains", response_model=DomainListResponse, status_code=200)
async def list_domains_endpoint(
    request: Request,
    learner_id: CurrentLearnerId,
    include_archived: Annotated[bool, Query()] = False,
) -> DomainListResponse:
    resources = get_resources(request)
    return await service.list_domains(resources, learner_id, include_archived=include_archived)


@_protected.get("/domains/{domain_id}", response_model=DomainSummary, status_code=200)
async def get_domain_endpoint(
    domain_id: UUID,
    request: Request,
    learner_id: CurrentLearnerId,
) -> DomainSummary:
    resources = get_resources(request)
    return await service.get_domain(resources, learner_id, domain_id)


@_protected.post(
    "/domains/{domain_id}/archive",
    response_model=ArchiveDomainResponse,
    status_code=200,
)
async def archive_domain_endpoint(
    domain_id: UUID,
    req: ArchiveDomainRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> ArchiveDomainResponse:
    resources = get_resources(request)
    return await service.archive_domain(resources, learner_id, domain_id, req)


# --- 3. Structure Onboarding & Editing (4 endpoints) ---


@_protected.post(
    "/domains/{domain_id}/structure/propose",
    response_model=ProposeStructureResponse,
    status_code=200,
)
async def propose_structure_endpoint(
    domain_id: UUID,
    req: ProposeStructureRequest,
    request: Request,
    learner_id: CurrentLearnerId,
    llm: CurrentLLMGateway,
) -> ProposeStructureResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await structure.propose_structure(resources, settings, llm, learner_id, domain_id, req)


@_protected.post(
    "/domains/{domain_id}/structure/confirm",
    response_model=ConfirmStructureResponse,
    status_code=200,
)
async def confirm_structure_endpoint(
    domain_id: UUID,
    req: ConfirmStructureRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> ConfirmStructureResponse:
    resources = get_resources(request)
    return await structure.confirm_structure(resources, learner_id, domain_id, req)


@_protected.patch(
    "/domains/{domain_id}/structure",
    response_model=EditStructureResponse,
    status_code=200,
)
async def edit_structure_endpoint(
    domain_id: UUID,
    req: EditStructureRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> EditStructureResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await structure.edit_structure(resources, settings, learner_id, domain_id, req)


@_protected.patch(
    "/domains/{domain_id}/topics/{topic_id}/status",
    response_model=UpdateTopicStatusResponse,
    status_code=200,
)
async def update_topic_status_endpoint(
    domain_id: UUID,
    topic_id: UUID,
    req: UpdateTopicStatusRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> UpdateTopicStatusResponse:
    resources = get_resources(request)
    return await structure.update_topic_status(resources, learner_id, domain_id, topic_id, req)


# --- 4. Adaptive Diagnostics (3 endpoints) ---


@_protected.post(
    "/domains/{domain_id}/diagnostic/start",
    response_model=StartDiagnosticResponse,
    status_code=200,
)
async def start_diagnostic_endpoint(
    domain_id: UUID,
    req: StartDiagnosticRequest,
    request: Request,
    learner_id: CurrentLearnerId,
    llm: CurrentLLMGateway,
) -> StartDiagnosticResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await diagnostic.start_diagnostic(resources, settings, llm, learner_id, domain_id, req)


@_protected.post(
    "/domains/{domain_id}/diagnostic/answer",
    response_model=AnswerDiagnosticResponse,
    status_code=200,
)
async def answer_diagnostic_endpoint(
    domain_id: UUID,
    req: AnswerDiagnosticRequest,
    request: Request,
    learner_id: CurrentLearnerId,
    llm: CurrentLLMGateway,
) -> AnswerDiagnosticResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await diagnostic.answer_diagnostic(resources, settings, llm, learner_id, domain_id, req)


@_protected.post(
    "/domains/{domain_id}/diagnostic/finish",
    response_model=FinishDiagnosticResponse,
    status_code=200,
)
async def finish_diagnostic_endpoint(
    domain_id: UUID,
    req: FinishDiagnosticRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> FinishDiagnosticResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await diagnostic.finish_diagnostic(resources, settings, learner_id, domain_id, req)


# --- 5. Knowledge Map Views for UI (2 endpoints) ---


@_protected.get(
    "/domains/{domain_id}/graph",
    response_model=DomainGraphResponse,
    status_code=200,
)
async def get_domain_graph_endpoint(
    domain_id: UUID,
    request: Request,
    learner_id: CurrentLearnerId,
    include_archived: Annotated[bool, Query()] = False,
) -> DomainGraphResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await graph_view.get_domain_graph_view(
        resources, settings, learner_id, domain_id, include_archived=include_archived
    )


@_protected.get(
    "/domains/{domain_id}/topics/{topic_id}",
    response_model=TopicDetailResponse,
    status_code=200,
)
async def get_topic_detail_endpoint(
    domain_id: UUID,
    topic_id: UUID,
    request: Request,
    learner_id: CurrentLearnerId,
) -> TopicDetailResponse:
    resources = get_resources(request)
    settings = _get_settings(request)
    return await graph_view.get_topic_detail_view(
        resources, settings, learner_id, domain_id, topic_id
    )


# --- 6. Short topic routes (resolve `domain_id` from the learner's events) ---


@_protected.get(
    "/topics/{topic_id}",
    response_model=TopicDetailResponse,
    status_code=200,
)
async def get_topic_detail_short_endpoint(
    topic_id: UUID,
    request: Request,
    learner_id: CurrentLearnerId,
) -> TopicDetailResponse:
    resources = get_resources(request)
    domain_id = await topics.resolve_topic_domain_id(resources, learner_id, topic_id)
    return await get_topic_detail_endpoint(domain_id, topic_id, request, learner_id)


@_protected.patch(
    "/topics/{topic_id}/status",
    response_model=UpdateTopicStatusResponse,
    status_code=200,
)
async def update_topic_status_short_endpoint(
    topic_id: UUID,
    req: UpdateTopicStatusRequest,
    request: Request,
    learner_id: CurrentLearnerId,
) -> UpdateTopicStatusResponse:
    resources = get_resources(request)
    domain_id = await topics.resolve_topic_domain_id(resources, learner_id, topic_id)
    return await update_topic_status_endpoint(domain_id, topic_id, req, request, learner_id)


router = APIRouter()
router.include_router(_protected)


# --- ТЗ Ф4 WP8.1: «не согласен» and «это была описка» (Т-§2.8, Т-§7.6) ---


def _not_yours() -> ApiError:
    return ApiError("NOT_FOUND", "no such target of this learner", status_code=404)


@_protected.post("/disputes", response_model=disputes.EventAccepted, status_code=202)
async def file_dispute_endpoint(
    req: disputes.DisputeRequest, request: Request, learner_id: CurrentLearnerId
) -> disputes.EventAccepted:
    r = get_resources(request)
    seq = await disputes.file_dispute(r.db, r.neo4j, r.redis, learner_id, req)
    if seq is None:
        raise _not_yours()
    return disputes.EventAccepted(seq=seq)


@_protected.post(
    "/verdicts/{answer_seq}/typo", response_model=disputes.EventAccepted, status_code=202
)
async def declare_typo_endpoint(
    answer_seq: int, req: disputes.TypoRequest, request: Request, learner_id: CurrentLearnerId
) -> disputes.EventAccepted:
    r = get_resources(request)
    seq = await disputes.declare_typo(r.db, r.redis, learner_id, answer_seq, req.part)
    if seq is None:
        raise _not_yours()
    return disputes.EventAccepted(seq=seq)


# --- ТЗ Ф4 WP8.2: edits of topics and «я это уже знаю» (Т-§4.11) ---


def _edited(seq: int | None) -> topic_edits.Edited:
    if seq is None:
        raise _not_yours()
    return topic_edits.Edited(seq=seq)


@_protected.patch("/topics/{topic_id}", response_model=topic_edits.Edited, status_code=202)
async def rename_topic_endpoint(
    topic_id: UUID, req: topic_edits.RenameTopic, request: Request, learner_id: CurrentLearnerId
) -> topic_edits.Edited:
    r = get_resources(request)
    return _edited(await topic_edits.rename(r.db, r.neo4j, r.redis, learner_id, topic_id, req.name))


@_protected.post("/topics/{topic_id}/merge", response_model=topic_edits.Edited, status_code=202)
async def merge_topic_endpoint(
    topic_id: UUID, req: topic_edits.MergeTopic, request: Request, learner_id: CurrentLearnerId
) -> topic_edits.Edited:
    r = get_resources(request)
    return _edited(await topic_edits.merge(r.db, r.neo4j, r.redis, learner_id, topic_id, req.into))


@_protected.post("/topics/{topic_id}/hide", response_model=topic_edits.Edited, status_code=202)
async def hide_topic_endpoint(
    topic_id: UUID, request: Request, learner_id: CurrentLearnerId
) -> topic_edits.Edited:
    r = get_resources(request)
    return _edited(await topic_edits.hide(r.db, r.neo4j, r.redis, learner_id, topic_id))


@_protected.post("/topics/{topic_id}/known", response_model=topic_edits.Edited, status_code=202)
async def claim_known_endpoint(
    topic_id: UUID, request: Request, learner_id: CurrentLearnerId
) -> topic_edits.Edited:
    r = get_resources(request)
    return _edited(await topic_edits.claim_known(r.db, r.neo4j, r.redis, learner_id, topic_id))


@_protected.post(
    "/episodes/{episode_seq}/reassign", response_model=topic_edits.Edited, status_code=202
)
async def reassign_episode_endpoint(
    episode_seq: int,
    req: topic_edits.ReassignEpisode,
    request: Request,
    learner_id: CurrentLearnerId,
) -> topic_edits.Edited:
    r = get_resources(request)
    seq = await topic_edits.reassign(r.db, r.neo4j, r.redis, learner_id, episode_seq, req.topic_id)
    return _edited(seq)
