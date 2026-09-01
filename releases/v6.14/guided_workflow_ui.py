"""Streamlit adapter for the v6.5 guided path.

The adapter intentionally keeps planning separate from manual capture.  It only
submits a capture plan after an explicit two-stage review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from anchor_candidate_selection import candidate_label
from hierarchical_child_discovery import DISCOVERY_VERSION, StatementScopeSelection
from portfolio_topology_execution_plan import (
    DIRECT_PHYSICAL_TABLE,
    NOTE_CHILD_TABLE,
    build_portfolio_topology_execution_plan,
    certification_target_for_concept,
    evaluate_portfolio_certification_readiness,
    portfolio_topology_ui_summary,
)

EVIDENCE_LABELS = {
    "exact_parent_match": "目标父行与研究目标完全一致",
    "normalized_parent_match": "规范化后的父行名称一致",
    "formal_statement_region": "位于正式财务主报表区域",
    "statement_type_match": "主报表类型符合研究定义",
    "scope_match": "合并/公司口径符合研究定义",
    "continuous_children": "父行下方存在连续子项",
    "inline_note_references": "子项含可沿用的行内附注编号",
    "valid_note_format": "附注编号格式有效",
    "amount_completeness": "当期/对比期金额列可识别",
    "period_completeness": "期间表头完整",
    "unit_context": "单位上下文可追溯",
    "scope_context": "报表口径上下文明确",
    "column_alignment": "金额列几何对齐",
}


def _human_anchor_evidence(candidate: dict[str, Any]) -> list[dict[str, str]]:
    positive = set(candidate.get("positive_evidence") or [])
    return [
        {"人工核对点": label, "系统判断": "符合" if key in positive else "未确认"}
        for key, label in EVIDENCE_LABELS.items()
    ]


def _anchor_children(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for child in candidate.get("child_rows") or []:
        values = child.get("values")
        if values is None:
            value = child.get("value")
            values = [] if value is None else [value]
        rows.append({
            "子项": child.get("member_table") or child.get("item") or "",
            "主表金额": " / ".join(str(x) for x in values),
            "期间归属": child.get("member_period_status") or "UNRESOLVED",
            "Stage B": child.get("stage_b_eligibility") or child.get("stage_b_requirement") or "待判断",
            "附注编号": child.get("note_reference_normalized") or child.get("note_reference") or "未识别",
        })
    return rows


def _restored_anchor_default(
    ranked_rows: list[dict[str, Any]],
    preselected_ids: set[str] | list[str],
    discovery_registry: Any,
) -> str | None:
    """Restore a prior formal Anchor decision before applying score defaults.

    A rerun may reproduce the same occurrence with an optional-geometry score
    below the automatic recommendation threshold.  That must not erase an
    already persisted human/formal decision.  Candidates without a certified
    decision still follow the ranking result and remain unselected when no
    recommendation exists.
    """
    for row in ranked_rows:
        occurrence_id = str(row.get("occurrence_id") or "")
        if not occurrence_id:
            continue
        if _has_formal_anchor_certification(row, discovery_registry):
            return occurrence_id
    preselected = set(map(str, preselected_ids or []))
    return next(
        (str(row.get("occurrence_id")) for row in ranked_rows
         if str(row.get("occurrence_id")) in preselected),
        None,
    )


def _has_formal_anchor_certification(
    candidate: dict[str, Any], discovery_registry: Any,
) -> bool:
    """Check current or exact-physical append-only formal certification."""
    occurrence_id = str(candidate.get("occurrence_id") or "")
    if not occurrence_id:
        return False
    persisted = discovery_registry.get_occurrence(occurrence_id) or {}
    return bool(
        str(persisted.get("status") or "") == "ANCHOR_CERTIFIED"
        or discovery_registry.is_anchor_certified(occurrence_id)
        or (
            hasattr(discovery_registry, "is_equivalent_anchor_certified")
            and discovery_registry.is_equivalent_anchor_certified(candidate)
        )
    )


def _union_certified_links(
    current: list[dict[str, Any]],
    restored: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge fresh Stage-A results with the owner-certified inventory."""
    by_id: dict[str, dict[str, Any]] = {}
    for link in [*restored, *current]:
        certified_link_id = str(link.get("certified_link_id") or "").strip()
        if not certified_link_id:
            raise ValueError("CERTIFIED_LINK_ID_REQUIRED_FOR_STAGE_B_RESTORE")
        by_id[certified_link_id] = dict(link)
    return [by_id[key] for key in sorted(by_id)]


def _golden_anchor_family_id(
    candidate: dict[str, Any], *,
    selected_definition: dict[str, Any] | None = None,
    selected_family_id: str | None = None,
) -> str:
    """Return the unambiguous Registry family governing an Anchor Golden gate.

    The legacy Golden anchor corpus certifies financial-investment statement
    members only.  Company/year is therefore not enough to select a Golden
    contract: a portfolio disclosure from the same filing must never inherit
    the financial-investment member set.
    """
    candidate_family = str(
        candidate.get("table_family") or candidate.get("table_family_id") or ""
    ).strip()
    if candidate_family:
        return candidate_family
    if selected_family_id:
        return str(selected_family_id).strip()
    definition_payload = dict((selected_definition or {}).get("payload") or {})
    families = [str(value).strip() for value in definition_payload.get("table_families") or [] if str(value).strip()]
    return families[0] if len(families) == 1 else ""


def _render_golden_anchor_check(
    st, candidate: dict[str, Any], *,
    selected_definition: dict[str, Any] | None = None,
    selected_family_id: str | None = None,
) -> bool:
    """Show only the Registry-specific Golden gate before Anchor certification."""
    registry_family_id = _golden_anchor_family_id(
        candidate,
        selected_definition=selected_definition,
        selected_family_id=selected_family_id,
    )
    if registry_family_id == "investment_portfolio":
        from golden_acceptance import compare_portfolio_anchor
        comparison = compare_portfolio_anchor(
            str(candidate.get("company") or ""),
            str(candidate.get("report_year") or ""),
            candidate,
        )
        if comparison["status"] == "NO_GOLDEN":
            st.caption(
                "Registry=investment_portfolio：该公司/年份没有投资组合 Golden；"
                "按原 PDF 与拓扑证据审核。"
            )
            return True
        if comparison["status"] == "GOLDEN_UNAVAILABLE":
            st.warning(f"投资组合 Golden 无法读取：{comparison.get('error')}。")
            return False
        st.caption(f"投资组合独立 Golden：{comparison.get('golden_path')}")
        st.dataframe(pd.DataFrame(comparison["rows"]), use_container_width=True, hide_index=True)
        if comparison["status"] == "MISMATCH":
            st.error("投资组合物理页、披露拓扑、适用分类轴或来源披露总额不吻合；禁止认证。")
            return False
        st.success("投资组合物理表身份、拓扑、适用分类轴与来源披露总额吻合。")
        return True
    if registry_family_id != "financial_investment":
        label = registry_family_id or "当前通用发现"
        st.caption(
            f"{label} 未注册主表 Golden 成员门禁；按当前 Registry 的机器与原 PDF 证据审核。"
        )
        return True
    from golden_acceptance import compare_statement_anchor
    comparison = compare_statement_anchor(
        str(candidate.get("company") or ""),
        str(candidate.get("report_year") or ""),
        list(candidate.get("child_rows") or []),
    )
    if comparison["status"] == "NO_GOLDEN":
        st.caption("该公司/年份没有 Golden Corpus 基准；按常规人工证据审核。")
        return True
    if comparison["status"] == "GOLDEN_UNAVAILABLE":
        st.warning(f"Golden Corpus 无法读取：{comparison.get('error')}；不能将其当作验收通过。")
        return False
    st.caption(f"独立 Golden 对照：{comparison.get('golden_path')}")
    st.caption("门禁范围：仅核对当前期必需成员；比较期/历史变体保留为证据，不作为当前 Anchor 缺失项。")
    st.dataframe(pd.DataFrame(comparison["rows"]), use_container_width=True, hide_index=True)
    historical_variants = comparison.get("historical_variants") or []
    if historical_variants:
        with st.expander(f"比较期/历史变体证据（{len(historical_variants)} 项，不阻断当前期认证）", expanded=False):
            st.dataframe(pd.DataFrame(historical_variants), use_container_width=True, hide_index=True)
    if comparison["status"] == "MISMATCH":
        missing = "、".join(comparison.get("missing_current_members") or [])
        detail = f"当前期缺失或不吻合成员：{missing}。" if missing else ""
        st.error(detail + "请核对原 PDF、口径、附注号和金额后再认证；系统不会用 Golden 覆盖机器证据。")
        return False
    st.success("Golden 主表金额与附注编号全部吻合。")
    return True


def _render_golden_child_target_check(st, item: dict[str, Any], link: dict[str, Any]) -> bool:
    """Compare the selected Stage-B target page before child-link certification."""
    from golden_acceptance import compare_child_target
    anchor = item["anchor"]
    child = item["child"]
    candidate = link["candidate"]
    comparison = compare_child_target(
        str(anchor.get("company") or ""), str(anchor.get("report_year") or ""),
        # Golden page anchors certify the PDF's disclosed child-table identity.
        # Do not lead with a cross-regime canonical title here: for example,
        # the current-period source label “交易性金融资产” maps to the broader
        # fvtpl_assets concept, whose legacy canonical title is longer.  Passing
        # that legacy label creates a false Golden mismatch even when page,
        # ordinal and source heading all match.  The canonical id remains in
        # the persisted relation; this comparator is intentionally source-aware.
        member_label=str(child.get("raw_label") or child.get("item") or item["contract"].get("canonical_title") or ""),
        note_reference=str(link.get("anchor_note_reference") or child.get("note_reference_normalized") or child.get("note_reference") or ""),
        candidate_page=candidate.get("start_page"),
        candidate_heading=str(candidate.get("raw_heading") or ""),
    )
    if comparison["status"] in {"NO_GOLDEN", "NO_GOLDEN_TARGET"}:
        st.caption("该子表没有独立 Golden 目标页；按 PDF 证据审核。")
        return True
    if comparison["status"] == "GOLDEN_UNAVAILABLE":
        st.warning(f"Golden 子表基准不可读取：{comparison.get('error')}。")
        return False
    st.dataframe(pd.DataFrame([comparison]), use_container_width=True, hide_index=True)
    if comparison["status"] == "MISMATCH":
        st.error("所选子表目标页与 Golden 不吻合，必须核查原 PDF 后再认证。")
        return False
    st.success("Golden 子表目标页与身份吻合。")
    return True


def _bundle_raw_long_paths(backend, run_dir: Path, metadata: dict[str, Any]) -> list[Path]:
    """A Golden child-table check must include every audited block in a bundle."""
    bundle_id = str(metadata.get("capture_bundle_id") or "")
    if not bundle_id:
        return [run_dir / "table_raw_long.csv"]
    try:
        with backend.capture_service.repo.registry.connect() as conn:
            capture_ids = [
                str(row[0]) for row in conn.execute(
                    "SELECT capture_id FROM capture_bundle_children WHERE bundle_id=? ORDER BY child_order",
                    (bundle_id,),
                ).fetchall()
            ]
        paths = []
        for capture_id in capture_ids:
            record = backend.capture_service.get(capture_id) or {}
            candidate = Path(str(record.get("run_path") or "")) / "table_raw_long.csv"
            if candidate.is_file():
                paths.append(candidate)
        return paths or [run_dir / "table_raw_long.csv"]
    except Exception:
        return [run_dir / "table_raw_long.csv"]


def _render_golden_capture_parity(st, backend, run_dir: Path, member_table: str, source_pdf: str, metadata: dict[str, Any]) -> None:
    """Render post-capture row/cell parity where the Golden contract exists."""
    from batch_pipeline import infer_company_year
    from golden_acceptance import compare_child_capture_csv
    long_path = run_dir / "table_raw_long.csv"
    if not long_path.exists():
        return
    company, report_year = infer_company_year(Path(source_pdf or run_dir.name), "")
    comparison = compare_child_capture_csv(
        str(company or ""), str(report_year or ""),
        member_label=member_table,
        raw_long_path=_bundle_raw_long_paths(backend, run_dir, metadata),
    )
    if comparison["status"] in {"NO_GOLDEN", "NO_GOLDEN_CHILD"}:
        st.caption("该 Capture 没有子表细项 Golden，未执行数值 parity。")
        return
    if comparison["status"] == "CAPTURE_UNREADABLE":
        st.warning(f"Golden 子表数值对照不可执行：{comparison.get('error')}")
        return
    st.markdown("##### Golden 子表细项数值对照")
    st.caption(f"独立基准：{comparison.get('golden_path')}")
    st.dataframe(pd.DataFrame(comparison["rows"]), use_container_width=True, hide_index=True)
    if comparison["status"] == "MISMATCH":
        st.error("子表细项与 Golden 不吻合：该 Capture 必须核查，不应直接认证或合表。")
    else:
        st.success("Golden 子表细项当前期/比较期数值全部吻合。")


def _member_contract_for_stage_b(research_definition_service: Any, family_id: str, concept: dict[str, Any]) -> dict[str, Any]:
    """Hydrate the strict-retrieval contract from the Research Definition.

    ``raw_label`` is physical PDF evidence and can carry OCR artefacts.  The
    registry member ID is the stable semantic identity for Stage B matching.
    Keep the source label as a bounded fallback only.
    """
    member_id = str(concept.get("canonical_concept_id") or "")
    registry_member = next(
        (
            member
            for member in research_definition_service.members(str(family_id or ""))
            if str(member.get("member_id") or "") == member_id
        ),
        None,
    )
    payload = dict((registry_member or {}).get("payload") or {})
    canonical_title = str(
        (registry_member or {}).get("display_name")
        or concept.get("canonical_display_name")
        or concept.get("raw_label")
        or member_id
    )
    aliases = list(dict.fromkeys([
        canonical_title,
        *(payload.get("aliases") or []),
        *(concept.get("concept_aliases") or []),
        str(concept.get("raw_label") or ""),
    ]))
    return {
        "member_table_id": member_id or str(concept.get("raw_label") or ""),
        "canonical_title": canonical_title,
        "exact_aliases": [item for item in aliases if item],
        "certified_company_aliases": [],
        "direct_main_statement": bool(payload.get("direct_main_statement")),
        "direct_portfolio_table": bool(
            concept.get("direct_portfolio_table")
            or (concept.get("inline_note_reference_evidence") or {}).get("direct_portfolio_table")
        ),
        "physical_asset_id": str(
            concept.get("physical_asset_id")
            or (concept.get("inline_note_reference_evidence") or {}).get("physical_asset_id")
            or ""
        ),
        "logical_block_id": str(
            concept.get("logical_block_id")
            or (concept.get("inline_note_reference_evidence") or {}).get("logical_block_id")
            or ""
        ),
        "classification_axis": str(
            concept.get("classification_axis")
            or (concept.get("inline_note_reference_evidence") or {}).get("classification_axis")
            or ""
        ),
        "portfolio_source_kind": str(
            concept.get("portfolio_source_kind")
            or (concept.get("inline_note_reference_evidence") or {}).get("portfolio_source_kind")
            or ""
        ),
    }


def _portfolio_plan_for_occurrence(
    occurrence: dict[str, Any],
) -> dict[str, Any] | None:
    if str(
        occurrence.get("table_family")
        or occurrence.get("table_family_id")
        or ""
    ) != "investment_portfolio":
        return None
    return build_portfolio_topology_execution_plan(occurrence)


def _portfolio_stage_action(
    occurrences: list[dict[str, Any]],
) -> dict[str, Any]:
    plans = [
        plan for plan in (
            _portfolio_plan_for_occurrence(row) for row in occurrences
        ) if plan
    ]
    if not plans:
        return {
            "is_portfolio": False,
            "stage_a_button": "② 认证所选 Anchor 并解析附注目标",
            "stage_b_heading": "阶段 B：认证附注目标",
            "routes": [],
        }
    summaries = [portfolio_topology_ui_summary(plan) for plan in plans]
    routes = sorted({row["route"] for row in summaries})
    if routes == ["DIRECT_ONLY"]:
        button = "② 认证所选投资组合来源并生成直接物理表 Stage B 目标"
        heading = "阶段 B：认证直接物理表 ROI 与逻辑分块"
    elif routes == ["NOTE_ONLY"]:
        button = "② 认证所选投资组合来源并解析附注组件"
        heading = "阶段 B：认证附注组件子表链接"
    else:
        button = "② 认证所选投资组合来源并生成 Direct + Note Stage B 目标"
        heading = "阶段 B：分别认证直接物理表与附注组件"
    return {
        "is_portfolio": True,
        "stage_a_button": button,
        "stage_b_heading": heading,
        "routes": routes,
        "plans": plans,
        "summaries": summaries,
    }


def _guided_discovery_context_identity(
    selected_definition: dict[str, Any] | None,
    selected_pdfs: list[Path],
    requested_scope: str,
    selected_family_id: str | None,
) -> tuple[str, str, tuple[str, ...], str]:
    return (
        str((selected_definition or {}).get("definition_id") or ""),
        str(selected_family_id or ""),
        tuple(sorted(str(Path(path)) for path in selected_pdfs)),
        str(requested_scope or ""),
    )


def _effective_guided_definition(
    selected_definition: dict[str, Any] | None,
    selected_family_id: str | None,
    research_definition_service: Any,
) -> tuple[dict[str, Any] | None, str]:
    """Route new portfolio knowledge-package work to the current V2 Definition."""
    if selected_definition or str(selected_family_id or "") != "investment_portfolio":
        return selected_definition, ""
    current = research_definition_service.definition("INVESTMENT_PORTFOLIO_V2")
    if not current or str(current.get("status") or "") != "ACTIVE":
        raise PermissionError("INVESTMENT_PORTFOLIO_V2_ACTIVE_DEFINITION_REQUIRED")
    payload = dict(current.get("payload") or {})
    if payload.get("selection_status") == "LEGACY_COMPATIBILITY":
        raise PermissionError("INVESTMENT_PORTFOLIO_V2_CURRENT_DEFINITION_REQUIRED")
    return current, "KNOWLEDGE_PACKAGE_ROUTED_TO_INVESTMENT_PORTFOLIO_V2"


def _clear_stale_guided_discovery_state(
    session_state: Any,
    identity: tuple[str, str, tuple[str, ...], str],
) -> bool:
    key = "v613_guided_discovery_context_identity"
    previous = session_state.get(key)
    session_state[key] = identity
    if previous in (None, identity):
        return False
    for stale_key in (
        "v65_raw_discovery", "v65_clusters", "v65_occurrences", "v613_discovery_failures",
        "v66_resolved_occurrences", "v651_certified_occurrence_ids",
        "v66_certified_plans", "v66_research_batch_id",
        "v610_child_mappings", "v610_certified_child_links",
        "v613_portfolio_execution_plans",
    ):
        session_state.pop(stale_key, None)
    return True


def _guided_discovery_failure_rows(
    pdf_path: Path,
    dimensions: dict[str, Any],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project per-PDF discovery failures for the UI without changing evidence."""
    rows = []
    for failure in result.get("failures") or []:
        audit = dict(
            failure.get("portfolio_topology_audit")
            or failure.get("ocr_audit")
            or {}
        )
        rows.append({
            "source_pdf": Path(pdf_path).name,
            "company": str(dimensions.get("company") or ""),
            "report_year": str(dimensions.get("year") or ""),
            "family_id": str(failure.get("family_id") or ""),
            "failure_reason": str(failure.get("failure_reason") or "DISCOVERY_FAILED"),
            "strategy": str(audit.get("strategy") or ""),
            "native_pages_scanned": audit.get("native_pages_scanned"),
            "ocr_used": bool(audit.get("ocr_used")),
        })
    return rows


def _stage_b_amount_caption(child: dict[str, Any]) -> str:
    certified = child.get("statement_amount_normalized") or child.get("statement_amount_raw") or []
    if certified:
        return f"主表认证金额 {certified}"
    evidence = dict(child.get("inline_note_reference_evidence") or {})
    ocr_candidates = evidence.get("ocr_amount_candidates") or child.get("ocr_amount_candidates") or []
    if ocr_candidates:
        return f"主表 OCR 数值候选 {ocr_candidates}（仅供定位，不参与认证/勾稽）"
    return "主表认证金额未取得"


def _stage_b_actionable_inventory_mappings(
    backend: Any,
    mappings: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Return only mappings that still have real OPEN/UNRESOLVED cases."""
    actionable: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for item in mappings:
        child = dict(item.get("child") or {})
        cases = backend.child_discovery_repository.unresolved_inventory_cases(
            anchor_child_id=child.get("anchor_child_id"),
        )
        if cases:
            actionable.append((item, cases))
    return actionable


def _safe_pdf_page(value: Any) -> int | None:
    """Accept legacy SQLite NULL/NaN values without pretending they are pages."""
    if value is None or pd.isna(value):
        return None
    try:
        page = int(float(value))
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _show_pdf_preview(container, preview: dict[str, Any], label: str) -> bool:
    """Render review evidence without letting a bad PDF/page crash Streamlit."""
    if preview.get("status") != "OK" or not preview.get("png"):
        container.warning(
            f"{label}不可用：{preview.get('error') or preview.get('status') or 'UNKNOWN_PREVIEW_ERROR'}"
        )
        return False
    container.caption(
        f"{label}：PDF {preview['pdf_page_index']}（印刷页 "
        f"{preview.get('printed_page') or '未识别'}）· "
        f"{preview.get('evidence_level') or 'UNAVAILABLE'}"
    )
    container.image(preview["png"], use_container_width=True)
    return True


def _resolve_pdf_path(record: dict[str, Any], backend=None) -> Path | None:
    """Resolve a filesystem path even when the stored PDF identity is opaque."""
    for raw in (
        record.get("pdf_path"),
        record.get("source_pdf"),
        record.get("source_pdf_path"),
        record.get("pdf_id"),
    ):
        value = str(raw or "").strip()
        if value.lower().startswith("pdf::"):
            value = value[5:]
        candidate = Path(value) if value else None
        if candidate and candidate.is_file():
            return candidate
    pdf_id = str(record.get("pdf_id") or "")
    if backend is not None and pdf_id:
        for asset in backend.pdf_service.list(limit=5000):
            if str(asset.get("pdf_id") or "") == pdf_id:
                candidate = Path(str(asset.get("path") or ""))
                if candidate.is_file():
                    return candidate
    return None


def render_guided_capture(st, backend, selected_pdfs: list[Path], infer_dimensions) -> None:
    st.subheader("研究引导抓取：发现 → 审核 → 认证计划 → 一键抓取")
    st.caption("该路径只输入一次研究目标；认证后不再重复选择目标表或表族。手工抓取在下方高级区独立保留。")
    definitions = backend.research_definition_service.definitions() if hasattr(backend, "research_definition_service") else []
    definition_map = {"（不使用 Registry，临时自由输入）": None} | {f"{x['display_name']} · {x['definition_version']}": x for x in definitions}
    definition_label = st.selectbox("Research Definition（推荐，可复现）", list(definition_map), key="v67_definition_select")
    selected_definition = definition_map[definition_label]
    default_name = selected_definition["display_name"] if selected_definition else ""
    # Streamlit keeps a widget's value by key.  Reusing the manual-input key
    # meant switching to a Registry definition could leave the field visually
    # blank and keep the Discovery button disabled, despite a valid definition
    # being selected.  Give each definition an independent input state so its
    # registered display name is both visible and actually submitted.
    display_name_key = "v65_display_name_manual"
    if selected_definition:
        display_name_key = f"v65_display_name_definition_{selected_definition['definition_id']}"
    display_name = st.text_input(
        "研究目标 / display_name", value=default_name,
        placeholder="例如：金融投资、保险合同负债、投资收益", key=display_name_key,
    )
    scope_label=st.radio(
        "财务报表口径",
        ["合并财务报表（默认）","母公司财务报表","两者都需要"],
        horizontal=True,key="v610_scope_selector",
    )
    requested_scope={
        "合并财务报表（默认）":"CONSOLIDATED",
        "母公司财务报表":"PARENT_COMPANY",
        "两者都需要":"BOTH",
    }[scope_label]
    requested_scope_lanes=(
        ["CONSOLIDATED","PARENT_COMPANY"] if requested_scope=="BOTH"
        else [requested_scope]
    )
    families = backend.research_definition_service.families() if hasattr(backend, "research_definition_service") else []
    knowledge_map = {"（无知识包，纯通用发现）": None} | {
        f"{family['display_name']} · {family['definition_version']}": family["family_id"]
        for family in families
    }
    knowledge_label = st.selectbox(
        "可选 Registry 知识包", list(knowledge_map), key="v68_knowledge_package",
        disabled=selected_definition is not None,
        help="知识包只从 Registry 提供不可变词表；选择 Research Definition 时由定义直接固定发现策略。",
    )
    selected_family_id = knowledge_map[knowledge_label]
    selected_definition, definition_route = _effective_guided_definition(
        selected_definition,
        selected_family_id,
        backend.research_definition_service,
    )
    if selected_definition and not display_name.strip():
        # The knowledge-package selector appears after the display-name widget.
        # When it upgrades a legacy family selection to V2 in this rerun, use
        # the immutable Definition label immediately instead of leaving the
        # Discovery button disabled until another rerun.
        display_name = str(selected_definition.get("display_name") or "").strip()
    if definition_route:
        st.info(
            "投资组合新任务已从可选知识包自动路由到 INVESTMENT_PORTFOLIO_V2；"
            "V1 仅保留历史兼容，不再用于新 Discovery。"
        )
    current_identity = _guided_discovery_context_identity(
        selected_definition,
        selected_pdfs,
        requested_scope,
        selected_family_id,
    )
    if _clear_stale_guided_discovery_state(st.session_state, current_identity):
        st.info("Research Definition、PDF 或口径已改变；旧 Discovery/Stage A/Stage B 的 UI 临时结果已清除，请重新发现。")
    if selected_definition:
        selected_payload = dict(selected_definition.get("payload") or {})
        topology_version = dict(selected_payload.get("research_scope") or {}).get(
            "portfolio_topology_contract_version"
        )
        st.caption(
            f"当前 Registry：{selected_definition.get('definition_id')} · "
            f"{selected_definition.get('definition_version')}"
            + (f" · {topology_version}" if topology_version else "")
        )
    if st.button("① 发现主报表 occurrence 与附注候选", key="v65_discover", disabled=not selected_pdfs or not display_name.strip()):
        # A new discovery invalidates every downstream UI artifact from the
        # previous run.  Keeping an old Stage-B occurrence is what previously
        # caused UNSELECTED_ANCHOR_NEVER_MATERIALIZES.
        for key in (
            "v66_resolved_occurrences","v651_certified_occurrence_ids",
            "v66_certified_plans","v66_research_batch_id",
            "v613_portfolio_execution_plans",
        ):
            st.session_state.pop(key,None)
        raw: list[dict[str, Any]] = []
        direct_occurrences = []
        discovery_failures: list[dict[str, Any]] = []
        for pdf in selected_pdfs:
            dim = infer_dimensions(pdf)
            backend.child_discovery_repository.save_scope(StatementScopeSelection.new(
                str(pdf),requested_scope,
                research_definition_id=str((selected_definition or {}).get("definition_id") or ""),
                selection_source="USER_SELECTED",selected_by="USER",
                evidence={"ui":"Research-Guided Capture"},
            ))
            if selected_definition:
                result = backend.generic_discovery_service.discover(pdf_path=pdf, definition_id=selected_definition["definition_id"], company=dim["company"], report_year=dim["year"])
                discovery_failures.extend(_guided_discovery_failure_rows(pdf, dim, result))
                saved_candidates = []
                saved_by_source_id = {}
                for candidate in result["candidates"]:
                    source_id = str(candidate.get("discovery_id") or "")
                    saved = backend.discovery_registry.save_machine(
                        dict(candidate) | {"pdf_id": str(pdf)}
                    )
                    candidate.update(saved)
                    saved_candidates.append(candidate)
                    if source_id:
                        saved_by_source_id[source_id] = saved
                raw.extend(saved_candidates)
                for occurrence in result["occurrences"]:
                    context = dict(occurrence) | {"pdf_id": str(pdf)}
                    saved = saved_by_source_id.get(str(occurrence.get("discovery_id") or ""))
                    if saved:
                        context["discovery_id"] = saved["discovery_id"]
                        if saved.get("machine_evidence_revision"):
                            context["machine_evidence_revision"] = saved["machine_evidence_revision"]
                    direct_occurrences.append(backend.discovery_service.build_occurrence(context=context, parent_text=occurrence["parent_text"], child_rows=occurrence["child_rows"], source_table_title=occurrence["source_table_title"], scope=occurrence.get("scope", "UNKNOWN")))
            else:
                discovery_context = (
                    backend.research_definition_service.family_discovery_context(selected_family_id)
                    if selected_family_id else {}
                )
                raw.extend(backend.discovery_service.preview(
                    pdf, display_name=display_name.strip(), company=dim["company"],
                    report_year=dim["year"], discovery_context=discovery_context,
                ))
        st.session_state["v65_raw_discovery"] = raw
        st.session_state["v65_clusters"] = backend.discovery_service.cluster(raw)
        st.session_state["v65_occurrences"] = direct_occurrences or backend.discovery_service.proposed_occurrences(raw)
        st.session_state["v613_discovery_failures"] = discovery_failures
    clusters = st.session_state.get("v65_clusters", [])
    occurrences = st.session_state.get("v65_occurrences", [])
    discovery_failures = st.session_state.get("v613_discovery_failures", [])
    if discovery_failures:
        st.warning(
            f"有 {len(discovery_failures)} 个 PDF/Registry 发现项未进入阶段 A；"
            "请按文件名核对是否选择了正确的上市母公司年报。"
        )
        st.dataframe(pd.DataFrame(discovery_failures), use_container_width=True, hide_index=True)
    if not clusters and not occurrences:
        return
    workflow_action = _portfolio_stage_action(occurrences)
    st.markdown("#### 阶段 A：审核抓什么（已先按证据聚类）")
    if workflow_action["is_portfolio"]:
        st.caption(
            "投资组合 UI 与离线管道共用五拓扑执行计划；Direct 来源审核物理表，"
            "Note 来源审核附注链接，Hybrid 在同一 filing 内同时保留两类目标。"
        )
    if clusters:
        table = pd.DataFrame(clusters)
        cols = [c for c in ["candidate_cluster_id", "company", "report_year", "display_name", "statement_type", "scope", "disclosure_topology", "portfolio_source_kind", "member_table", "statement_pdf_page_index", "candidate_note_pdf_page_index", "note_reference_normalized", "confidence", "evidence_count"] if c in table]
        st.dataframe(table[cols], use_container_width=True, hide_index=True)
    else:
        table = pd.DataFrame()
    if occurrences:
        st.caption(
            "发现、推荐、预选与认证严格分离；每份 PDF、每个口径最多推荐一个来源 occurrence，"
            "只有点击确认后才认证。"
            if workflow_action["is_portfolio"] else
            "发现、推荐、预选与认证严格分离；每份 PDF、每个口径最多推荐一个 Anchor，只有点击确认后才认证。"
        )
        definition_scope=requested_scope_lanes[0] if len(requested_scope_lanes)==1 else ""
        ranked=backend.discovery_service.rank_anchor_candidates(
            occurrences,scope_preference=definition_scope or None,
            required_scopes=requested_scope_lanes,
        )
        recovery_audit = dict(ranked.get("recovery_audit") or {})
        if recovery_audit.get("attempts"):
            attempts = list(recovery_audit.get("attempts") or [])
            st.info(
                "V2 证据恢复｜阶段=" + str(recovery_audit.get("recovery_stage") or "NATIVE_DISCOVERY")
                + "；" + ("结果=" + str(recovery_audit.get("final_status")) if recovery_audit.get("final_status") else "仅补全候选页证据")
            )
            st.dataframe(pd.DataFrame([
                {"阶段": item.get("recovery_stage"), "OCR 页": ",".join(map(str, item.get("ocr_pages") or [])),
                 "缓存命中": item.get("ocr_cache_hits"), "缓存未命中": item.get("ocr_cache_misses"),
                 "状态": item.get("final_status")}
                for item in attempts
            ]), use_container_width=True, hide_index=True)
        ranked_by_id={row["occurrence_id"]:row for row in ranked["candidates"]}
        groups:dict[tuple[str,str],list[dict[str,Any]]]={}
        for row in ranked["candidates"]:
            key=(str(row.get("pdf_id") or ""),str(row.get("scope") or "UNKNOWN"))
            groups.setdefault(key,[]).append(row)
        selected_occurrence_ids=[]
        for group_index,((pdf_id,scope),rows) in enumerate(groups.items()):
            first=rows[0]
            st.markdown(
                f"**{first.get('company') or Path(pdf_id).stem}｜{first.get('report_year') or '-'}｜"
                f"{scope}**"
            )
            label_map={candidate_label(row):row["occurrence_id"] for row in rows}
            options=["不选择（需要人工判断）"]+list(label_map)
            recommended = _restored_anchor_default(
                rows,
                ranked["preselected_ids"],
                backend.discovery_registry,
            )
            recommended_label=next((label for label,oid in label_map.items() if oid==recommended),None)
            choice=st.radio(
                "选择本口径投资组合来源" if workflow_action["is_portfolio"] else "选择本口径主报表 Anchor",options,
                index=options.index(recommended_label) if recommended_label else 0,
                key=f"v69_anchor_choice_{group_index}_{abs(hash((pdf_id,scope)))}",
            )
            if choice!="不选择（需要人工判断）":
                selected_occurrence_ids.append(label_map[choice])
                selected=ranked_by_id[label_map[choice]]
                st.markdown("##### 人工判断依据")
                evidence_cols=st.columns([1.15,1])
                pdf=_resolve_pdf_path(selected,backend)
                page=_safe_pdf_page(selected.get("statement_pdf_page_index"))
                if pdf and page:
                    from pdf_evidence import page_preview
                    preview=page_preview(
                        pdf,page-1,
                        [str(selected.get("display_name") or "")]+[
                            str(x.get("item") or x.get("member_table") or "")
                            for x in selected.get("child_rows") or []
                        ],
                    )
                    _show_pdf_preview(evidence_cols[0],preview,"候选主报表原页")
                else:
                    evidence_cols[0].warning("没有可显示的主报表原页；请勿仅凭评分认证。")
                with evidence_cols[1]:
                    st.write(
                        f"**{selected.get('source_table_title') or '未知主表'}**  "
                        f"PDF {page or '未识别'} 页 · {selected.get('scope') or 'UNKNOWN'}"
                    )
                    anchor_v2 = dict(selected.get("evidence") or {})
                    if anchor_v2.get("schema_version") == "STATEMENT_ANCHOR_EVIDENCE_V2":
                        st.caption(
                            "V2 来源证据｜"
                            f"scope={anchor_v2.get('source_statement_scope')} "
                            f"({anchor_v2.get('scope_evidence_source')}, {anchor_v2.get('scope_confidence')})｜"
                            f"物理页组={anchor_v2.get('physical_page_group')}｜单位={anchor_v2.get('unit') or '未识别'}｜"
                            f"恢复={anchor_v2.get('recovery_stage')}｜几何={anchor_v2.get('geometry_evidence_mode')}"
                        )
                        st.caption(
                            f"列报制度={anchor_v2.get('presentation_regime') or 'UNKNOWN'}｜"
                            f"当前期必需成员={anchor_v2.get('required_current_members') or []}｜"
                            f"比较期/历史成员={anchor_v2.get('comparative_only_members') or []}"
                        )
                        st.dataframe(pd.DataFrame(anchor_v2.get("period_columns") or []), use_container_width=True, hide_index=True)
                        st.dataframe(pd.DataFrame([
                            {"成员": item.get("member_table"),
                             "披露成员": item.get("presentation_member_id") or item.get("member_table"),
                             "来源行": item.get("raw_label"),
                             "身份来源": item.get("identity_source"), "数值来源": item.get("value_source"),
                             "期间归属": item.get("member_period_status"),
                             "制度": item.get("presentation_regime"),
                             "分析桥接组": " / ".join(
                                 str(group.get("analysis_bridge_group") or "")
                                 for group in item.get("analysis_bridge_groups") or []
                             ),
                             "可比性": item.get("comparability_status"),
                             "父项关系": item.get("parent_relation"), "附注": item.get("note_reference") or "未解析",
                             "附注状态": item.get("note_reference_status"), "金额单元格数": len(item.get("amount_cells") or []),
                             "对齐": (item.get("alignment_evidence") or {}).get("status"),
                             "纵向重叠": (item.get("alignment_evidence") or {}).get("vertical_overlap_ratio")}
                            for item in anchor_v2.get("members") or []
                        ]), use_container_width=True, hide_index=True)
                        if anchor_v2.get("scope_conflict_reason"):
                            st.warning("来源 scope 冲突：" + str(anchor_v2["scope_conflict_reason"]))
                        if anchor_v2.get("native_ocr_conflicts"):
                            st.error("原生/OCR 证据冲突，已按 fail-closed 阻断：" + str(anchor_v2["native_ocr_conflicts"]))
                        with st.expander("V2 拓扑与缓存审计", expanded=False):
                            st.write({
                                "selected_topology_id": anchor_v2.get("selected_topology_id"),
                                "page_cache_identity": anchor_v2.get("page_cache_identity"),
                                "period_geometry_verified": anchor_v2.get("period_geometry_verified"),
                                "note_geometry_verified": anchor_v2.get("note_geometry_verified"),
                                "row_binding_verified": anchor_v2.get("row_binding_verified"),
                                "value_geometry_verified": anchor_v2.get("value_geometry_verified"),
                                "geometry_source": anchor_v2.get("geometry_source"),
                            })
                            st.dataframe(pd.DataFrame(anchor_v2.get("topology_hypotheses") or []), use_container_width=True, hide_index=True)
                    child_rows=_anchor_children(selected)
                    if child_rows:
                        st.dataframe(pd.DataFrame(child_rows),use_container_width=True,hide_index=True)
                    else:
                        st.warning("未识别父行下的连续子项。")
                    st.dataframe(
                        pd.DataFrame(_human_anchor_evidence(selected)),
                        use_container_width=True,hide_index=True,
                    )
                    golden_ok = _render_golden_anchor_check(
                        st,
                        selected,
                        selected_definition=selected_definition,
                        selected_family_id=selected_family_id,
                    )
                    st.session_state[f"v611_golden_anchor_ok_{selected['occurrence_id']}"] = golden_ok
                with st.expander("高级信息：机器评分、门禁和算法版本",expanded=False):
                    formal_anchor_certified = _has_formal_anchor_certification(
                        selected, backend.discovery_registry,
                    )
                    st.write(
                        f"总分：{selected['total_score']:.2f}；门禁："
                        f"{'全部通过' if selected['hard_gates_passed'] else ('正式认证已恢复（机器门禁未全通过）' if formal_anchor_certified else '未通过')}；"
                        f"排序版本：{selected['ranking_version']}"
                    )
                    st.dataframe(pd.DataFrame([
                        {"机器特征":name,"权重":value}
                        for name,value in selected["score_components"].items() if value
                    ]),use_container_width=True,hide_index=True)
                    failed=[name for name,passed in selected["hard_gate_results"].items() if not passed]
                    if failed and formal_anchor_certified:
                        st.warning(
                            "机器门禁未全通过（"+"、".join(failed)+
                            "）；已按同一 PDF、页码、口径和表族的正式认证决定恢复，"
                            "该信息仅作审计提示。"
                        )
                    elif failed:
                        st.error("未通过硬门禁："+"、".join(failed))
            elif ranked["scope_decisions"].get(f"{pdf_id}::{scope}",{}).get("status")=="ANCHOR_SELECTION_REQUIRED":
                st.warning("候选分数不足、差距过小或证据冲突：需要人工选择，不会自动认证。")
        override_reason=st.text_input(
            "选择非推荐 Anchor 时的原因（可选）",
            key="v69_anchor_override_reason",
            placeholder="例如：研究任务要求母公司口径；推荐页为摘要表。",
        )
    else:
        ranked={"candidates":[],"preselected_ids":[]}
        ranked_by_id={}
        override_reason=""
        selected_occurrence_ids = []
    selected_workflow_action = _portfolio_stage_action([
        ranked_by_id[occurrence_id]
        for occurrence_id in selected_occurrence_ids
        if occurrence_id in ranked_by_id
    ])
    if selected_workflow_action["is_portfolio"]:
        for summary in selected_workflow_action["summaries"]:
            st.dataframe(pd.DataFrame([{
                "拓扑": summary["topology"],
                "UI 路由": summary["route"],
                "直接物理表": summary["direct_target_count"],
                "附注组件": summary["note_target_count"],
                "逻辑分块": summary["logical_block_count"],
                "汇总政策": summary["aggregation_policy"],
                "计划状态": summary["readiness"],
            }]), use_container_width=True, hide_index=True)
            if summary["blocking_issue_codes"]:
                st.error("拓扑执行计划未就绪：" + "、".join(summary["blocking_issue_codes"]))
        for plan in selected_workflow_action["plans"]:
            review_rows = []
            for target in plan["direct_targets"]:
                review_rows.append({
                    "认证目标": "直接物理表",
                    "物理资产 ID": target["physical_asset_id"],
                    "PDF 页": target["page"],
                    "bbox": target["bbox"],
                    "成员": " / ".join(target["member_table_ids"]),
                    "逻辑分块": " / ".join(target["logical_block_ids"]),
                    "分类轴": " / ".join(target["classification_axes"]),
                })
            for target in plan["note_targets"]:
                review_rows.append({
                    "认证目标": "附注组件",
                    "物理资产 ID": "-",
                    "PDF 页": "待 Stage B 确认",
                    "bbox": "待 Stage B 确认",
                    "成员": " / ".join(target["member_table_ids"]),
                    "逻辑分块": target["target_id"],
                    "分类轴": "COMPONENT_SOURCE",
                })
            if review_rows:
                st.caption("Stage B 将逐项认证以下物理来源；此预览不写入业务状态。")
                st.dataframe(pd.DataFrame(review_rows), use_container_width=True, hide_index=True)
    certify_button_label = (
        selected_workflow_action["stage_a_button"]
        if selected_workflow_action["is_portfolio"]
        else "② 认证所选 Anchor 并解析附注目标"
    )
    if st.button(certify_button_label, key="v66_certify_anchors", disabled=not selected_occurrence_ids):
        chosen_occurrences = [o for o in occurrences if o["occurrence_id"] in selected_occurrence_ids]
        certified_occurrences = []
        for occurrence_id in selected_occurrence_ids:
            candidate=ranked_by_id[occurrence_id]
            golden_ok = st.session_state.get(f"v611_golden_anchor_ok_{occurrence_id}")
            if golden_ok is False:
                st.error(f"{candidate.get('company')} {candidate.get('report_year')} 与 Golden 不吻合，已阻止自动认证；请先核查。")
                continue
            recommended=occurrence_id in ranked["preselected_ids"]
            alternatives=[{
                "occurrence_id":x["occurrence_id"],"score":x["total_score"],
                "scope":x.get("scope"),"page":x.get("statement_pdf_page_index"),
            } for x in ranked["candidates"] if x["occurrence_id"]!=occurrence_id]
            backend.discovery_service.adjudicate_anchor(
                occurrence_id,label="ACCEPTED",chosen_scope=str(candidate.get("scope") or ""),
                reason="确认系统推荐" if recommended else override_reason.strip(),
                override={
                    "selection_method":"HUMAN_CONFIRMED_RECOMMENDATION" if recommended else "HUMAN_OVERRIDE",
                    "recommended_candidate_id":occurrence_id if recommended else next(iter(ranked["preselected_ids"]),None),
                    "selected_candidate_id":occurrence_id,
                    "candidate_score":candidate["total_score"],
                    "score_evidence_snapshot":{
                        "score_components":candidate["score_components"],
                        "hard_gate_results":candidate["hard_gate_results"],
                        "ranking_version":candidate["ranking_version"],
                        "statement_anchor_evidence_v2":dict(candidate.get("evidence") or {}) if
                            (candidate.get("evidence") or {}).get("schema_version")=="STATEMENT_ANCHOR_EVIDENCE_V2" else None,
                    },
                    "alternative_candidates":alternatives,
                    "override_reason":"" if recommended else override_reason.strip(),
                },
            )
            certified=backend.discovery_registry.get_occurrence(occurrence_id)
            if certified and (
                certified.get("status")=="ANCHOR_CERTIFIED"
                or backend.discovery_registry.is_anchor_certified(occurrence_id)
            ):
                certified_occurrences.append(certified)
        # Persist only the anchor decision here.  Note candidates remain
        # non-executable until the user confirms a concrete target below.
        chosen_by_id={x["occurrence_id"]:x for x in chosen_occurrences}
        resolved_occurrences = []
        for row in certified_occurrences:
            hydrated = {
                **row,
                "pdf_id": chosen_by_id.get(row["occurrence_id"], {}).get("pdf_id") or row.get("pdf_id"),
                "child_rows": chosen_by_id.get(row["occurrence_id"], {}).get("child_rows") or row.get("child_rows") or [],
            }
            plan = _portfolio_plan_for_occurrence(hydrated)
            if plan and plan["readiness"] != "READY_FOR_STAGE_A_REVIEW":
                st.error(
                    f"{hydrated.get('company')} {hydrated.get('report_year')} 拓扑执行计划未就绪："
                    + "、".join(plan["blocking_issue_codes"])
                )
                continue
            resolved_occurrences.append(
                backend.discovery_service.resolve_note_targets(hydrated)
            )
        st.session_state["v66_resolved_occurrences"] = resolved_occurrences
        st.session_state["v651_certified_occurrence_ids"] = [
            x["occurrence_id"] for x in certified_occurrences
        ]
        st.session_state.pop("v66_certified_plans",None)
        v610_mappings=[]
        auto_certified_links=[]
        portfolio_execution_plans={}
        for row in certified_occurrences:
            source=Path(str(row.get("pdf_id") or ""))
            if not source.is_file():continue
            chosen=chosen_by_id.get(row["occurrence_id"],{})
            anchor={**row,"child_rows":chosen.get("child_rows") or row.get("child_rows") or []}
            anchor_scope=str(anchor.get("scope") or "")
            if anchor_scope not in requested_scope_lanes:
                if len(requested_scope_lanes)!=1:
                    st.error("认证 Anchor 的口径无法映射到所选双口径 lane；请返回阶段 A 重新认证。")
                    continue
                anchor_scope=requested_scope_lanes[0]
                anchor["scope"]=anchor_scope
            concepts=backend.child_discovery_repository.create_anchor_children(
                anchor,
                research_definition_id=str((selected_definition or {}).get("definition_id") or ""),
                definition_version=str((selected_definition or {}).get("definition_version") or ""),
            )
            portfolio_plan = _portfolio_plan_for_occurrence({
                **anchor,
                "child_rows": concepts,
            })
            if portfolio_plan:
                portfolio_execution_plans[anchor["occurrence_id"]] = portfolio_plan
                if portfolio_plan["readiness"] != "READY_FOR_STAGE_A_REVIEW":
                    st.error(
                        "投资组合拓扑执行计划未就绪："
                        + "、".join(portfolio_plan["blocking_issue_codes"])
                    )
                    continue
            links_by_child={}
            certified_portfolio_physical_ids=set()
            for concept in concepts:
                contract=_member_contract_for_stage_b(
                    backend.research_definition_service,
                    str(anchor.get("table_family") or ""),
                    concept,
                )
                certification_target = (
                    certification_target_for_concept(portfolio_plan, concept)
                    if portfolio_plan else None
                )
                if portfolio_plan and not certification_target:
                    st.error(
                        "投资组合成员没有对应的拓扑认证目标："
                        f"{concept.get('canonical_concept_id') or concept.get('raw_label')}"
                    )
                    continue
                if certification_target:
                    contract.update({
                        "portfolio_source_kind": certification_target["source_kind"],
                        "physical_asset_id": certification_target.get("physical_asset_id"),
                        "member_table_ids": list(
                            certification_target.get("member_table_ids") or []
                        ),
                        "logical_block_ids": list(
                            certification_target.get("logical_block_ids") or []
                        ),
                        "classification_axes": list(
                            certification_target.get("classification_axes") or []
                        ),
                        "conditional_logical_members": list(
                            certification_target.get("conditional_logical_members") or []
                        ),
                        "period_labels": list(
                            (concept.get("inline_note_reference_evidence") or {}).get(
                                "period_headers"
                            ) or []
                        ),
                    })
                if contract.get("direct_portfolio_table") or (
                    certification_target
                    and certification_target["source_kind"] == DIRECT_PHYSICAL_TABLE
                ):
                    physical_asset_id=str(contract.get("physical_asset_id") or "")
                    if physical_asset_id in certified_portfolio_physical_ids:
                        continue
                    try:
                        auto_certified_links.append(
                            backend.child_discovery_repository
                            .certify_direct_portfolio_table(anchor,concept,contract)
                        )
                        certified_portfolio_physical_ids.add(physical_asset_id)
                    except Exception as exc:
                        st.error(
                            "投资组合直接披露表 CertifiedChildTableLink 生成失败："
                            f"{type(exc).__name__}: {exc}"
                        )
                    continue
                if contract.get("direct_main_statement"):
                    try:
                        auto_certified_links.append(
                            backend.child_discovery_repository
                            .certify_direct_main_statement(anchor,concept,contract)
                        )
                    except Exception as exc:
                        st.error(
                            "主表整表 CertifiedChildTableLink 生成失败："
                            f"{type(exc).__name__}: {exc}"
                        )
                    continue
                found=backend.hierarchical_child_discovery_service.discover(
                    source,anchor,concept,contract,anchor_scope,
                )
                enriched=backend.hierarchical_child_discovery_service.enrich_top_k(
                    source,concept,found["candidates"],contract,
                )
                links=backend.hierarchical_child_discovery_service.link_candidates(
                    anchor,concept,enriched,contract,
                )
                links_by_child[concept["anchor_child_id"]]=links
                v610_mappings.append({
                    "anchor":anchor,"child":concept,"contract":contract,
                    "run":found["run"],"links":links,"pdf_path":str(source),
                })
            assignment=backend.hierarchical_child_discovery_service.assign_global(
                anchor["occurrence_id"],anchor_scope,
                links_by_child,
            )
            auto_certified_links.extend(
                assignment.get("certified_links") or []
            )
            restored_links = (
                backend.child_discovery_repository.certified_links_for_anchor(
                    str(anchor["occurrence_id"]),
                    table_family_id=str(anchor.get("table_family") or ""),
                    statement_scope=anchor_scope,
                    research_definition_id=str(
                        (selected_definition or {}).get("definition_id") or ""
                    ),
                    definition_version=str(
                        (selected_definition or {}).get("definition_version") or ""
                    ),
                )
            )
            if not restored_links:
                restored_links = (
                    backend.child_discovery_repository
                    .certified_links_for_physical_anchor(
                        anchor,
                        table_family_id=str(anchor.get("table_family") or ""),
                        statement_scope=anchor_scope,
                        research_definition_id=str(
                            (selected_definition or {}).get("definition_id") or ""
                        ),
                        definition_version=str(
                            (selected_definition or {}).get("definition_version") or ""
                        ),
                    )
                )
            auto_certified_links = _union_certified_links(
                auto_certified_links,
                [{**link, "pdf_path": str(source)} for link in restored_links],
            )
        st.session_state["v613_portfolio_execution_plans"] = portfolio_execution_plans
        auto_certified_child_ids={
            str(link.get("anchor_child_id") or "")
            for link in auto_certified_links
        }
        st.session_state["v610_child_mappings"]=[
            item for item in v610_mappings
            if str((item.get("child") or {}).get("anchor_child_id") or "")
            not in auto_certified_child_ids
        ]
        st.session_state["v610_certified_child_links"]=auto_certified_links
        st.session_state["v610_child_mapping_contract_version"] = DISCOVERY_VERSION
    # v6.11: strict and compat are input adapters only. They share one
    # persistent execution session, one panel callback, and one widget prefix.
    strict_stage_b_key_prefix = "v611_stage_b_capture"
    compat_stage_b_key_prefix = "v611_stage_b_capture"

    def _render_stage_b_panel(
        *, certified_links=None,plans=None,source_pdf_map=None,
    ):
        from components.child_capture_execution_panel import (
            render_child_capture_execution_panel,
        )
        if ranked.get("excluded_scope_candidates"):
            st.warning("以下候选来源口径与所选 lane 冲突，已硬性排除，不能认证为当前口径：")
            st.dataframe(pd.DataFrame([
                {"PDF": row.get("statement_pdf_page_index"), "来源标题": row.get("source_table_title"),
                 "来源 scope": row.get("source_statement_scope") or row.get("scope"),
                 "失败门禁": "SCOPE_CONFLICT"}
                for row in ranked["excluded_scope_candidates"]
            ]), use_container_width=True, hide_index=True)
        assert strict_stage_b_key_prefix == compat_stage_b_key_prefix
        effective_pdf_map = {
            str(path):Path(path) for path in selected_pdfs
        }
        effective_pdf_map.update(source_pdf_map or {})
        return render_child_capture_execution_panel(
            st,backend,
            display_name=display_name,
            certified_links=certified_links,
            plans=plans,
            source_pdf_map=effective_pdf_map,
            research_definition=selected_definition,
            scope=requested_scope,
            key_prefix=strict_stage_b_key_prefix,
        )

    resolved_occurrences = st.session_state.get("v66_resolved_occurrences", [])
    if not resolved_occurrences:
        # A fresh Streamlit process has no workflow session_state. The
        # Stage B service restores any existing plan/batch/progress from DB.
        _render_stage_b_panel()
        return
    mappings=st.session_state.get("v610_child_mappings",[])
    if mappings and st.session_state.get("v610_child_mapping_contract_version") != DISCOVERY_VERSION:
        # Never render stale mapping rows after a retrieval-contract change:
        # the old rows can contain OCR-contaminated labels and old cache IDs.
        # Stage A certification explicitly regenerates the persistent child
        # concepts and is the only valid state transition into Stage B.
        st.warning("阶段 B 检索合同已更新。请返回阶段 A 重新认证所选 Anchor，以生成新的标准成员映射。")
        st.session_state["v610_child_mappings"]=[]
        mappings=[]
    certified_links=list(
        st.session_state.get("v610_certified_child_links",[])
    )
    portfolio_execution_plans=dict(
        st.session_state.get("v613_portfolio_execution_plans", {})
    )
    if mappings:
        from components.child_mapping_review import (
            render_inventory_resolution_case,
        )
        st.markdown("#### 阶段 B：校正未决候选语义")
        st.caption(
            "完整 inventory 已自动认证；这里只显示已持久化的 OPEN/UNRESOLVED case。"
            "人工只能重分类或关联现有 logical/segment candidate IDs。"
        )
        actionable_mappings=_stage_b_actionable_inventory_mappings(
            backend,mappings,
        )
        if not actionable_mappings:
            st.session_state["v610_child_mappings"]=[]
            mappings=[]
        remaining_mappings=[]
        newly_certified=[]
        for item, cases in actionable_mappings:
            child=item["child"]
            with st.expander(
                f"{item['contract']['canonical_title']}｜{child['statement_scope']}｜"
                f"{_stage_b_amount_caption(child)}",
                expanded=bool(cases),
            ):
                if child.get("raw_label") and child.get("raw_label") != item["contract"]["canonical_title"]:
                    st.caption(f"源表识别标签：{child['raw_label']}")
                run=item["run"]
                st.caption(
                    f"执行层级：{', '.join(run['tiers_executed']) or '-'}；"
                    f"跳过：{', '.join(run['tiers_skipped']) or '-'}；"
                    f"早停：{run.get('early_stop_reason') or '无'}"
                )
                resolved=False
                for case in cases:
                    result=render_inventory_resolution_case(
                        st,backend,case,
                        key_prefix=(
                            "v611_guided_inventory_case_"
                            +case["resolution_case_id"]
                        ),
                    )
                    if not result:
                        continue
                    enriched=(
                        backend.child_discovery_repository.cached_enriched(
                            case["candidate_id"]
                        )
                    )
                    if not enriched:
                        st.error("校正已保存，但 enriched candidate 不可恢复。")
                        continue
                    links=(
                        backend.hierarchical_child_discovery_service.link_candidates(
                            item["anchor"],child,[enriched],item["contract"],
                        )
                    )
                    assignment=(
                        backend.hierarchical_child_discovery_service.assign_global(
                            item["anchor"]["occurrence_id"],
                            child["statement_scope"],
                            {child["anchor_child_id"]:links},
                        )
                    )
                    promoted=[
                        link|{"pdf_path":item["pdf_path"]}
                        for link in assignment.get("certified_links") or []
                    ]
                    if not promoted:
                        st.error("语义校正已认证，但 logical link 自动提升失败。")
                        continue
                    newly_certified.extend(promoted)
                    resolved=True
                    st.success(f"已提升 {len(promoted)} 个 logical table link。")
                    break
                if not resolved:
                    remaining_mappings.append(item)
        if newly_certified:
            by_certified_id={
                str(link["certified_link_id"]):link
                for link in [*certified_links,*newly_certified]
            }
            certified_links=list(by_certified_id.values())
            st.session_state["v610_certified_child_links"]=certified_links
            st.session_state["v610_child_mappings"]=remaining_mappings
            mappings=remaining_mappings
        elif actionable_mappings:
            st.session_state["v610_child_mappings"]=remaining_mappings
            mappings=remaining_mappings
        st.divider()
    portfolio_readiness = {
        occurrence_id: evaluate_portfolio_certification_readiness(
            plan, certified_links,
        )
        for occurrence_id, plan in portfolio_execution_plans.items()
    }
    blocked_portfolio_plans = {
        occurrence_id: status
        for occurrence_id, status in portfolio_readiness.items()
        if status["status"] != "READY_FOR_CAPTURE_PLAN"
    }
    if blocked_portfolio_plans:
        st.markdown("#### 阶段 B：完成拓扑要求的全部认证目标")
        for occurrence_id, status in blocked_portfolio_plans.items():
            st.warning(
                f"{occurrence_id} 尚缺认证目标："
                + "、".join(status["missing_target_ids"] or status["blocking_issue_codes"])
                + "。Direct 与 Note 必需分支全部完成前不会生成 Capture Plan。"
            )
    if resolved_occurrences and not (certified_links or mappings):
        st.error(
            "阶段 A 认证已完成，但本次没有产生任何 CertifiedChildTableLink，"
            "也没有待处理的未决映射，因此不能进入 Stage B 执行。"
            "请核对认证结果（例如附注容器重复认证冲突），"
            "系统不会用历史会话计划代替本次认证结果。"
        )
        return
    if (certified_links or mappings) and not blocked_portfolio_plans:
        st.info(
            "已完成拓扑要求的 Stage B 认证目标；当前执行路径进入认证 Capture Plan。"
            "仍有 UNRESOLVED 时只保留异常队列，不回退到手工附注目标。"
        )
        _render_stage_b_panel(certified_links=certified_links)
        return
    if blocked_portfolio_plans:
        return
    st.markdown("#### 兼容流程：审核显式附注目标")
    st.caption("只有本阶段明确确认的附注目标会进入 Capture Plan；未选 Anchor 与未确认目标不会生成作业。")
    target_selections: dict[str, dict[str, Any]] = {}
    for occ in resolved_occurrences:
        pdf = _resolve_pdf_path(occ, backend)
        pdf_label = pdf.name if pdf else str(occ.get("pdf_id") or "PDF证据不可用")
        with st.expander(f"{pdf_label} · 已选主表：{occ.get('source_table_title')}", expanded=False):
            if pdf and occ.get("statement_pdf_page_index"):
                from pdf_evidence import page_preview
                preview = page_preview(pdf, int(occ["statement_pdf_page_index"]) - 1,
                                       [str(x.get("item") or "") for x in occ.get("child_rows") or []])
                _show_pdf_preview(st, preview, "主表")
            for child in occ.get("child_rows") or []:
                member = str(child.get("member_table") or child.get("item") or "")
                if child.get("member_period_status") in {
                    "COMPARATIVE_ONLY_LEGACY_MEMBER",
                    "ACTIVE_COMPARATIVE_PERIOD",
                    "INACTIVE_CURRENT_PERIOD",
                }:
                    st.caption(f"{member} · 仅比较期/历史证据；不构成当前期 Stage B 必需链接。")
                    continue
                candidates = child.get("note_target_candidates") or []
                st.markdown(f"**{member}** · {child.get('note_reference_normalized') or child.get('note_reference') or '无附注引用'}")
                if not candidates:
                    st.warning("未找到可认证附注目标：不会自动抓取。")
                    continue
                labels = [f"PDF {x['pdf_page_index']} · {x.get('heading','')[:70]} · {x.get('locator_method')} · {x.get('score',0):.2f}" for x in candidates]
                selected_label = st.selectbox("确认附注目标", labels, key=f"v66_target_{occ['occurrence_id']}_{member}")
                candidate = candidates[labels.index(selected_label)]
                target_selections[f"{occ['occurrence_id']}::{member}"] = backend.discovery_service.note_resolver.certify(candidate)
    if st.button("③ 认证附注目标并生成 Capture Plan", key="v66_certify_targets"):
        plans = []
        for occ in resolved_occurrences:
            persisted=backend.discovery_registry.get_occurrence(occ["occurrence_id"])
            if not persisted or (
                persisted.get("status")!="ANCHOR_CERTIFIED"
                and not backend.discovery_registry.is_anchor_certified(occ["occurrence_id"])
            ):
                st.error(
                    "该主报表只是历史会话中的候选，尚未完成 Anchor 认证。"
                    "请返回阶段 A 重新选择并点击“认证所选 Anchor”。"
                )
                continue
            target_map = {key.split("::", 1)[1]: value for key, value in target_selections.items() if key.startswith(occ["occurrence_id"] + "::")}
            plans.append(backend.discovery_service.certified_capture_plan(occ, certified_ids=[], certified_targets=target_map))
        if not plans:
            st.session_state.pop("v66_certified_plans",None)
            return
        st.session_state["v66_certified_plans"] = plans
    plans = st.session_state.get("v66_certified_plans", [])
    stage_b_pdf_map = {}
    for occurrence in resolved_occurrences:
        path = _resolve_pdf_path(occurrence,backend)
        if path:
            stage_b_pdf_map[
                str(occurrence.get("pdf_id") or path)
            ] = path
    for link in certified_links:
        path = Path(str(link.get("pdf_path") or ""))
        if path.is_file():
            stage_b_pdf_map[
                str(link.get("pdf_id") or path)
            ] = path
    _render_stage_b_panel(
        certified_links=certified_links,
        plans=plans,
        source_pdf_map=stage_b_pdf_map,
    )


def render_review_center(st, backend) -> None:
    st.title("研究任务审核中心")
    batches = backend.research_batch_service.list()
    if batches:
        st.subheader("研究任务 / Research Batch")
        labels = {f"{b['display_name']} · {b['research_batch_id']} · {b['status']}": b for b in batches}
        chosen = labels[st.selectbox("选择研究任务", list(labels), key="v66_review_research_batch")]
        impact = backend.research_batch_service.impact(chosen['research_batch_id'])
        st.json({k: impact[k] for k in ['research_batch_id','plans','source_batches','jobs','captures']})
        st.caption("以下审核将优先围绕该研究任务的来源计划、主报表 Anchor、成员与附注目标展开；内部 DISC ID 仅在审计详情显示。")
        if st.button("修复本研究批次缺失的定义身份", key="v610_backfill_batch_definition_identity"):
            repair = backend.research_batch_service.backfill_missing_definition_identity(chosen['research_batch_id'])
            if repair.get("reason"):
                st.warning("该研究批次没有固定的研究定义版本，不能安全回填。")
            else:
                st.success(f"已安全回填 {repair.get('updated', 0)} 个逻辑资产的缺失定义身份；既有身份未被覆盖。")
                st.rerun()
        plan_view = backend.research_batch_service.plan_view(chosen['research_batch_id'])
        if plan_view:
            st.markdown("#### 已选主报表与子表（唯一执行范围）")
            for plan in plan_view:
                payload = plan.get('payload', {})
                anchor = payload.get('anchor', {})
                pdf = _resolve_pdf_path(
                    {"pdf_id": plan.get("pdf_id"), "source_pdf": payload.get("source_pdf")},
                    backend,
                )
                pdf_label = pdf.name if pdf else str(plan.get("pdf_id") or "PDF证据不可用")
                st.markdown(f"**{pdf_label}** · 已选 Anchor：{anchor.get('source_table_title','主报表')} · {anchor.get('scope','-')}")
                rows = []
                for item in plan['items']:
                    if item.get('member_table_role') == 'NOTE_DETAIL':
                        item_payload = json.loads(item.get('payload_json') or '{}')
                        target = item_payload.get('certified_note_target') or {}
                        rows.append({'成员':item.get('member_table'),'附注':item.get('note_reference'),'认证页':item.get('confirmed_note_pdf_page_index'),'目标标题':target.get('target_heading'),'状态':item.get('status')})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                with st.expander("查看已认证主报表与附注证据", expanded=False):
                    statement_page = _safe_pdf_page(anchor.get('statement_pdf_page_index'))
                    if pdf and statement_page:
                        from pdf_evidence import page_preview
                        terms = [str(anchor.get('display_name') or '')] + [str(row['成员']) for row in rows]
                        preview = page_preview(pdf, statement_page - 1, terms)
                        _show_pdf_preview(st, preview, "主报表")
                    else:
                        st.warning("主报表证据页不可用；该计划不应据此自动扩大抓取范围。")
                    for row in rows:
                        target_page = _safe_pdf_page(row['认证页'])
                        if pdf and target_page:
                            from pdf_evidence import page_preview
                            detail = page_preview(pdf, target_page - 1, [str(row['目标标题'] or row['成员'])])
                            _show_pdf_preview(st, detail, str(row["成员"]))
                        else:
                            st.warning(f"{row['成员']} 缺少已认证附注页，不能进入自动抓取。")
            left, right = st.columns(2)
            if left.button("移入研究任务回收站", key="v66_trash_research_batch"):
                st.success(str(backend.research_batch_service.trash(chosen['research_batch_id'])))
                st.rerun()
            if right.button("恢复研究任务", key="v66_restore_research_batch"):
                st.success(str(backend.research_batch_service.restore(chosen['research_batch_id'])))
                st.rerun()
            st.markdown("#### Capture Result Review（执行、目标、质量分层）")
            result_rows = backend.research_batch_service.result_review(chosen['research_batch_id'])
            review_table = pd.DataFrame(result_rows)
            if "certification_score" in review_table.columns:
                review_table["认证评分"] = review_table["certification_score"].map(
                    lambda value: "" if pd.isna(value) else f"{float(value):.2f}"
                )
                st.caption("certification_score 是已认证主表与成员证据的综合评分。")
            st.dataframe(review_table, use_container_width=True, hide_index=True)
            st.caption("execution_status 是不可变的历史作业结果；capture_quality 是最新非替代 Capture 的当前质量，重跑与合表以当前质量为准。")
            st.caption("认证评分使用 certification_score（综合认证分），不使用检索先验分作为审核主评分。")
            review_queue = []
            for row in result_rows:
                if str(row.get("capture_quality") or row.get("review_status") or "").upper() != "REVIEW_REQUIRED":
                    continue
                for capture_id in row.get("capture_ids") or []:
                    capture = backend.capture_service.get(capture_id) or {}
                    logical_asset_id = str(capture.get("logical_asset_id") or "")
                    if not logical_asset_id:
                        continue
                    review_queue.append({
                        "capture_id": capture_id,
                        "logical_asset_id": logical_asset_id,
                        "company_id": capture.get("company_id") or row.get("company_id") or row.get("company"),
                        "report_year": capture.get("report_year") or row.get("report_year"),
                        "member_table_id": capture.get("member_table_id") or row.get("member_table"),
                        "initial_tab": "审核",
                        "return_route": "研究任务审核中心",
                    })
            if review_queue and st.button("审核待复核 Capture（进入逻辑资产工作区）", key="v6121_open_research_review_queue"):
                first = review_queue[0]
                st.session_state["asset_workspace_review_queue"] = review_queue
                for key in ("selected_logical_asset_id", "selected_capture_version_id", "asset_workspace_review_queue_capture"):
                    st.session_state.pop(key, None)
                st.session_state["inspection_route"] = {
                    "logical_asset_id": first["logical_asset_id"], "capture_version_id": first["capture_id"],
                    "table_block_id": "", "initial_tab": "审核", "return_route": "研究任务审核中心",
                    "review_queue_item_id": "",
                }
                st.session_state["_pending_main_page"] = "逻辑资产工作区"
                st.rerun()
            rerun_mode = st.selectbox("重跑范围", ["REVIEW_REQUIRED", "ALL"], key="v66_research_rerun_mode")
            rerun_candidates = backend.research_batch_service.rerun_candidates(chosen['research_batch_id'], rerun_mode)
            st.caption(f"可重跑的认证目标：{len(rerun_candidates)}；未认证或未选 Anchor 不会列入。")
            if st.button("按所选范围创建并启动认证重跑", key="v66_research_rerun_certified", disabled=not rerun_candidates):
                rerun_plans = backend.research_batch_service.build_rerun_plans(chosen['research_batch_id'], rerun_mode)
                results = []
                for rerun_plan in rerun_plans:
                    pdf = _resolve_pdf_path(rerun_plan, backend)
                    if pdf:
                        results.append(backend.guided_capture_service.execute(rerun_plan, pdf_path=pdf, research_batch_id=chosen['research_batch_id']))
                jobs = sum(len(result.get('jobs', [])) for result in results)
                st.success(f"已按 {rerun_mode} 新建 {len(rerun_plans)} 份版本化重跑计划并提交 {jobs} 个作业；不会复用旧作业状态。")
                st.rerun()
            st.markdown("#### 在此直接审核 Capture 结构")
            capture_choices = {}
            for row in result_rows:
                for capture_id in row.get('capture_ids') or []:
                    capture_choices[f"{row['member_table']} · {capture_id}"] = {
                        "capture_id": capture_id,
                        "review_row": row,
                    }
            if not capture_choices:
                st.caption("尚无完成的 Capture 可审核；完成作业后无需前往数据资产管理，可直接在此审核。")
            else:
                selected_capture_label = st.selectbox("选择本研究任务的 Capture", list(capture_choices), key="v66_review_capture_direct")
                selected_capture = capture_choices[selected_capture_label]
                capture = backend.capture_service.get(selected_capture["capture_id"])
                selected_review_row = selected_capture["review_row"]
                run_dir = Path(str((capture or {}).get('run_path') or ''))
                if capture and run_dir.exists():
                    wide_path = run_dir / 'table_raw_wide.csv'
                    long_path = run_dir / 'table_raw_long.csv'
                    machine_wide_path = run_dir / 'machine_capture_full_wide.csv'
                    machine_long_path = run_dir / 'machine_capture_full_long.csv'
                    official_tab, machine_tab = st.tabs(["正式输出", "机器完整证据"])
                    official_tab.dataframe(
                        pd.read_csv(wide_path) if wide_path.exists() else pd.DataFrame(),
                        use_container_width=True,
                        hide_index=True,
                    )
                    machine_tab.dataframe(
                        pd.read_csv(machine_wide_path) if machine_wide_path.exists() else pd.DataFrame(),
                        use_container_width=True,
                        hide_index=True,
                    )
                    metadata_path = run_dir / "capture_metadata.json"
                    try:
                        capture_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
                    except (OSError, json.JSONDecodeError):
                        capture_metadata = {}
                    _render_golden_capture_parity(
                        st, backend, run_dir,
                        str(capture_metadata.get("member_table") or selected_review_row.get("member_table") or ""),
                        str(capture_metadata.get("source_pdf_path") or ""), capture_metadata,
                    )
                    result_path = run_dir / 'table_capture_result.json'
                    if result_path.exists():
                        try:
                            capture_result = json.loads(result_path.read_text(encoding='utf-8'))
                        except (OSError, json.JSONDecodeError):
                            capture_result = {}
                        capture_stats = capture_result.get("stats") or {}
                        boundary_evidence = capture_stats.get("boundary_evidence") or {}
                        boundary_method = str(boundary_evidence.get("method") or "")
                        boundary_target_page = _safe_pdf_page(
                            boundary_evidence.get("next_note_pdf_page_index")
                        )
                        has_terminating_boundary = bool(
                            boundary_target_page
                            and boundary_method in {"NEXT_NOTE_ORDINAL", "NEXT_PEER_HEADING"}
                        )
                        st.markdown("##### Table Boundary Evidence")
                        st.json({
                            "start": (
                                f"{capture_result.get('note_number') or capture_result.get('located_title')}"
                                f" · PDF {capture_result.get('start_page') or '?'}"
                            ),
                            "end": (
                                (
                                    f"{boundary_evidence.get('next_note_ordinal') or '未认证'}"
                                    f" · {boundary_evidence.get('next_note_title') or '需人工确认'}"
                                    f" · PDF {boundary_target_page or '?'}"
                                )
                                if has_terminating_boundary
                                else (
                                    f"未发现独立终止边界；搜索截止于 PDF "
                                    f"{capture_result.get('end_page') or '?'}"
                                )
                            ),
                            "evidence": boundary_method or "NO_BOUNDARY_EVIDENCE",
                            "boundary_confidence": capture_stats.get("boundary_confidence") or "LOW",
                            "boundary_status": capture_result.get("boundary_status") or "REVIEW_REQUIRED",
                        })
                        source_pdf_candidates = [
                            capture_stats.get("source_pdf_path"),
                            selected_review_row.get("source_pdf"),
                        ]
                        source_pdf = next(
                            (
                                Path(str(candidate))
                                for candidate in source_pdf_candidates
                                if candidate and Path(str(candidate)).is_file()
                            ),
                            None,
                        )
                        if source_pdf:
                            with st.expander("PDF 边界证据预览", expanded=True):
                                from pdf_evidence import page_preview
                                start_page = _safe_pdf_page(capture_result.get("start_page"))
                                end_page = _safe_pdf_page(
                                    boundary_target_page
                                    if has_terminating_boundary
                                    else capture_result.get("end_page")
                                )
                                left_preview, right_preview = st.columns(2)
                                if start_page:
                                    start_evidence = page_preview(
                                        source_pdf,
                                        start_page - 1,
                                        [
                                            str(capture_result.get("located_title") or ""),
                                            str(capture_result.get("table_query") or ""),
                                        ],
                                    )
                                    _show_pdf_preview(left_preview, start_evidence, "开始")
                                else:
                                    left_preview.warning("缺少可用的表格起始页。")
                                if end_page:
                                    end_evidence = page_preview(
                                        source_pdf,
                                        end_page - 1,
                                        (
                                            [
                                                str(boundary_evidence.get("next_note_title") or ""),
                                                str(boundary_evidence.get("next_note_heading_raw") or ""),
                                            ]
                                            if has_terminating_boundary
                                            else []
                                        ),
                                    )
                                    _show_pdf_preview(
                                        right_preview,
                                        end_evidence,
                                        "终止证据"
                                        if has_terminating_boundary
                                        else "搜索截止页（非边界证据）",
                                    )
                                    if not has_terminating_boundary:
                                        right_preview.info(
                                            "该页仅表示搜索窗口截止位置，不能作为下一附注边界的认证证据。"
                                        )
                                else:
                                    right_preview.warning("缺少可用的终止边界页；必须人工审核。")
                        else:
                            st.warning("未能解析此 Capture 的源 PDF 路径，暂时无法显示页面预览。")
                        machine_columns = list(capture_result.get('columns') or [])
                        if machine_columns:
                            st.caption("列维度审核也可在此完成；机器表头不会被覆盖，人工确认另存为审核记录。")
                            editable_columns = pd.DataFrame(machine_columns)
                            for column, default in (("year", ""), ("scope", ""), ("restated", False)):
                                if column not in editable_columns:
                                    editable_columns[column] = default
                            editable_columns["year"] = editable_columns["year"].where(editable_columns["year"].notna(), "")
                            editable_columns["scope"] = editable_columns["scope"].where(editable_columns["scope"].notna(), "")
                            editable_columns["restated"] = editable_columns["restated"].fillna(False).astype(bool)
                            editable_columns = editable_columns[[
                                column for column in ("ordinal", "header_raw", "year", "scope", "restated")
                                if column in editable_columns
                            ]]
                            with st.expander("审核列维度（期间 / 口径 / 重述）", expanded=False):
                                reviewed_columns = st.data_editor(
                                    editable_columns,
                                    hide_index=True,
                                    use_container_width=True,
                                    disabled=[column for column in ("ordinal", "header_raw") if column in editable_columns],
                                    key=f"v66_direct_header_editor_{capture['capture_id']}",
                                )
                                header_note = st.text_input("列维度审核说明", key=f"v66_direct_header_note_{capture['capture_id']}")
                                capture_detail=backend.capture_version_service.detail(capture["capture_id"])
                                if capture_detail:
                                    from inspection_route import InspectionRoute,set_inspection_route
                                    st.button(
                                        "在逻辑资产工作区审核表头",
                                        key=f"v69_route_header_{capture['capture_id']}",
                                        on_click=set_inspection_route,
                                        args=(st,InspectionRoute(
                                            logical_asset_id=capture_detail["logical_asset_id"],
                                            capture_version_id=capture["capture_id"],
                                            initial_tab="表头拓扑",return_route="发现结果审核",
                                        )),
                                        kwargs={"open_workspace":True},
                                    )
                    # Boundary adjudication must always use immutable machine
                    # evidence. Using an already-truncated official table makes
                    # it impossible to widen a previous human cutoff.
                    boundary_source = machine_long_path if machine_long_path.exists() else long_path
                    long = pd.read_csv(boundary_source) if boundary_source.exists() else pd.DataFrame()
                    if not long.empty and 'row_order' in long:
                        orders = sorted({int(x) for x in pd.to_numeric(long['row_order'], errors='coerce').dropna().tolist()})
                        cutoff = st.selectbox("确认边界：最后有效 row_order", orders, index=len(orders)-1, key=f"v66_direct_cutoff_{capture['capture_id']}")
                        capture_detail=backend.capture_version_service.detail(capture["capture_id"])
                        if capture_detail:
                            from inspection_route import InspectionRoute,set_inspection_route
                            st.button(
                                "在逻辑资产工作区审核边界",
                                key=f"v69_route_boundary_{capture['capture_id']}",
                                on_click=set_inspection_route,
                                args=(st,InspectionRoute(
                                    logical_asset_id=capture_detail["logical_asset_id"],
                                    capture_version_id=capture["capture_id"],
                                    initial_tab="附注容器与表块",return_route="发现结果审核",
                                )),
                                kwargs={"open_workspace":True},
                            )
                    else:
                        st.warning("此 Capture 缺少可审核的长表输出。")
            st.info("备选 Anchor 和原始机器候选已隔离至审计记录，不会显示为本研究任务的待审核子表，也不会进入 Capture Plan。")
            capture_ids = backend.research_batch_service.capture_ids(chosen['research_batch_id'])
            st.caption(f"可进入 Family Merge 的活动 Capture：{len(capture_ids)}")
            if capture_ids and st.button("将本研究任务的已认证 Capture 创建 Family Merge", key="v66_guided_family_merge"):
                merged = backend.merge_service.create(capture_ids=capture_ids, table_id=chosen['table_family'])
                st.success(f"已创建 Family Merge：{merged['merge_id']}")
            return
    rows = backend.discovery_registry.list_review_queue(limit=500)
    if not rows:
        st.info("暂无候选。请先运行“研究引导抓取”。")
        return
    table = pd.DataFrame(rows)
    st.caption("按 公司 → 年份 → 主报表 分级审核。一个主报表下同时展示其全部子表与附注证据；归档数据永不进入批量动作。")
    pending_statuses = ["NEEDS_REVIEW", "REVIEW_REQUIRED", "UNRESOLVED"]
    actionable = table[table["review_status"].isin(pending_statuses)].copy()
    archived = table[~table["review_status"].isin(pending_statuses)].copy()

    if actionable.empty:
        st.info("当前没有待审核候选。已处理记录可在下方归档区查看。")
        with st.expander(f"已处理归档（{len(archived)} 条，仅查看）", expanded=False):
            st.dataframe(archived, use_container_width=True, hide_index=True)
        return

    def text(value: Any) -> str:
        return "-" if value is None or pd.isna(value) or str(value).strip() == "" else str(value)

    companies = sorted(actionable["company"].dropna().astype(str).unique().tolist())
    company = st.selectbox("① 公司", companies, key="v651_review_company")
    by_company = actionable[actionable["company"].astype(str) == company].copy()
    years = sorted(by_company["report_year"].fillna("-").astype(str).unique().tolist(), reverse=True)
    year = st.selectbox("② 年份", years, key="v651_review_year")
    by_year = by_company[by_company["report_year"].fillna("-").astype(str) == year].copy()

    def anchor_key(r):
        return "\u241f".join([text(r.get(x)) for x in ("pdf_id", "scope", "source_table_title", "display_name", "statement_pdf_page_index", "statement_printed_page")])

    def anchor_label(r):
        page = _safe_pdf_page(r.get("statement_pdf_page_index")) or _safe_pdf_page(r.get("statement_page"))
        return " | ".join([text(r.get("scope")), text(r.get("source_table_title")), text(r.get("display_name")), f"PDF {page or '?'}（印刷页 {text(r.get('statement_printed_page'))}）"])

    by_year["_anchor_key"] = by_year.apply(anchor_key, axis=1)
    anchor_records = by_year.drop_duplicates("_anchor_key")
    anchor_options = {anchor_label(row): row["_anchor_key"] for _, row in anchor_records.iterrows()}
    chosen_anchor_label = st.selectbox("③ 主报表 / 表族", list(anchor_options), key="v651_review_anchor")
    chosen_anchor = anchor_options[chosen_anchor_label]
    children = by_year[by_year["_anchor_key"] == chosen_anchor].copy()

    def business_label(r):
        page = _safe_pdf_page(r.get("statement_pdf_page_index")) or _safe_pdf_page(r.get("statement_page"))
        return " | ".join([text(r.get("member_table") or r.get("statement_item")), text(r.get("note_reference_normalized")), f"附注 PDF {page or '?'}"])

    source = children.iloc[0].to_dict()
    pdf = _resolve_pdf_path(source, backend)
    statement_page = _safe_pdf_page(source.get("statement_pdf_page_index")) or _safe_pdf_page(source.get("statement_page"))
    st.markdown("#### 主报表证据")
    st.caption(chosen_anchor_label)
    if pdf and statement_page:
        from pdf_evidence import page_preview
        source_preview = page_preview(pdf, statement_page - 1, [text(source.get("display_name")), *(text(x) for x in children["member_table"].tolist())])
        _show_pdf_preview(st, source_preview, "主报表证据")
    else:
        st.warning("EVIDENCE_PAGE_UNRESOLVED：此主报表缺少可打开的 PDF 或有效页码。")

    children["子表审核对象"] = children.apply(business_label, axis=1)
    cols = [c for c in ["子表审核对象", "candidate_note_printed_page", "locator_method", "confidence", "review_status"] if c in children]
    st.markdown("#### 本主报表下的全部子表")
    st.dataframe(children[cols], use_container_width=True, hide_index=True)
    st.caption("下方同时提供每个子表的附注页预览；若没有 bbox/页码，会明确标记而不是伪造证据。")
    preview_columns = st.columns(2)
    for index, (_, child) in enumerate(children.iterrows()):
        with preview_columns[index % 2]:
            st.markdown(f"**{text(child.get('member_table') or child.get('statement_item'))}** · {text(child.get('note_reference_normalized'))}")
            note_page = _safe_pdf_page(child.get("candidate_note_pdf_page_index"))
            if pdf and note_page:
                from pdf_evidence import page_preview
                note_preview = page_preview(pdf, note_page - 1, [text(child.get("member_table") or child.get("statement_item"))])
                _show_pdf_preview(st, note_preview, "附注")
            else:
                st.info("未定位附注页：可标记 REVIEW_REQUIRED / UNRESOLVED。")

    # Only children from this specific source statement appear in the action UI.
    labels = dict(zip(children["子表审核对象"], children["discovery_id"]))
    chosen_labels = st.multiselect("④ 选择本主报表下要批量处理的子表", list(labels), default=list(labels), key="v651_anchor_child_select")
    ids = [labels[x] for x in chosen_labels]
    action = st.radio("⑤ 批量动作", ["ACCEPTED", "REJECTED", "REVIEW_REQUIRED", "UNRESOLVED"], horizontal=True)
    reason = st.text_input("审核理由", key="v65_review_reason")
    if st.button("保存批量审核", disabled=not ids, type="primary", key="v65_bulk_review"):
        backend.discovery_service.bulk_adjudicate(ids, label=action, reason=reason, scope="COMPANY_STATEMENT")
        st.success(f"已对 {len(ids)} 条候选逐条写入审计、认证知识和训练样本。")
    archived_for_anchor = archived.copy()
    if not archived_for_anchor.empty:
        archived_for_anchor["_anchor_key"] = archived_for_anchor.apply(anchor_key, axis=1)
        archived_for_anchor = archived_for_anchor[archived_for_anchor["_anchor_key"] == chosen_anchor]
    with st.expander(f"本主报表已处理归档（{len(archived_for_anchor)} 条，仅查看）", expanded=False):
        if archived_for_anchor.empty:
            st.caption("本主报表暂无已处理归档。")
        else:
            archived_for_anchor["子表审核对象"] = archived_for_anchor.apply(business_label, axis=1)
            archive_cols = [c for c in cols if c in archived_for_anchor]
            st.dataframe(archived_for_anchor[archive_cols], use_container_width=True, hide_index=True)
