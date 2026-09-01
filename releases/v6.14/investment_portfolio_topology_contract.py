"""Declarative v6.13 investment-portfolio acquisition topology contract."""
from __future__ import annotations


INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_VERSION = (
    "INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_V2"
)

INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT = {
    "contract_version": INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_VERSION,
    "runtime_activation_status": "ACTIVE_FOR_INVESTMENT_PORTFOLIO_V2",
    "resolver_implementation_status": "IMPLEMENTED_NODE_4_NATIVE_FIRST",
    "execution_plan_status": "FIVE_TOPOLOGY_UI_OFFLINE_SHARED_PLAN_NODE_3",
    # No physical member is universal across all disclosure forms.  Member
    # applicability is determined only after topology resolution.
    "universal_required_members": [],
    "evidence_priority": [
        "DIRECT_DISCLOSED_PORTFOLIO_TABLE",
        "DIRECT_DISCLOSED_PORTFOLIO_BLOCK",
        "CERTIFIED_STATEMENT_TO_NOTE_LINKS",
    ],
    "topologies": {
        "DIRECT_SEPARATE_TABLES_SAME_PAGE": {
            "description": "同一页的两张独立投资组合表；资产身份不得因总额相同而合并。",
            "applicable_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
            ],
            "required_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
            ],
            "reported_total_policy": "SOURCE_DISCLOSED_IF_PRESENT",
            "observed_listed_examples": ["PING_AN_2023"],
            "execution_policy": {
                "ui_route": "DIRECT_ONLY",
                "required_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "allowed_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "stage_a_review_mode": "DIRECT_SOURCE_TOPOLOGY",
                "stage_b_certification_targets": ["DIRECT_PHYSICAL_TABLE"],
                "aggregation_policy": "KEEP_PHYSICAL_TABLES_SEPARATE",
            },
        },
        "DIRECT_COMPOUND_TABLE": {
            "description": "一张物理表包含按投资对象和按会计计量两个逻辑块。",
            "applicable_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
            ],
            "required_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
            ],
            "split_reason": "CLASSIFICATION_AXIS_TRANSITION",
            "conditional_logical_members": [{
                "member_id": "portfolio_summary",
                "classification_axis": "PORTFOLIO_SUMMARY",
                "activation": "NUMERIC_PREFIX_BEFORE_FIRST_CERTIFIED_AXIS",
                "required": False,
            }],
            "reported_total_policy": "SOURCE_DISCLOSED_IF_PRESENT",
            "observed_listed_examples": [
                "CHINA_LIFE_2024",
                "CHINA_LIFE_2025",
                "CPIC_GROUP_2023",
                "CPIC_GROUP_2024",
                "CPIC_GROUP_2025",
                "NEW_CHINA_LIFE_2023",
                "NEW_CHINA_LIFE_2024",
                "NEW_CHINA_LIFE_2025",
            ],
            "execution_policy": {
                "ui_route": "DIRECT_ONLY",
                "required_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "allowed_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "stage_a_review_mode": "DIRECT_SOURCE_TOPOLOGY",
                "stage_b_certification_targets": ["DIRECT_PHYSICAL_TABLE"],
                "aggregation_policy": "ONE_PHYSICAL_TWO_LOGICAL_AXES",
            },
        },
        "DIRECT_SINGLE_AXIS_TABLE": {
            "description": "来源只披露一个投资组合分类轴；未披露轴不构成缺失。",
            "applicable_members": ["portfolio_by_category"],
            "required_members": ["portfolio_by_category"],
            "not_applicable_members": ["portfolio_by_measurement"],
            "conditional_logical_members": [{
                "member_id": "portfolio_summary",
                "classification_axis": "PORTFOLIO_SUMMARY",
                "activation": "NUMERIC_PREFIX_BEFORE_FIRST_CERTIFIED_AXIS",
                "required": False,
            }],
            "reported_total_policy": "SOURCE_DISCLOSED_IF_PRESENT",
            "observed_listed_examples": ["CHINA_LIFE_2023"],
            "execution_policy": {
                "ui_route": "DIRECT_ONLY",
                "required_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "allowed_source_kinds": ["DIRECT_PHYSICAL_TABLE"],
                "stage_a_review_mode": "DIRECT_SOURCE_TOPOLOGY",
                "stage_b_certification_targets": ["DIRECT_PHYSICAL_TABLE"],
                "aggregation_policy": "SINGLE_DISCLOSED_AXIS_NO_MISSING_AXIS",
            },
        },
        "MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL": {
            "description": "主表成员链接到多个独立附注；只保留组件集合，不伪造投资组合总额。",
            "applicable_members": ["portfolio_components"],
            "required_members": ["portfolio_components"],
            "not_applicable_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
            ],
            "reported_total_policy": "NOT_DISCLOSED_NO_SYNTHETIC_TOTAL",
            "statement_link_policy": "CERTIFIED_CHILD_TABLE_LINKS_ONLY",
            "observed_negative_controls": [
                "CPIC_LIFE_2023_DISCLOSURE_REPORT",
                "CPIC_LIFE_2024_DISCLOSURE_REPORT",
                "CPIC_LIFE_2025_DISCLOSURE_REPORT",
            ],
            "execution_policy": {
                "ui_route": "NOTE_ONLY",
                "required_source_kinds": ["NOTE_CHILD_TABLE"],
                "allowed_source_kinds": ["NOTE_CHILD_TABLE"],
                "stage_a_review_mode": "STATEMENT_TO_NOTE_COMPONENTS",
                "stage_b_certification_targets": ["NOTE_CHILD_TABLE"],
                "aggregation_policy": "KEEP_COMPONENTS_SEPARATE_NO_SYNTHETIC_TOTAL",
            },
        },
        "HYBRID_DIRECT_AND_NOTE_COMPONENTS": {
            "description": "直接组合表与附注组件并存；两种来源保持独立，禁止覆盖。",
            "applicable_members": [
                "portfolio_by_category",
                "portfolio_by_measurement",
                "portfolio_components",
            ],
            "required_members": [],
            "reported_total_policy": "DIRECT_SOURCE_TOTAL_ONLY",
            "observed_listed_examples": [],
            "execution_policy": {
                "ui_route": "HYBRID",
                "required_source_kinds": [
                    "DIRECT_PHYSICAL_TABLE",
                    "NOTE_CHILD_TABLE",
                ],
                "allowed_source_kinds": [
                    "DIRECT_PHYSICAL_TABLE",
                    "NOTE_CHILD_TABLE",
                ],
                "stage_a_review_mode": "DIRECT_AND_NOTE_SOURCE_TOPOLOGY",
                "stage_b_certification_targets": [
                    "DIRECT_PHYSICAL_TABLE",
                    "NOTE_CHILD_TABLE",
                ],
                "aggregation_policy": "DIRECT_TOTAL_NOTE_COMPONENTS_NO_DOUBLE_COUNT",
            },
        },
    },
    "physical_identity_policy": "PRESERVE_SOURCE_TABLE_AND_BLOCK_IDENTITY",
    "cross_axis_merge_policy": "FORBIDDEN",
    "cross_note_sum_policy": "FORBIDDEN_UNLESS_SOURCE_DISCLOSES_RECONCILIATION",
    "golden_policy": "VERIFY_SOURCE_FACTS_ONLY_NO_GOLDEN_BACKFILL",
}
