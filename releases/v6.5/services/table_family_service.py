"""Table-family contracts for disclosures that split or merge over time."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Iterable

@dataclass(frozen=True)
class TableTarget:
    name: str
    role: str = "COMPONENT"
    required: bool = False

@dataclass(frozen=True)
class TableFamily:
    family_id: str
    display_name: str
    targets: tuple[TableTarget, ...]
    def to_dict(self) -> dict:
        return {"family_id": self.family_id, "display_name": self.display_name, "targets": [asdict(x) for x in self.targets]}

INVESTMENT_RETURN_FAMILY = TableFamily("INVESTMENT_RETURN_FAMILY", "投资相关收益", (
    TableTarget("投资净收益", "LEGACY_COMBINED"),
    TableTarget("投资收益", "INVESTMENT_COMPONENT"),
    TableTarget("利息收入", "INTEREST_COMPONENT"),
))
BUILTIN_TABLE_FAMILIES = {INVESTMENT_RETURN_FAMILY.family_id: INVESTMENT_RETURN_FAMILY}

def build_family(family_id: str, display_name: str, targets: Iterable[dict | TableTarget]) -> TableFamily:
    clean=[]
    for target in targets:
        item = target if isinstance(target, TableTarget) else TableTarget(str(target.get("name") or "").strip(), str(target.get("role") or "COMPONENT").strip().upper(), bool(target.get("required", False)))
        if item.name: clean.append(item)
    if not clean: raise ValueError("表族至少需要一个非空目标表名")
    return TableFamily(str(family_id).strip().upper(), str(display_name).strip(), tuple(clean))

def detect_schema_variant(targets: Iterable[dict]) -> str:
    found={str(x.get("role", "")).upper() for x in targets if x.get("status") in {"SUCCESS", "REVIEW_REQUIRED"}}
    if not found: return "NO_MATCH"
    if found == {"LEGACY_COMBINED"}: return "LEGACY_COMBINED"
    if "LEGACY_COMBINED" in found: return "MIXED_REVIEW_REQUIRED"
    if {"INVESTMENT_COMPONENT", "INTEREST_COMPONENT"}.issubset(found): return "SPLIT_COMPONENTS"
    return "PARTIAL_COMPONENTS_REVIEW_REQUIRED"
