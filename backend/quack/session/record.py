"""The journal part of `POST /v1/sessions/{id}/actions` (Т-§2.2, Т-§2.3; ТЗ Ф4 WP13.1): every
action kind writes its event (`ACTION_EVENT_TYPES`) under the client's `idempotency_key`; an
answer goes with its instant verdict in one transaction (WP11.2); the kinds of
`TURN_ACTION_KINDS` then start a teacher turn (WP13.2)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

from quack.config import Settings
from quack.db.db import Db
from quack.practice.check import Verdict
from quack.session.actions import Action


@dataclass(frozen=True)
class RecordedAction:
    """`seq` — the action's event (`action_recorded` frame, §4.7); `verdict` — an instant
    verdict written with an answer; `starts_turn` — the kind has a teacher turn."""

    seq: int
    starts_turn: bool
    verdict: Verdict | None = None


async def record_action(
    db: Db,
    action: Action,
    *,
    learner_id: UUID,
    session_id: UUID,
    domain_id: UUID | None,
    settings: Settings,
    redis: Redis | None = None,
) -> RecordedAction:
    """Write the action's event(s); `LookupError` — the task or the turn element it names
    is not the learner's."""
    raise NotImplementedError
