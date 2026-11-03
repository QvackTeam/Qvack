"""Graph records of the `rules@3` projector (Т-§3.4).

Values: enumerations always explicit (`'unknown'`, `'none'`), counters and weights 0, times in
int64 ms with 0 «не было» (`Т-§3.4.4`, law 8); lists — `requiredLevels`, `triggers`,
`notation`, `embedding`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

type PropValue = str | int | float | bool | list[str] | list[int] | list[float]
type Props = dict[str, PropValue]
type NodeRef = tuple[str, str]  # (label, id)
type RelKey = tuple[str, str, str, str, str]  # (from_label, from_id, type, to_label, to_id)


@dataclass(frozen=True)
class NodeRecord:
    label: str
    id: str
    props: Props


@dataclass(frozen=True)
class RelRecord:
    from_label: str
    from_id: str
    rel_type: str
    to_label: str
    to_id: str
    props: Props

    @property
    def key(self) -> RelKey:
        return (self.from_label, self.from_id, self.rel_type, self.to_label, self.to_id)


@dataclass
class SubGraph:
    nodes: list[NodeRecord] = field(default_factory=list)
    rels: list[RelRecord] = field(default_factory=list)
