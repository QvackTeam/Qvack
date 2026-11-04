"""T-DB3 (ТЗ Ф4 §8.2, DoD п.6, G4): no code or dependency of the Phase 1–3 stack is left."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
# DoD п.6: SQLAlchemy, asyncpg, Alembic, PyJWT, pwdlib — import names and distribution names.
MODULES = {"sqlalchemy", "asyncpg", "alembic", "jwt", "pwdlib"}
DISTRIBUTIONS = {"sqlalchemy", "asyncpg", "alembic", "pyjwt", "pwdlib"}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_no_sqlalchemy_left() -> None:
    offenders = [
        f"{path.relative_to(BACKEND)}: {sorted(_imports(path) & MODULES)}"
        for root in ("quack", "tests", "loadtest")
        for path in sorted((BACKEND / root).rglob("*.py"))
        if _imports(path) & MODULES
    ]
    assert offenders == []
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    groups = [project["project"].get("dependencies", []),
              *project.get("dependency-groups", {}).values()]  # fmt: skip
    names = {re.split(r"[\s\[<>=!~;]", spec, maxsplit=1)[0].lower() for g in groups for spec in g}
    assert not names & DISTRIBUTIONS
