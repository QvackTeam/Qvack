"""The body of the insurance job `check.symbolic` (Т-§6.1, Т-§22.7; ТЗ Ф4 WP11.3).

`run_at` = answer time + `symbolic_check_delay_ms` (dispatcher, seam S6). The job first looks
for the verdict by `verdict:{answer_seq}:{part}` — the inline check of the API may have written
it — and ends if it is there. Otherwise it checks with `symbolic_background_timeout_ms` and
writes the verdict, or `check.failed {answer_seq, part, reason}`, which the dispatcher turns
into `check.model`. The registration of the handler comes with the dispatcher of Phase 4
(stream A, WP7.1, G2).
"""

from __future__ import annotations

from uuid import UUID

from quack.compute_client.client import ComputeClient
from quack.config import Settings
from quack.db.db import Db
from quack.practice.check import CheckFailed, NeedsModel, Verdict

type InsuranceResult = Verdict | CheckFailed | NeedsModel | None


async def insure_symbolic(
    db: Db,
    compute: ComputeClient,
    settings: Settings,
    *,
    learner_id: UUID,
    answer_seq: int,
    part: str,
) -> InsuranceResult:
    """`None` — the verdict was already there; otherwise what was written (a `NeedsModel`
    is not written yet, D-B-146)."""
    raise NotImplementedError
