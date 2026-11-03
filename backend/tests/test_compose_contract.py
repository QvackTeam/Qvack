"""T-OPS1 (ТЗ Фазы 4): `compose.yaml` keeps the contract of Д-§3, Д-§4.1, Д-§4.2, Д-§6.1, Д-§10."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml  # pyright: ignore[reportMissingModuleSource]

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"

SERVICES = {
    "caddy",
    "api",
    "workers",
    "projector",
    "compute",
    "postgres",
    "neo4j",
    "redis",
    "migrate",
    "backup",
    "meta-mock",
}
# Д-§6.1 table.
STOP_GRACE_S = {"api": 35, "workers": 25, "projector": 15, "compute": 10}
BACKEND_ONLY = {"projector", "compute", "postgres", "neo4j", "redis", "migrate"}


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(COMPOSE.read_text(encoding="utf-8")))


def _bytes(value: str) -> int:
    default = re.fullmatch(r"\$\{[^:}]+:-([^}]+)\}", value)
    text = default.group(1) if default else value
    number, unit = re.fullmatch(r"(\d+(?:\.\d+)?)([mg])", text).groups()  # pyright: ignore[reportOptionalMemberAccess]
    return int(float(number) * (1024**2 if unit == "m" else 1024**3))


def _seconds(value: str) -> int:
    return int(value.rstrip("s"))


def test_services_are_the_documented_ones(compose: dict[str, Any]):
    assert set(compose["services"]) == SERVICES


def test_only_caddy_publishes_ports(compose: dict[str, Any]):
    published = {n for n, s in compose["services"].items() if s.get("ports")}
    assert published == {"caddy"}
    assert sorted(compose["services"]["caddy"]["ports"]) == ["443:443", "80:80"]


def test_networks_follow_d_3_2(compose: dict[str, Any]):
    assert compose["networks"]["backend"] == {"internal": True}
    for name, service in compose["services"].items():
        networks = set(service["networks"])
        assert "backend" in networks, name
        wants_internet = name in {"caddy", "api", "workers", "backup"}
        assert ("egress" in networks) == wants_internet, name
    for name in BACKEND_ONLY:
        assert set(compose["services"][name]["networks"]) == {"backend"}


def test_limits_and_swap_follow_d_4_1(compose: dict[str, Any]):
    for name, service in compose["services"].items():
        assert "cpus" in service and "mem_limit" in service, name
        ratio = _bytes(str(service["memswap_limit"])) / _bytes(str(service["mem_limit"]))
        # Д-§4.1: memswap_limit = mem_limit x 1.25 (rounded to whole MB in the table).
        assert ratio == pytest.approx(1.25, abs=0.01), name
    for name in ("postgres", "compute"):
        assert compose["services"][name]["shm_size"] == "256mb"


def test_stop_grace_period_follows_d_6_1(compose: dict[str, Any]):
    for name, seconds in STOP_GRACE_S.items():
        assert _seconds(compose["services"][name]["stop_grace_period"]) == seconds, name


def test_every_service_has_json_file_logs_10m_x_5(compose: dict[str, Any]):
    for name, service in compose["services"].items():
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "5"},
        }, name


def test_compute_gets_no_secrets_and_projector_no_model_key(compose: dict[str, Any]):
    compute = set(compose["services"]["compute"]["environment"])
    assert compute <= {"LOG_LEVEL"}
    projector = set(compose["services"]["projector"]["environment"])
    assert not projector & {"META_API_KEY", "JWT_SECRET", "COMPUTE_URL"}


def test_only_api_has_the_jwt_secret(compose: dict[str, Any]):
    holders = {
        n for n, s in compose["services"].items() if "JWT_SECRET" in s.get("environment", {})
    }
    assert holders == {"api"}


def test_backup_is_short_lived_and_never_started_by_up(compose: dict[str, Any]):
    backup = compose["services"]["backup"]
    assert backup["restart"] == "no"
    assert backup["profiles"] == ["backup"]
    assert backup["command"] == ["ops", "backup"]
