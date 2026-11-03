"""Coverage of episodes by extractors (ТЗ Ф4 WP7.3; `Т-§2.8`, `Т-§7.10`).

`ops.coverage(learner_id, episode_seq, extractor, status, observation_seq)`: a row says the
episode was processed by this extractor version — `extracted` with the observation, or
`nothing_to_extract` written by the dispatcher itself (WP7.2). No row — the episode is not
processed and the dispatcher puts the job. The row is written in the transaction of the
observation event: called inside `db.transaction()` it joins it (law 7).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from quack.db import Db

type CoverageStatus = Literal["extracted", "nothing_to_extract"]


async def mark_covered(
    db: Db,
    learner_id: UUID,
    *,
    episode_seq: int,
    extractor: str,
    status: CoverageStatus,
    observation_seq: int | None,
) -> None:
    """Record that `extractor` covered the episode. `extracted` needs the `seq` of its
    `observation.extracted`; `nothing_to_extract` has none. A repeat replaces the row (law 5):
    a re-extraction (`episode.reassigned`, `skill.split`) points it at the new observation."""
    raise NotImplementedError
