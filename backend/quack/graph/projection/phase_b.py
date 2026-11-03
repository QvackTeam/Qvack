"""Phase B of a batch (ТЗ Ф4 WP3.3, WP4; Т-§2.4, Т-§8.1): the fold of every dirty skill over all
its active evidence and exposures; skill properties and computed evidence properties are set
on the slice, and only the changed values reach Neo4j (the diff, `Т-§8.1` «ориентир»)."""

from __future__ import annotations

from quack.graph.projection.misconception_fold import (
    FoldSign,
    MisconceptionParams,
    fold_misconception,
)
from quack.graph.projection.mutations import SetProps
from quack.graph.projection.skill_fold import FoldEvidence, FoldExposure, FoldParams, fold_skill
from quack.graph.projection.view import BatchSlice


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _evidence(batch: BatchSlice, evidence: str) -> FoldEvidence | None:
    e = batch.node("Evidence", evidence)
    if e is None or e.get("status") != "active":
        return None
    family = domain = ""
    options = max_level = 0
    for r in batch.rels("Evidence", evidence, "ON_TASK", out=True):
        task = batch.node("Task", r.to_id) or {}
        family, domain = _str(task.get("familyId")), _str(task.get("domainId"))
        options = len(batch.rels("Task", r.to_id, "HAS_OPTION", out=True))
        levels = [
            _int(t.props.get("level")) for t in batch.rels("Task", r.to_id, "TESTS", out=True)
        ]
        max_level = max(levels, default=0)
    return FoldEvidence(
        id=evidence,
        at_ms=_int(e.get("atMs")),
        seq=_int(e.get("sourceSeq")),
        level=_int(e.get("level")),
        outcome=_str(e.get("outcome")),
        tier=_int(e.get("tier")),
        verification=_str(e.get("verification"), "model"),
        assistance=_str(e.get("assistance"), "none"),
        hint_step=_int(e.get("hintStep")),
        derived_kind=_str(e.get("derivedKind"), "direct"),
        gap_type=_str(e.get("gapType"), "none"),
        family_id=family,
        task_domain_id=domain,
        options=options,
        task_max_level=max_level,
    )


def fold_dirty_skills(
    batch: BatchSlice, skills: set[str], params: FoldParams, as_of_seq: int
) -> None:
    for skill in sorted(skills):
        props = batch.node("Skill", skill)
        if props is None:
            continue
        evidence = [
            found
            for r in batch.rels("Skill", skill, "ON", out=False)
            if (found := _evidence(batch, r.from_id)) is not None
        ]
        exposures = [
            FoldExposure(_int(x.get("atMs")), _int(x.get("sourceSeq")), _str(x.get("kind")))
            for r in batch.rels("Skill", skill, "OF", out=False)
            if (x := batch.node("Exposure", r.from_id)) is not None
        ]
        fold = fold_skill(
            evidence,
            exposures,
            params,
            skill_domain=_str(props.get("domainId")),
            as_of_seq=as_of_seq,
        )
        changes = [SetProps("Skill", skill, fold.skill)]
        changes += [SetProps("Evidence", e, p) for e, p in sorted(fold.evidence.items())]
        batch.apply(changes)


def _sign(batch: BatchSlice, evidence: str, *, resists: bool) -> FoldSign | None:
    e = batch.node("Evidence", evidence)
    if e is None or e.get("status") != "active":
        return None
    family = ""
    for r in batch.rels("Evidence", evidence, "ON_TASK", out=True):
        family = _str((batch.node("Task", r.to_id) or {}).get("familyId"))
    return FoldSign(
        _int(e.get("atMs")), _int(e.get("sourceSeq")), _int(e.get("tier")), family, resists
    )


def fold_dirty_misconceptions(
    batch: BatchSlice, misconceptions: set[str], params: MisconceptionParams
) -> None:
    """Т-§9.2: the status of each misconception the batch touched; `disputed` stays."""
    for misconception in sorted(misconceptions):
        props = batch.node("Misconception", misconception)
        if props is None:
            continue
        signs = [
            sign
            for rel, resists in (("MANIFESTS", False), ("RESISTED", True))
            for r in batch.rels("Misconception", misconception, rel, out=False)
            if (sign := _sign(batch, r.from_id, resists=resists)) is not None
        ]
        state = fold_misconception(
            signs,
            params,
            disputed=props.get("status") == "disputed",
            targeted_session=_str(props.get("targetedInSessionId")),
        )
        batch.apply([SetProps("Misconception", misconception, state)])
