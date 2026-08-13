"""v6.7 research-definition, table-family and strategy registry.

The registry intentionally separates metric semantics from acquisition
structures.  It is SQLite-backed, append-audited and requires no Python
special-case when a user adds a new research definition.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any


def _now(registry) -> str:
    from metadata_registry import now_iso
    return now_iso()


FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION = (
    "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V4"
)
FINANCIAL_INVESTMENT_NEW_MEMBERS = [
    "fvtpl_assets",
    "debt_investment",
    "other_debt_investment",
    "other_equity_investment",
]
FINANCIAL_INVESTMENT_LEGACY_MEMBERS = [
    "legacy_fvtpl_assets",
    "legacy_loans",
    "time_deposits",
    "available_for_sale_assets",
    "held_to_maturity_investments",
]
FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS = [
    "long_term_equity",
]
FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS = {
    "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION": {
        "CONSOLIDATED": {
            "required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "current_required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "historical_variant_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "optional_members": [],
        },
    },
    "LEGACY_FINANCIAL_ASSET_CLASSIFICATION": {
        "CONSOLIDATED": {
            "required_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "current_required_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "historical_variant_members": [],
            "optional_members": [],
        },
    },
    "MIXED_TRANSITION_PRESENTATION": {
        "CONSOLIDATED": {
            "required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "current_required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "historical_variant_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "optional_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
        },
    },
    "UNKNOWN": {
        "CONSOLIDATED": {
            "required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "current_required_members": FINANCIAL_INVESTMENT_NEW_MEMBERS,
            "historical_variant_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "optional_members": [],
        },
    },
}


BUILTIN_STRATEGIES = {
    "STATEMENT_PARENT_TO_MULTI_NOTE": {"description": "主表父项→多个子项→多个附注", "plugin": "statement_multi_note"},
    "STATEMENT_ITEM_TO_NOTE_FAMILY": {"description": "单一主表项目→附注表族", "plugin": "statement_item_note_family"},
    "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE": {"description": "单一主表项目→复杂附注表", "plugin": "statement_item_complex_note"},
    "DIRECT_NOTE_TABLE_FAMILY": {"description": "直接在附注/披露中定位表族", "plugin": "direct_note_table"},
    "DIRECT_DISCLOSURE_SEARCH": {"description": "直接披露搜索", "plugin": "direct_disclosure"},
}

BUILTIN_FAMILIES = {
    "financial_investment": {
        "display_name": "金融投资", "definition_version": "FINANCIAL_INVESTMENT_V1",
        "discovery_strategy": "STATEMENT_PARENT_TO_MULTI_NOTE", "preferred_statement_types": ["BALANCE_SHEET"],
        "preferred_scope": "CONSOLIDATED", "core_members": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"],
        "optional_members": ["reverse_repo", "capital_guarantee_deposit"], "excluded_members": [],
        "family_resolution_contract": {
            "contract_version": FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION,
            "allowed_resolution_modes": ["EXPLICIT_PARENT", "IMPLICIT_MEMBER_SET", "HYBRID"],
            "explicit_parent_aliases": ["金融投资"],
            "direct_member_concepts": [
                "legacy_fvtpl_assets", "legacy_loans",
                "time_deposits", "available_for_sale_assets", "held_to_maturity_investments",
            ],
            "required_members": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"],
            "current_required_members": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"],
            "historical_variant_members": FINANCIAL_INVESTMENT_LEGACY_MEMBERS,
            "optional_members": ["legacy_fvtpl_assets", "legacy_loans", "available_for_sale_assets", "held_to_maturity_investments"],
            "outside_family_members": FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS,
            "expected_member_contracts": FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS,
            "mutually_exclusive_members": [["fvtpl_assets", "legacy_fvtpl_assets"]],
            "presentation_regime_rules": "REGISTRY_MEMBER_SET_ONLY",
            "member_inclusion_policy": "VERSIONED_EXACT_ALIAS_ONLY",
            "family_total_contract": "SOURCE_TOTAL_OR_CERTIFIED_DERIVATION_ONLY",
            "comparability_contract": "NO_LEGACY_NEW_AUTO_BRIDGE",
        },
        "description": "主报表金融投资构成及其附注明细，不自动纳入研究依赖的扩展资产。",
    },
    "investment_portfolio": {
        "display_name": "投资组合", "definition_version": "INVESTMENT_PORTFOLIO_V1",
        "discovery_strategy": "DIRECT_NOTE_TABLE_FAMILY", "preferred_statement_types": ["NOTE_SECTION"],
        "preferred_scope": "CONSOLIDATED", "core_members": ["portfolio_by_category", "portfolio_by_measurement"],
        "optional_members": [], "excluded_members": [],
        "description": "独立投资组合披露；不得与 financial_investment 的会计附注子表混合。",
    },
}

BUILTIN_MEMBERS = {
    "financial_investment": [
        {"member_id": "financial_investment_anchor", "display_name": "金融投资_主报表构成", "member_role": "STATEMENT_ANCHOR", "required": True, "canonical_order": 0, "aliases": ["金融投资"], "row_signatures": ["债权投资", "其他债权投资"]},
        {"member_id": "fvtpl_assets", "display_name": "以公允价值计量且其变动计入当期损益的金融资产", "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 1, "aliases": ["交易性金融资产", "FVTPL金融资产"], "row_signatures": [], "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION", "classification_axis": "ASSET_TYPE", "canonical_analysis_bucket": "fvtpl_assets", "comparability_status": "EXACT"},
        {"member_id": "debt_investment", "display_name": "债权投资", "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 2, "aliases": [], "row_signatures": ["政府债券", "金融债", "企业债"], "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION", "classification_axis": "ASSET_TYPE"},
        {"member_id": "other_debt_investment", "display_name": "其他债权投资", "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 3, "aliases": [], "row_signatures": ["政府债券", "金融债"], "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION", "classification_axis": "ASSET_TYPE"},
        {"member_id": "other_equity_investment", "display_name": "其他权益工具投资", "member_role": "NOTE_DETAIL", "required": True, "canonical_order": 4, "aliases": [], "row_signatures": ["股票", "基金"], "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION", "classification_axis": "ASSET_TYPE"},
        # Direct statement members are not aliases for the newer debt/equity
        # categories. They preserve a legacy presentation without unsafe
        # cross-regime mapping.
        {"member_id": "legacy_fvtpl_assets", "display_name": "以公允价值计量且其变动计入当期损益的金融资产", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 10, "aliases": [], "row_signatures": [], "direct_member": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "canonical_analysis_bucket": "legacy_fvtpl_assets", "comparability_status": "PARTIALLY_COMPARABLE"},
        {"member_id": "legacy_loans", "display_name": "贷款", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 11, "aliases": ["贷款及应收款项"], "row_signatures": [], "direct_member": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "canonical_analysis_bucket": "legacy_loans", "comparability_status": "PARTIALLY_COMPARABLE"},
        {"member_id": "time_deposits", "display_name": "定期存款", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 12, "aliases": [], "row_signatures": [], "direct_member": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "canonical_analysis_bucket": "time_deposits", "comparability_status": "PARTIALLY_COMPARABLE"},
        {"member_id": "available_for_sale_assets", "display_name": "可供出售金融资产", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 13, "aliases": [], "row_signatures": [], "direct_member": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "canonical_analysis_bucket": "available_for_sale_assets", "comparability_status": "PARTIALLY_COMPARABLE"},
        {"member_id": "held_to_maturity_investments", "display_name": "持有至到期投资", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 14, "aliases": [], "row_signatures": [], "direct_member": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "classification_axis": "ASSET_TYPE", "canonical_analysis_bucket": "held_to_maturity_investments", "comparability_status": "PARTIALLY_COMPARABLE"},
        {"member_id": "long_term_equity", "display_name": "长期股权投资", "member_role": "NOTE_DETAIL", "required": False, "canonical_order": 15, "aliases": [], "row_signatures": [], "direct_member": False, "outside_family": True, "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION", "canonical_analysis_bucket": "long_term_equity", "comparability_status": "PARTIALLY_COMPARABLE"},
    ],
    "investment_portfolio": [
        {"member_id": "portfolio_by_category", "display_name": "投资组合（按投资品种）", "member_role": "DIRECT_DISCLOSURE_TABLE", "required": True, "canonical_order": 1,
         "aliases": ["投资组合(按投资品种)", "投资组合按投资品种", "投资资产按投资品种", "投资资产配置（按品种）", "保险资金投资组合（按投资品种）", "投资资产情况", "投资组合情况"],
         "row_signatures": ["现金", "定期存款", "债券", "股票", "长期股权投资", "投资资产合计"],
         "column_signatures": ["账面值", "占总额比例", "比例"],
         "classification_axis": "BY_INVESTMENT_OBJECT",
         "amount_columns": ["账面值"], "ratio_columns": ["占总额比例"],
         "ratio_total_reconciliation": True},
        {"member_id": "portfolio_by_measurement", "display_name": "投资组合（按会计计量）", "member_role": "DIRECT_DISCLOSURE_TABLE", "required": True, "canonical_order": 2,
         "aliases": ["投资组合(按会计计量)", "投资组合按会计计量", "投资资产按计量属性", "保险资金投资组合（按会计计量）"],
         "row_signatures": ["以公允价值计量且其变动计入当期损益", "其他综合收益", "固收类", "股票", "权益型基金"],
         "column_signatures": ["账面值", "占总额比例", "比例"],
         "classification_axis": "BY_ACCOUNTING_MEASUREMENT",
         "amount_columns": ["账面值"], "ratio_columns": ["占总额比例"],
         "ratio_total_reconciliation": True},
    ],
}

BUILTIN_METRICS = [
    {"metric_id": "EQUITY_INVESTMENT_RATIO", "display_name": "权益类投资资产占比", "description": "从投资组合研究表推导的比例指标"},
    {"metric_id": "TOTAL_PREMIUM", "display_name": "总保费", "description": "保险业务规模指标"},
]

BUILTIN_DOMAINS = {
    "INVESTMENT_ASSET_ANALYSIS": {
        "display_name": "投资资产分析域",
        "description": "跨金融投资主表和投资组合披露的上位研究域；不覆盖来源事实",
        "families": ["financial_investment", "investment_portfolio"],
        "bridge_contracts": [
            {
                "source_family_id": "investment_portfolio",
                "source_member_id": "portfolio_by_category",
                "target_family_id": "financial_investment",
                "target_member_id": None,
                "analysis_bucket": "portfolio",
                "comparability_status": "PARTIALLY_COMPARABLE",
                "measurement_basis": "FAIR_VALUE_AMORTIZED_COST_MIXED",
                "disclosure_context": "MANAGEMENT_DISCUSSION",
            },
            {
                "source_family_id": "financial_investment",
                "source_member_id": None,
                "target_family_id": "investment_portfolio",
                "target_member_id": "portfolio_by_category",
                "analysis_bucket": "financial_statement",
                "comparability_status": "PARTIALLY_COMPARABLE",
                "measurement_basis": "AMORTIZED_COST_FAIR_VALUE",
                "disclosure_context": "FINANCIAL_STATEMENT_NOTES",
            },
        ],
    },
}

BUILTIN_MAPPINGS = [
    {"metric_id": "EQUITY_INVESTMENT_RATIO", "family_id": "investment_portfolio", "member_id": "portfolio_by_category", "row_path_hint": "股权型金融资产", "priority": 1},
]


class ResearchDefinitionService:
    def __init__(self, registry):
        self.registry = registry
        self.seed_builtin()

    def seed_builtin(self) -> None:
        with self.registry.connect() as conn:
            now = _now(self.registry)
            for strategy_id, payload in BUILTIN_STRATEGIES.items():
                conn.execute("INSERT OR IGNORE INTO discovery_strategies(strategy_id,display_name,plugin_key,payload_json,archived,created_at,updated_at) VALUES(?,?,?,?,0,?,?)", (strategy_id, strategy_id, payload["plugin"], json.dumps(payload, ensure_ascii=False), now, now))
            for family_id, payload in BUILTIN_FAMILIES.items():
                conn.execute("INSERT OR IGNORE INTO table_families(family_id,display_name,definition_version,discovery_strategy,payload_json,archived,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?)", (family_id, payload["display_name"], payload["definition_version"], payload["discovery_strategy"], json.dumps(payload, ensure_ascii=False), now, now))
                # The release-owned resolution contract is versioned semantic
                # policy.  Preserve user extension fields, but migrate known
                # former members out of the financial-investment family.
                if family_id == "financial_investment":
                    current = conn.execute("SELECT payload_json FROM table_families WHERE family_id=?", (family_id,)).fetchone()
                    current_payload = json.loads((current[0] if current else "") or "{}")
                    existing_contract = dict(current_payload.get("family_resolution_contract") or {})
                    # These fields are release-owned accounting semantics.
                    # Replace them during a contract-version migration rather
                    # than retaining a stale V2 snapshot that silently omits
                    # a valid legacy member (for example 中国人寿的定期存款).
                    for key, value in payload["family_resolution_contract"].items():
                        if key in {
                            "contract_version", "direct_member_concepts",
                            "required_members", "current_required_members",
                            "historical_variant_members", "optional_members",
                            "outside_family_members", "expected_member_contracts",
                            "mutually_exclusive_members", "presentation_regime_rules",
                            "member_inclusion_policy", "family_total_contract",
                            "comparability_contract",
                        }:
                            existing_contract[key] = value
                        else:
                            existing_contract.setdefault(key, value)
                    outside = set(FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS)
                    existing_contract["direct_member_concepts"] = [
                        member_id
                        for member_id in dict.fromkeys(
                            existing_contract.get("direct_member_concepts") or []
                        )
                        if member_id not in outside
                    ]
                    existing_contract["optional_members"] = [
                        member_id
                        for member_id in dict.fromkeys(
                            existing_contract.get("optional_members") or []
                        )
                        if member_id not in outside
                    ]
                    existing_contract["outside_family_members"] = list(
                        FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS
                    )
                    existing_contract["expected_member_contracts"] = (
                        FINANCIAL_INVESTMENT_EXPECTED_MEMBER_CONTRACTS
                    )
                    existing_contract["contract_version"] = (
                        FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION
                    )
                    current_payload["family_resolution_contract"] = existing_contract
                    current_payload["optional_members"] = [
                        member_id
                        for member_id in dict.fromkeys(
                            current_payload.get("optional_members") or []
                        )
                        if member_id not in outside
                    ]
                    current_payload["member_contract_migration"] = {
                        "version": FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION,
                        "outside_family_members": list(
                            FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS
                        ),
                    }
                    conn.execute("UPDATE table_families SET payload_json=?,updated_at=? WHERE family_id=?", (json.dumps(current_payload, ensure_ascii=False), now, family_id))
                for member in BUILTIN_MEMBERS[family_id]:
                    conn.execute("INSERT OR IGNORE INTO family_members(member_id,family_id,display_name,member_role,required,canonical_order,payload_json,archived,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?)", (member["member_id"], family_id, member["display_name"], member["member_role"], int(member["required"]), member["canonical_order"], json.dumps(member, ensure_ascii=False), now, now))
                    # Existing v6.10 registries have member IDs already. Add
                    # semantic fields idempotently so legacy assets remain
                    # traceable without recreating a research definition.
                    current_member = conn.execute("SELECT payload_json FROM family_members WHERE member_id=? AND family_id=?", (member["member_id"], family_id)).fetchone()
                    current_member_payload = json.loads((current_member[0] if current_member else "") or "{}")
                    changed = False
                    for key in ("direct_member", "outside_family", "presentation_regime", "classification_axis", "canonical_analysis_bucket", "comparability_status"):
                        if key in member and current_member_payload.get(key) != member[key]:
                            current_member_payload[key] = member[key]; changed = True
                        if key not in member and key in current_member_payload and key in {"direct_member", "outside_family"}:
                            # Remove a formerly release-owned flag that no
                            # longer applies; user extension fields remain.
                            current_member_payload.pop(key, None); changed = True
                    if (
                        family_id == "financial_investment"
                        and member["member_id"]
                        in FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS
                    ):
                        if current_member_payload.get("direct_member") is not False:
                            current_member_payload["direct_member"] = False
                            changed = True
                        if current_member_payload.get("outside_family") is not True:
                            current_member_payload["outside_family"] = True
                            changed = True
                    if changed:
                        conn.execute("UPDATE family_members SET payload_json=?,updated_at=? WHERE member_id=? AND family_id=?", (json.dumps(current_member_payload, ensure_ascii=False), now, member["member_id"], family_id))
            for metric in BUILTIN_METRICS:
                conn.execute("INSERT OR IGNORE INTO research_metrics(metric_id,display_name,payload_json,archived,created_at,updated_at) VALUES(?,?,?,0,?,?)", (metric["metric_id"], metric["display_name"], json.dumps(metric, ensure_ascii=False), now, now))
            for mapping in BUILTIN_MAPPINGS:
                conn.execute("INSERT OR IGNORE INTO metric_family_mappings(mapping_id,metric_id,family_id,member_id,row_path_hint,priority,payload_json,archived,created_at) VALUES(?,?,?,?,?,?,?,0,?)", ("MAP_" + mapping["metric_id"] + "_" + mapping["family_id"], mapping["metric_id"], mapping["family_id"], mapping["member_id"], mapping["row_path_hint"], mapping["priority"], json.dumps(mapping, ensure_ascii=False), now))
            # v6.10: seed analysis domains and bridge contracts.
            for domain_id, domain in BUILTIN_DOMAINS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_domains(domain_id,display_name,description,payload_json,created_at) VALUES(?,?,?,?,?)",
                    (domain_id, domain["display_name"], domain["description"],
                     json.dumps(domain, ensure_ascii=False), now),
                )
                for contract in domain.get("bridge_contracts") or []:
                    bridge_id = "BRIDGE_" + domain_id + "_" + (contract.get("source_family_id") or "X") + "_" + (contract.get("target_family_id") or "Y")
                    conn.execute(
                        """INSERT OR IGNORE INTO domain_bridge_contracts(
                           bridge_contract_id,domain_id,source_family_id,source_member_id,
                           target_family_id,target_member_id,analysis_bucket,
                           comparability_status,measurement_basis,disclosure_context,
                           payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (bridge_id, domain_id,
                         contract["source_family_id"], contract.get("source_member_id"),
                         contract["target_family_id"], contract.get("target_member_id"),
                         contract.get("analysis_bucket"), contract["comparability_status"],
                         contract.get("measurement_basis"), contract.get("disclosure_context"),
                         json.dumps(contract, ensure_ascii=False), now),
                    )

            # Definitions pin semantics and acquisition choices for a batch.
            for family_id, family in BUILTIN_FAMILIES.items():
                definition_id = family["definition_version"]
                payload = {"definition_id": definition_id, "display_name": family["display_name"], "table_families": [family_id], "definition_version": definition_id, "research_scope": {"core_members": family["core_members"], "optional_members": family["optional_members"], "excluded_members": family["excluded_members"]}}
                conn.execute("INSERT OR IGNORE INTO research_definitions(definition_id,display_name,definition_version,payload_json,status,created_at,updated_at) VALUES(?,?,?,?, 'ACTIVE', ?, ?)", (definition_id, family["display_name"], definition_id, json.dumps(payload, ensure_ascii=False), now, now))
                if family_id == "financial_investment":
                    current = conn.execute(
                        "SELECT payload_json FROM research_definitions WHERE definition_id=?",
                        (definition_id,),
                    ).fetchone()
                    definition_payload = json.loads(
                        (current[0] if current else "") or "{}"
                    )
                    research_scope = dict(
                        definition_payload.get("research_scope") or {}
                    )
                    outside = set(FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS)
                    for key in ("core_members", "optional_members"):
                        research_scope[key] = [
                            member_id
                            for member_id in dict.fromkeys(
                                research_scope.get(key) or []
                            )
                            if member_id not in outside
                        ]
                    research_scope["outside_family_members"] = list(
                        FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS
                    )
                    research_scope["expected_member_contract_version"] = (
                        FINANCIAL_INVESTMENT_MEMBER_CONTRACT_VERSION
                    )
                    # This loop's local ``payload`` may still refer to an
                    # earlier strategy/family iteration.  Use the explicit
                    # financial-investment source contract so seeding an
                    # isolated registry cannot depend on loop-variable state.
                    resolution_contract = BUILTIN_FAMILIES[family_id]["family_resolution_contract"]
                    research_scope["current_required_members"] = list(
                        resolution_contract["current_required_members"]
                    )
                    research_scope["historical_variant_members"] = list(
                        resolution_contract["historical_variant_members"]
                    )
                    definition_payload["research_scope"] = research_scope
                    conn.execute(
                        "UPDATE research_definitions SET payload_json=?,updated_at=? WHERE definition_id=?",
                        (
                            json.dumps(definition_payload, ensure_ascii=False),
                            now,
                            definition_id,
                        ),
                    )

    def _rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def families(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived=0"
        rows = self._rows(f"SELECT * FROM table_families {where} ORDER BY display_name")
        for row in rows: row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    def strategies(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived=0"
        rows = self._rows(f"SELECT * FROM discovery_strategies {where} ORDER BY strategy_id")
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    def members(self, family_id: str) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM family_members WHERE family_id=? AND archived=0 ORDER BY canonical_order", (family_id,))
        for row in rows: row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    def family_discovery_context(self, family_id: str) -> dict[str, Any]:
        """Build an immutable generic-discovery hint set from Registry data."""
        family = next((row for row in self.families() if row["family_id"] == family_id), None)
        if not family:
            raise KeyError(family_id)
        member_tokens: list[str] = []
        for member in self.members(family_id):
            member_tokens.append(str(member["display_name"]))
            member_tokens.extend(
                str(value) for value in member["payload"].get("aliases", []) if value
            )
        payload = family["payload"]
        return {
            "registry_family_id": family_id,
            "discovery_strategy": family["discovery_strategy"],
            "preferred_scope": payload.get("preferred_scope"),
            "require_note_reference": family["discovery_strategy"] in {
                "STATEMENT_PARENT_TO_MULTI_NOTE",
                "STATEMENT_ITEM_TO_NOTE_FAMILY",
                "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
            },
            "preferred_statement_type": (
                payload.get("preferred_statement_types") or [None]
            )[0],
            "core_candidates": list(dict.fromkeys(member_tokens)),
            "historical_variants": list(payload.get("historical_variants") or []),
            "expansion_candidates": list(payload.get("optional_members") or []),
            "default_exclusions": list(payload.get("excluded_members") or []),
        }

    def definitions(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE status='ACTIVE'"
        rows = self._rows(f"SELECT * FROM research_definitions {where} ORDER BY display_name,definition_version")
        for row in rows: row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    def definition(self, definition_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM research_definitions WHERE definition_id=?", (definition_id,))
        if not rows: return None
        row = rows[0]; row["payload"] = json.loads(row.pop("payload_json") or "{}"); return row

    def create_definition(self, payload: dict[str, Any], *, actor: str = "UI") -> dict[str, Any]:
        definition_id = str(payload.get("definition_id") or payload.get("definition_version") or "DEF_" + uuid.uuid4().hex[:12]).strip()
        if not definition_id: raise ValueError("definition_id 不能为空")
        table_families = list(payload.get("table_families") or [])
        if not table_families: raise ValueError("Research Definition 至少需要一个 Table Family")
        now = _now(self.registry)
        normalized = dict(payload) | {"definition_id": definition_id, "definition_version": str(payload.get("definition_version") or definition_id), "table_families": table_families}
        with self.registry.connect() as conn:
            old = conn.execute("SELECT payload_json FROM research_definitions WHERE definition_id=?", (definition_id,)).fetchone()
            if old: raise ValueError("definition_id 已存在；请使用复制版本")
            conn.execute("INSERT INTO research_definitions(definition_id,display_name,definition_version,payload_json,status,created_at,updated_at) VALUES(?,?,?,?, 'ACTIVE', ?, ?)", (definition_id, normalized.get("display_name") or definition_id, normalized["definition_version"], json.dumps(normalized, ensure_ascii=False), now, now))
            conn.execute("INSERT INTO research_definition_audit(audit_id,definition_id,action,actor,old_json,new_json,created_at) VALUES(?,?,?,?,?,?,?)", ("RDA_"+uuid.uuid4().hex, definition_id, "CREATE", actor, "{}", json.dumps(normalized, ensure_ascii=False), now))
        return self.definition(definition_id) or normalized

    def save_family(self, payload: dict[str, Any], *, actor: str = "UI") -> dict[str, Any]:
        family_id = str(payload.get("family_id") or "").strip()
        if not family_id: raise ValueError("family_id 不能为空")
        strategy = str(payload.get("discovery_strategy") or "").strip()
        registered = {x["strategy_id"] for x in self.strategies()}
        if strategy not in registered: raise ValueError("必须选择已注册且未归档的 Discovery Strategy")
        now = _now(self.registry)
        with self.registry.connect() as conn:
            old = conn.execute("SELECT payload_json FROM table_families WHERE family_id=?", (family_id,)).fetchone()
            conn.execute("INSERT INTO table_families(family_id,display_name,definition_version,discovery_strategy,payload_json,archived,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?) ON CONFLICT(family_id) DO UPDATE SET display_name=excluded.display_name,definition_version=excluded.definition_version,discovery_strategy=excluded.discovery_strategy,payload_json=excluded.payload_json,updated_at=excluded.updated_at", (family_id, payload.get("display_name") or family_id, payload.get("definition_version") or family_id, strategy, json.dumps(payload, ensure_ascii=False), now, now))
            conn.execute("INSERT INTO research_definition_audit(audit_id,definition_id,action,actor,old_json,new_json,created_at) VALUES(?,?,?,?,?,?,?)", ("RDA_"+uuid.uuid4().hex, family_id, "SAVE_FAMILY", actor, old["payload_json"] if old else "{}", json.dumps(payload, ensure_ascii=False), now))
        return next(x for x in self.families() if x["family_id"] == family_id)

    def save_member(self, family_id: str, payload: dict[str, Any], *, actor: str = "UI") -> dict[str, Any]:
        member_id = str(payload.get("member_id") or "").strip()
        if not member_id: raise ValueError("member_id 不能为空")
        now = _now(self.registry)
        with self.registry.connect() as conn:
            conn.execute("INSERT INTO family_members(member_id,family_id,display_name,member_role,required,canonical_order,payload_json,archived,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,?,?) ON CONFLICT(member_id,family_id) DO UPDATE SET display_name=excluded.display_name,member_role=excluded.member_role,required=excluded.required,canonical_order=excluded.canonical_order,payload_json=excluded.payload_json,updated_at=excluded.updated_at", (member_id, family_id, payload.get("display_name") or member_id, payload.get("member_role") or "DIRECT_DISCLOSURE_TABLE", int(bool(payload.get("required"))), int(payload.get("canonical_order") or 100), json.dumps(payload, ensure_ascii=False), now, now))
        return next(x for x in self.members(family_id) if x["member_id"] == member_id)

    def archive_definition(self, definition_id: str, *, actor: str = "UI", reason: str = "ARCHIVED") -> None:
        """Soft-archive a definition without mutating historical batch pins."""
        now = _now(self.registry)
        with self.registry.connect() as conn:
            old = conn.execute("SELECT payload_json FROM research_definitions WHERE definition_id=?", (definition_id,)).fetchone()
            if not old:
                raise KeyError(definition_id)
            conn.execute("UPDATE research_definitions SET status='ARCHIVED',updated_at=? WHERE definition_id=?", (now, definition_id))
            conn.execute("INSERT INTO research_definition_audit(audit_id,definition_id,action,actor,old_json,new_json,created_at) VALUES(?,?,?,?,?,?,?)", ("RDA_"+uuid.uuid4().hex, definition_id, reason, actor, old["payload_json"], old["payload_json"], now))

    def archive_family(self, family_id: str, *, actor: str = "UI", reason: str = "ARCHIVED") -> None:
        """Soft-archive a family; captures and definition snapshots remain intact."""
        now = _now(self.registry)
        with self.registry.connect() as conn:
            old = conn.execute("SELECT payload_json FROM table_families WHERE family_id=?", (family_id,)).fetchone()
            if not old:
                raise KeyError(family_id)
            conn.execute("UPDATE table_families SET archived=1,updated_at=? WHERE family_id=?", (now, family_id))
            conn.execute("INSERT INTO research_definition_audit(audit_id,definition_id,action,actor,old_json,new_json,created_at) VALUES(?,?,?,?,?,?,?)", ("RDA_"+uuid.uuid4().hex, family_id, reason, actor, old["payload_json"], old["payload_json"], now))

    def clone_definition(self, definition_id: str, new_version: str, *, actor: str = "UI") -> dict[str, Any]:
        source = self.definition(definition_id)
        if not source: raise KeyError(definition_id)
        payload = dict(source["payload"]); payload["definition_id"] = new_version; payload["definition_version"] = new_version
        return self.create_definition(payload, actor=actor)

    def export_definition(self, definition_id: str) -> dict[str, Any]:
        definition = self.definition(definition_id)
        if not definition: raise KeyError(definition_id)
        families = [next((x for x in self.families() if x["family_id"] == fid), None) for fid in definition["payload"].get("table_families", [])]
        return {"definition": definition, "families": families, "members": {f["family_id"]: self.members(f["family_id"]) for f in families if f}}

    def template_stats(self) -> list[dict[str, Any]]:
        return self._rows("SELECT normalized_company AS company, filing_type, statement_type, COALESCE(scope,'') AS scope, table_family, member_table, SUM(CASE WHEN status='ACTIVE' THEN success_count ELSE 0 END) AS accepted, SUM(rejection_count) AS rejected, COUNT(*) AS templates FROM certified_discoveries GROUP BY normalized_company,filing_type,statement_type,scope,table_family,member_table ORDER BY accepted DESC")
