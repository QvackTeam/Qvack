"""Import path of the Phase 3 `graph.curate` handler kept for `quack.runtime.HANDLER_MODULES`
(D-A-208). The handler moved to `quack.jobs.curation_p3`; this file goes with the entry."""

from __future__ import annotations

from quack.jobs.curation_p3 import handle_graph_curate

__all__ = ["handle_graph_curate"]
