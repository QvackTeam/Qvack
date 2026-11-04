"""Operations (ТЗ Фазы 3 §8.6): T-O2…T-O4, T-O6. T-O1 (`ops status`) and `seed-learners` are in
`test_ops_p4_status.py` and `test_ops_p4_seed.py` (WP1.3 step 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quack import cli
from quack.config import Settings
from quack.events.catalog import EVENT_TYPE_VERSIONS
from quack.ops.registry import can_rollback, event_registry, registry_gaps, write_event_registry

# --- T-O4: CLI of Phase 3 --------------------------------------------------------------


def test_cli_parser_phase3(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """§6.7, WP8.1: process roles and the ops commands with their arguments; `worker` (both
    roles in one process, development only) refuses to start on prod with exit code 2."""
    parser = cli.build_parser()
    for argv in (["api"], ["projector"], ["workers"], ["worker"]):
        assert parser.parse_args(argv).command == argv[0]
    seed = parser.parse_args(
        ["ops", "seed-learners", "--count", "3", "--out", "l.json", "--fixture", "x", "--confirm"]
    )
    assert (seed.op, seed.count, seed.out, seed.fixture, seed.confirm) == (
        "seed-learners",
        3,
        "l.json",
        "x",
        True,
    )
    assert parser.parse_args(["ops", "openapi", "--out", "o.json"]).out == "o.json"
    # The commands of Phase 3 over `ops.dlq` and the tombstones are gone (WP1.3 step 3).
    for removed in (["ops", "replay-dlq"], ["ops", "purge-deleted"]):
        with pytest.raises(SystemExit):
            parser.parse_args(removed)
    assert parser.parse_args(["ops", "status"]).op == "status"
    assert parser.parse_args(["ops", "event-registry", "--out", "r.json"]).out == "r.json"
    rollback = parser.parse_args(["ops", "can-rollback", "--to-registry", "prev.json"])
    assert rollback.to_registry == "prev.json"
    assert cli.PROCESS_ROLES == {
        "api": "api",
        "projector": "projector",
        "workers": "workers",
        "worker": "workers",
        "ops": "ops",
    }

    monkeypatch.setattr(cli, "get_settings", lambda: settings.model_copy(update={"env": "prod"}))
    assert cli.main(["worker"]) == 2


def test_the_processes_run_on_phase_4(settings: Settings) -> None:
    """WP1.3 step 3: `cli` has no Phase 3 path of the processes; the flag of D-A-200 is set for
    the resources of `quack.runtime` (the gateway accounts in `ops.llm_usage`)."""
    import structlog

    try:
        for role in ("api", "projector", "workers", "ops"):
            configured = cli.process_settings(
                settings.model_copy(update={"phase4_processes": False}), role
            )
            assert configured.phase4_processes is True
    finally:
        structlog.contextvars.unbind_contextvars("process", "version")


def test_cli_binds_process_role_and_version(settings: Settings) -> None:
    """WP8.1 (Д-§9.1): the role goes into Settings before resources, every log line carries
    `process` and `version`."""
    import structlog

    configured = cli.process_settings(
        settings.model_copy(update={"quack_version": "1.2.3"}), "workers"
    )
    assert configured.process_role == "workers"
    try:
        bound = structlog.contextvars.get_contextvars()
        assert (bound["process"], bound["version"]) == ("workers", "1.2.3")
    finally:
        structlog.contextvars.unbind_contextvars("process", "version")


def test_cli_sets_process_role_before_settings(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WP8.1, WP9.2: `Settings` is validated with the role of the command — prod secrets are
    those of the role (Д-§7), so `migrate` and `projector` start without JWT/Meta secrets."""
    import structlog

    monkeypatch.setenv("PROCESS_ROLE", "api")
    seen: list[str] = []

    def fake_settings() -> Settings:
        import os

        seen.append(os.environ["PROCESS_ROLE"])
        return settings

    monkeypatch.setattr(cli, "get_settings", fake_settings)
    try:
        assert cli.main(["ops", "event-registry", "--out", str(tmp_path / "r.json")]) == 0
    finally:
        structlog.contextvars.unbind_contextvars("process", "version")
    assert seen == ["ops"]


# --- T-O2, T-O6: event registry, rollback check -----------------------------------------

REGISTRY_FIXTURE = Path(__file__).parent / "fixtures" / "event_registry.json"


def test_event_registry_and_can_rollback_of_phase3(tmp_path: Path) -> None:
    """The library of Phase 3 (`quack.ops.registry`, until WP1.3 step 5). The commands moved to
    the registry of Phase 4 (#232): `tests/test_ops_p4_registry.py`."""
    out = tmp_path / "registry.json"
    write_event_registry(out)
    current = json.loads(out.read_text(encoding="utf-8"))
    expected = json.loads(REGISTRY_FIXTURE.read_text(encoding="utf-8"))
    assert current == expected == event_registry()
    pairs = [(e["type"], e["schema_version"]) for e in current["events"]]
    assert pairs == sorted(pairs) and len(pairs) == 37
    assert ("turn.extracted", 2) in pairs and current["rules_version"] == "rules@2"

    assert can_rollback(current, set()) == {
        "can_rollback": True,
        "new_pairs": [],
        "new_pairs_seen": [],
        "rules_changed": False,
    }
    previous = {**current, "events": [e for e in current["events"] if e["schema_version"] == 1]}
    p = {"type": "turn.extracted", "schema_version": 2}
    unseen = can_rollback(previous, set())
    assert unseen["can_rollback"] is True and unseen["new_pairs"] == [p]
    seen = can_rollback(previous, {("turn.extracted", 2)})
    assert seen["can_rollback"] is False and seen["new_pairs_seen"] == [p]
    other_rules = can_rollback({**current, "rules_version": "rules@1"}, set())
    assert other_rules["rules_changed"] is True and other_rules["can_rollback"] is False


def test_event_registry_has_handlers_and_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    assert registry_gaps() == []
    monkeypatch.setitem(EVENT_TYPE_VERSIONS, ("lesson.invented", 1), object())
    assert registry_gaps() == [
        "lesson.invented@1: no projector handler",
        "lesson.invented@1: no dispatcher rule and no 'no rule' mark",
    ]
