"""Self-checks of the shared session fixtures that need no infrastructure."""

from __future__ import annotations

from quack.api.sse import format_sse
from tests.session.helpers import parse_sse

pytest_plugins = ["tests.session.fixtures"]


def test_parse_sse_round_trips_format_sse() -> None:
    body = format_sse("turn_started", {"turn_id": "t"}) + format_sse("done", {})
    assert parse_sse(body) == [("turn_started", {"turn_id": "t"}), ("done", {})]
