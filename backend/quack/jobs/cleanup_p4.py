"""The periodic job `manifests.cleanup` (ТЗ Ф4 WP7.5; Т-§3.2, Т-§3.6; closes Ф3 R14).

Once a day it deletes the turn manifests older than `turn_manifest_retention_days`: the
manifest is the trace of one turn for debugging, not memory (law 1 — the log is the truth).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from quack.db import Db
from quack.jobs.queue import ClaimedJob
from quack.jobs.runner import JobContext, register_job_handler
from quack.logging import get_logger

log = get_logger(__name__)

# Every learner's old manifests (D-A-204): a cross-learner statement of the periodic job.
_DELETE_OLD = "DELETE FROM ops.turn_manifests WHERE created_at < %(before)s"


async def delete_old_manifests(db: Db, before: datetime) -> int:
    async with db.transaction() as conn:
        cursor = await conn.execute(_DELETE_OLD, {"before": before})
        return cursor.rowcount


@register_job_handler("manifests.cleanup")
async def handle_manifests_cleanup(job: ClaimedJob, ctx: JobContext) -> None:
    days = ctx.settings.turn_manifest_retention_days
    deleted = await delete_old_manifests(ctx.db, datetime.now(UTC) - timedelta(days=days))
    log.info("manifests_cleaned", deleted=deleted, period=job.payload.get("period"))
