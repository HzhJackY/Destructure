"""v6.10 scope-first, tiered child-table discovery.

The module deliberately indexes headings, not tables.  Table structure and
amounts are inspected only for a bounded Top-K page set.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import fitz

from metadata_registry import now_iso
from capture_models import (
    CaptureMode,
    CaptureRequest,
    literal_capture_query_title,
)
from version import APP_VERSION


INDEX_VERSION="FIN_NOTE_INDEX_V5_ALIGNED_ORDINAL_TITLE_BBOX"
DISCOVERY_VERSION="HIERARCHICAL_CHILD_V4_INDEX_VALIDATED_SOURCE_TARGET"
ENRICHMENT_VERSION="LOCAL_TOPK_V3_NOTE_TABLE_INVENTORY"
DEFAULT_LIMITS={"TIER1":3,"TIER2":8,"TIER3":8,"ENRICHMENT_TOP_K":3}
RETRIEVAL_PRIORS={
    "TIER1_SOURCE_RESOLVED_NOTE_TARGET":0.30,
    "TIER1_EXPLICIT_REFERENCE":0.30,
    "T2A_CANONICAL_EXACT":0.24,
    "T2B_NORMALIZED_EXACT":0.21,
    "T2C_CERTIFIED_ALIAS":0.19,
    "T2D_BOUNDED_SEMANTIC":0.16,
    "TIER3_RAW_FALLBACK":0.13,
}
VALID_SCOPES={"CONSOLIDATED","PARENT_COMPANY","BOTH","UNKNOWN"}
EXCLUDED_SECTION_MARKERS=("目录","管理层讨论","董事会报告","报告摘要")
# Accounting-label variants, not company/year/page rules.  The registry may
# provide richer aliases; these baseline pairs let a new filing bridge the
# IFRS 9 presentation change before it has any company-specific history.
ACCOUNTING_TITLE_VARIANTS={
    "以公允价值计量且其变动计入当期损益的金融资产": ["交易性金融资产"],
    "交易性金融资产": ["以公允价值计量且其变动计入当期损益的金融资产"],
}


def _json(value:Any)->str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True)


def _norm(text:Any)->str:
    value=unicodedata.normalize("NFKC",str(text or "")).strip().lower()
    value=re.sub(r"^[（(]?[一二三四五六七八九十百\d]+[）)、.\s]+","",value)
    return re.sub(r"[\s:：,，。；;（）()\[\]【】\-—_]+","",value)


def _capture_query_heading(text: Any) -> str:
    """Return the literal table title without a note/subsection ordinal."""
    return literal_capture_query_title(text)


def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def _stable_candidate_id(prefix:str,*parts:Any)->str:
    material="::".join(str(part or "").strip() for part in parts)
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _snapshot_sha256(value:Any)->str:
    def stable(item:Any)->Any:
        if isinstance(item,dict):
            return {
                key:stable(child)
                for key,child in item.items()
                if key not in {"created_at","updated_at"}
            }
        if isinstance(item,list):
            return [stable(child) for child in item]
        return item
    return hashlib.sha256(_json(stable(value)).encode("utf-8")).hexdigest()


def _confidence_value(value:Any)->float:
    if isinstance(value,(int,float)):
        return max(0.0,min(1.0,float(value)))
    return {"HIGH":0.95,"MEDIUM":0.75,"LOW":0.45}.get(
        str(value or "").strip().upper(),0.0,
    )


def _assert_inventory_contains_no_amount_values(value:Any)->None:
    forbidden={"amount_summary","numeric_sample","raw_value","raw_values","value","values","sample"}
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).strip().lower() in forbidden:
                raise ValueError("CANDIDATE_INVENTORY_AMOUNT_VALUE_FORBIDDEN")
            _assert_inventory_contains_no_amount_values(item)
    elif isinstance(value,list):
        for item in value:
            _assert_inventory_contains_no_amount_values(item)


def _scope(text:str)->str:
    parent=bool(re.search(r"母公司|公司财务报表|本公司",text))
    consolidated=bool(re.search(r"合并财务报表|合并资产负债表|本集团|合并",text))
    if parent and consolidated:return "UNKNOWN"
    if parent:return "PARENT_COMPANY"
    if consolidated:return "CONSOLIDATED"
    return "UNKNOWN"


def _unit(text:str)->str:
    if "百万元" in text:return "CNY_MILLION"
    if "千元" in text:return "CNY_THOUSAND"
    if "人民币元" in text or "单位：元" in text:return "CNY"
    return ""


def _numbers(text:str)->list[float]:
    values=[]
    for token in re.findall(r"(?<!\d)(?:\(?-?\d[\d,]*(?:\.\d+)?\)?)(?!\d)",text):
        try:
            negative=token.startswith("(") and token.endswith(")")
            values.append(float(token.strip("()").replace(",",""))*(-1 if negative else 1))
        except ValueError:pass
    return values


def _chinese_ordinal(value:Any)->str:
    token=str(value or "").strip()
    if token.isdigit():return str(int(token))
    digits={"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,
            "六":6,"七":7,"八":8,"九":9}
    if token in digits:return str(digits[token])
    if token=="十":return "10"
    if "十" in token:
        left,right=token.split("十",1)
        tens=digits.get(left,1) if left else 1
        ones=digits.get(right,0) if right else 0
        return str(tens*10+ones)
    return token


def _ordinal_display(value: str) -> str:
    """Display a parsed section ordinal in the report's usual Chinese form."""
    try:
        number=int(value)
    except (TypeError, ValueError):
        return str(value or "")
    digits="零一二三四五六七八九"
    if 0 <= number < 10:
        return digits[number]
    if number == 10:
        return "十"
    if 10 < number < 20:
        return "十" + digits[number - 10]
    if 20 <= number < 100:
        return digits[number // 10] + "十" + ("" if number % 10 == 0 else digits[number % 10])
    return str(number)


def _leaf_note_ordinal(reference:Any)->str:
    tokens=re.findall(r"[一二三四五六七八九十百]+|\d+",str(reference or ""))
    return _chinese_ordinal(tokens[-1]) if tokens else ""


def _note_reference_key(reference: Any) -> dict[str, Any]:
    """Normalise notation without discarding section/item provenance.

    ``附注八-9`` and ``八、9`` share the same leaf item but are not silently
    claimed to be identical section references.  Tier 1 can use the leaf to
    find headings while retaining the raw/normalised evidence for review.
    """
    raw=unicodedata.normalize("NFKC",str(reference or "")).strip()
    tokens=re.findall(r"[一二三四五六七八九十百]+|\d+",raw)
    parsed=[_chinese_ordinal(token) for token in tokens]
    parsed=[token for token in parsed if token]
    section=parsed[-2] if len(parsed)>=2 else ""
    item=parsed[-1] if parsed else ""
    # Keep a human-readable canonical value while the ordinal fields below
    # remain the machine comparison key.  This prevents a UI/audit trail from
    # losing the fact that a row value came from an accounting note reference.
    normalized=(f"附注{_ordinal_display(section)}-{item}" if section else (f"附注{item}" if item else ""))
    return {
        "raw_note_reference":raw,"normalized_note_reference":normalized,
        "note_section_ordinal":section,"note_item_ordinal":item,
        "parse_confidence":"HIGH" if item else "NONE",
    }


def _next_peer_heading(
    heading_rows:list[dict[str,Any]],
    *,
    current_order:int,
    note_identity:str,
) -> dict[str,Any]|None:
    if not note_identity:
        return None
    current_numeric=int(note_identity) if note_identity.isdigit() else None
    for row in heading_rows:
        if int(row.get("heading_order") or -1)<=int(current_order):
            continue
        row_identity=_leaf_note_ordinal(
            str(row.get("note_reference") or row.get("note_ordinal") or "")
        )
        if not row_identity or row_identity==note_identity:
            continue
        if current_numeric is not None:
            if not row_identity.isdigit() or int(row_identity)!=current_numeric+1:
                continue
        normalized_heading=_norm(row.get("raw_heading") or "")
        if "财务报表" in normalized_heading and "附注" in normalized_heading:
            continue
        return row
    return None


def _amount_sequence(value: Any) -> list[Any]:
    """Keep raw amount observations intact while normalising scalar/list input."""
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        # A period-keyed contract is an observation map, not a single amount.
        return [value]
    return [value]


def _numeric_amounts(value: Any) -> list[float]:
    """Read StatementFamilyMember observations only; never candidate amounts."""
    output: list[float] = []
    if isinstance(value, dict):
        for item in value.values():
            output.extend(_numeric_amounts(item))
        return output
    if isinstance(value, (list, tuple)):
        for item in value:
            output.extend(_numeric_amounts(item))
        return output
    try:
        token=str(value).strip().replace(",", "")
        if token and token not in {"-", "—", "–", "不适用", "None", "null"}:
            output.append(float(token.strip("()")) * (-1 if token.startswith("(") else 1))
    except (TypeError, ValueError):
        pass
    return output


def _title_match_class(target: Any, heading: Any) -> tuple[str, float]:
    target_raw=_capture_query_heading(target)
    heading_raw=_capture_query_heading(heading)
    target_norm=_norm(target_raw); heading_norm=_norm(heading_raw)
    if target_raw and target_raw == heading_raw:
        return "EXACT_CANONICAL_TITLE", 0.28
    if target_norm and target_norm == heading_norm:
        return "EXACT_NORMALIZED_TITLE", 0.24
    if target_norm and heading_norm.startswith(target_norm):
        return "PREFIX_OR_SUFFIX_QUALIFIED_TITLE", 0.14
    if target_norm and target_norm in heading_norm:
        return "CONTAINS_TARGET_TITLE", 0.06
    target_chars=set(target_norm); heading_chars=set(heading_norm)
    similarity=len(target_chars & heading_chars)/max(1, len(target_chars | heading_chars))
    return "SEMANTIC_ONLY", 0.03 * similarity


def _contract_titles(member_contract: dict[str, Any]) -> list[str]:
    canonical=str(member_contract.get("canonical_title") or member_contract.get("member_table_id") or "")
    titles=[canonical, *(member_contract.get("exact_aliases") or []), *(member_contract.get("certified_company_aliases") or [])]
    for title in list(titles):
        titles.extend(ACCOUNTING_TITLE_VARIANTS.get(str(title), []))
    return list(dict.fromkeys(title for title in titles if str(title).strip()))


def _best_title_match(member_contract: dict[str, Any], heading: Any) -> tuple[str, float, str]:
    choices=[(*_title_match_class(title, heading), title) for title in _contract_titles(member_contract)]
    return max(choices, key=lambda item: item[1]) if choices else ("SEMANTIC_ONLY", 0.0, "")


def _subtable_role(
    heading:Any,member_contract:dict[str,Any],*,
    table_classification:str="",
) -> str:
    normalized=_norm(heading)
    # A canonical table heading wins over disclosure-keyword heuristics:
    # FVTPL contains “公允价值…变动” and held-to-maturity contains “到期”,
    # but both are primary balance-sheet member tables, not supplementary
    # movement/maturity disclosures.
    if str(table_classification or "").upper()!="SUPPLEMENTARY_TABLE":
        title_class,_,_=_best_title_match(member_contract, heading)
        if title_class in {"EXACT_CANONICAL_TITLE", "EXACT_NORMALIZED_TITLE", "PREFIX_OR_SUFFIX_QUALIFIED_TITLE"}:
            return "PRIMARY_AMOUNT_DETAIL"
    if re.search(r"公允价值.*变动|变动.*公允价值", normalized):
        return "FAIR_VALUE_MOVEMENT"
    if re.search(r"信用损失|减值准备|损失准备|拨备", normalized):
        return "LOSS_ALLOWANCE_ROLLFORWARD"
    if re.search(r"到期|期限|账龄", normalized):
        return "MATURITY_ANALYSIS"
    if re.search(r"信用风险|风险敞口", normalized):
        return "CREDIT_RISK_BREAKDOWN"
    return "SUPPLEMENTARY_DISCLOSURE"


@dataclass(frozen=True)
class StatementScopeSelection:
    scope_selection_id:str
    source_pdf_id:str
    requested_scope:str="CONSOLIDATED"
    default_scope:str="CONSOLIDATED"
    selection_source:str="USER_SELECTED"
    research_project_id:str=""
    research_task_id:str=""
    research_definition_id:str=""
    selected_by:str="USER"
    selected_at:str=""
    evidence:dict[str,Any]=None
    producer_version:str=APP_VERSION

    @classmethod
    def new(cls,source_pdf_id:str,requested_scope:str="CONSOLIDATED",**kwargs):
        scope=requested_scope if requested_scope in VALID_SCOPES else "UNKNOWN"
        return cls("SCOPE_"+uuid.uuid4().hex,source_pdf_id,scope,
                   kwargs.pop("default_scope","CONSOLIDATED"),
                   kwargs.pop("selection_source","USER_SELECTED"),
                   selected_at=now_iso(),evidence=kwargs.pop("evidence",{}),**kwargs)

    def lanes(self)->tuple[str,...]:
        return ("CONSOLIDATED","PARENT_COMPANY") if self.requested_scope=="BOTH" else (self.requested_scope,)


class ChildDiscoveryRepository:
    def __init__(self,registry):self.registry=registry

    def save_scope(self,row:StatementScopeSelection)->dict[str,Any]:
        p=asdict(row)
        with self.registry.connect() as c:
            c.execute("""INSERT INTO statement_scope_selections(
                scope_selection_id,research_project_id,research_task_id,research_definition_id,
                source_pdf_id,requested_scope,default_scope,selection_source,selected_by,
                selected_at,evidence_json,producer_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(research_task_id,source_pdf_id,requested_scope) DO UPDATE SET
                selection_source=excluded.selection_source,selected_by=excluded.selected_by,
                selected_at=excluded.selected_at,evidence_json=excluded.evidence_json""",
                (p["scope_selection_id"],p["research_project_id"],p["research_task_id"],
                 p["research_definition_id"],p["source_pdf_id"],p["requested_scope"],
                 p["default_scope"],p["selection_source"],p["selected_by"],p["selected_at"],
                 _json(p["evidence"]),p["producer_version"]))
        return p

    def create_anchor_children(self,anchor:dict[str,Any],*,logical_asset_id:str="",
                               research_definition_id:str="",definition_version:str="")->list[dict[str,Any]]:
        saved=[]
        with self.registry.connect() as c:
            for order,child in enumerate(anchor.get("child_rows") or []):
                # Child discovery must reject only *explicitly* non-current or
                # out-of-family rows.  A resolver's UNRESOLVED period label is
                # not evidence that a row is comparative-only; in real filings
                # such as Xinhua 2023 the source row has a current-period amount
                # and an explicit note reference.  Preserve it as a reviewable
                # Stage-B target instead of silently producing zero children.
                period_status = str(child.get("member_period_status") or "")
                if period_status in {
                    "COMPARATIVE_ONLY_LEGACY_MEMBER",
                    "OUTSIDE_FAMILY",
                    "NOT_A_FAMILY_MEMBER",
                }:
                    continue
                # A statement OCR/source row may include its note ordinal and
                # amount tokens.  It remains in ``source_line`` evidence, but
                # must never become the child concept used for heading lookup.
                raw=str(
                    child.get("raw_member_label")
                    or child.get("item")
                    or child.get("member_table")
                    or ""
                )
                canonical_concept_id=str(
                    child.get("canonical_concept_id")
                    or child.get("member_table")
                    or _norm(raw)
                )
                canonical_display_name=str(
                    child.get("canonical_display_name")
                    or child.get("member_display_name")
                    or canonical_concept_id
                )
                concept_aliases=list(dict.fromkeys([
                    canonical_display_name,
                    *(child.get("concept_aliases") or []),
                    raw,
                ]))
                child_id="ACHILD_"+uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{anchor['occurrence_id']}::{anchor.get('scope')}::{order}::{_norm(raw)}",
                ).hex
                # StatementFamilyMember is the sole amount source.  Support
                # legacy fields only as compatibility inputs; never infer from
                # a candidate note table or UI text.
                source_amounts=(
                    child.get("statement_amounts")
                    if child.get("statement_amounts") not in (None, "", [])
                    else child.get("statement_amount_normalized")
                    if child.get("statement_amount_normalized") not in (None, "", [])
                    else child.get("statement_amount_raw")
                    if child.get("statement_amount_raw") not in (None, "", [])
                    else child.get("values")
                    if child.get("values") not in (None, "", [])
                    else ([] if child.get("value") is None else [child.get("value")])
                )
                values=_amount_sequence(source_amounts)
                note_key=_note_reference_key(
                    child.get("note_reference_normalized") or child.get("note_reference")
                )
                p={
                    "anchor_child_id":child_id,"anchor_id":anchor["occurrence_id"],
                    "logical_asset_id":logical_asset_id,"raw_label":raw,
                    "normalized_label":_norm(raw),"canonical_concept_id":canonical_concept_id,
                    "canonical_display_name":canonical_display_name,
                    "concept_aliases":concept_aliases,"row_order":order,
                    "row_path":child.get("row_path") or f"{anchor.get('display_name','')}/{raw}",
                    "row_bbox":child.get("bbox") or {},"report_year":str(anchor.get("report_year") or ""),
                    "data_year":str(child.get("data_year") or anchor.get("report_year") or ""),
                    "statement_scope":anchor.get("scope") or "UNKNOWN","unit":child.get("unit") or (anchor.get("evidence") or {}).get("unit"),
                    "currency":"CNY","statement_amount_raw":values,
                    "statement_amount_normalized":values,
                    "candidate_note_pdf_page_index":child.get("candidate_note_pdf_page_index") or child.get("note_page"),
                    "candidate_note_printed_page":child.get("candidate_note_printed_page"),
                    "locator_method":child.get("locator_method") or "",
                    "inline_note_reference":note_key["normalized_note_reference"] or child.get("note_reference_normalized") or child.get("note_reference"),
                    "inline_note_reference_evidence":{
                        **(child.get("note_reference_evidence") or {}),
                        **note_key,
                        "amount_source_present":bool(values),
                        "member_period_status":period_status or "UNSPECIFIED",
                        "period_status_policy":(
                            "REVIEWABLE_UNRESOLVED_MEMBER"
                            if period_status == "UNRESOLVED" else "CURRENT_OR_UNSPECIFIED_MEMBER"
                        ),
                        "amount_source_row_id":child.get("source_row_id") or child.get("statement_family_member_id") or "",
                        "amount_source_page":child.get("statement_pdf_page_index") or anchor.get("statement_pdf_page_index"),
                        "amount_source_bbox":child.get("bbox") or {},
                        "candidate_note_pdf_page_index":child.get("candidate_note_pdf_page_index") or child.get("note_page"),
                        "candidate_note_printed_page":child.get("candidate_note_printed_page"),
                        "locator_method":child.get("locator_method") or "",
                        "canonical_display_name":canonical_display_name,
                        "source_line":child.get("source_line") or "",
                        "ocr_amount_candidates":list(child.get("ocr_amount_candidates") or []),
                        "ocr_amount_evidence_status":(
                            "DISPLAY_ONLY_UNCERTIFIED"
                            if child.get("ocr_amount_candidates") else "NOT_PRESENT"
                        ),
                        "direct_main_statement":bool(
                            child.get("direct_main_statement")
                        ),
                        "direct_capture_title":str(
                            child.get("direct_capture_title") or ""
                        ),
                        "direct_end_page":child.get("direct_end_page"),
                        "direct_portfolio_table":bool(
                            child.get("direct_portfolio_table")
                        ),
                        "portfolio_source_kind":str(
                            child.get("portfolio_source_kind") or ""
                        ),
                        "disclosure_topology":str(
                            child.get("disclosure_topology") or ""
                        ),
                        "physical_asset_id":str(
                            child.get("physical_asset_id") or ""
                        ),
                        "logical_block_id":str(
                            child.get("logical_block_id") or ""
                        ),
                        "classification_axis":str(
                            child.get("classification_axis") or ""
                        ),
                        "physical_bbox":dict(child.get("physical_bbox") or {}),
                        "applicable_members":list(
                            child.get("applicable_members") or []
                        ),
                        "not_applicable_members":list(
                            child.get("not_applicable_members") or []
                        ),
                        "reported_total_policy":str(
                            child.get("reported_total_policy") or ""
                        ),
                        "period_headers":list(
                            child.get("period_headers") or []
                        ),
                    },
                    "direct_main_statement":bool(child.get("direct_main_statement")),
                    "direct_capture_title":str(child.get("direct_capture_title") or ""),
                    "direct_end_page":child.get("direct_end_page"),
                    "direct_portfolio_table":bool(child.get("direct_portfolio_table")),
                    "portfolio_source_kind":str(child.get("portfolio_source_kind") or ""),
                    "disclosure_topology":str(child.get("disclosure_topology") or ""),
                    "physical_asset_id":str(child.get("physical_asset_id") or ""),
                    "logical_block_id":str(child.get("logical_block_id") or ""),
                    "classification_axis":str(child.get("classification_axis") or ""),
                    "physical_bbox":dict(child.get("physical_bbox") or {}),
                    "research_definition_id":research_definition_id,
                    "definition_version":definition_version,"producer_version":APP_VERSION,
                    "created_at":now_iso(),
                }
                c.execute("""INSERT INTO anchor_child_concepts(
                    anchor_child_id,anchor_id,logical_asset_id,raw_label,normalized_label,
                    canonical_concept_id,concept_aliases_json,row_order,row_path,row_bbox_json,
                    report_year,data_year,statement_scope,unit,currency,statement_amount_raw,
                    statement_amount_normalized,inline_note_reference,
                    inline_note_reference_evidence_json,research_definition_id,definition_version,
                    producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(anchor_id,row_order,statement_scope) DO UPDATE SET
                    raw_label=excluded.raw_label,normalized_label=excluded.normalized_label,
                    statement_amount_raw=excluded.statement_amount_raw,
                    statement_amount_normalized=excluded.statement_amount_normalized,
                    inline_note_reference=excluded.inline_note_reference,
                    inline_note_reference_evidence_json=excluded.inline_note_reference_evidence_json,
                    research_definition_id=excluded.research_definition_id,
                    definition_version=excluded.definition_version""",
                    (child_id,p["anchor_id"],logical_asset_id,raw,p["normalized_label"],
                     p["canonical_concept_id"],_json(p["concept_aliases"]),order,p["row_path"],
                     _json(p["row_bbox"]),p["report_year"],p["data_year"],p["statement_scope"],
                     p["unit"],p["currency"],_json(values),_json(values),p["inline_note_reference"],
                     _json(p["inline_note_reference_evidence"]),research_definition_id,
                     definition_version,APP_VERSION,p["created_at"]))
                saved.append(p)
        return saved

    def save_run(self,run:dict[str,Any],candidates:list[dict[str,Any]])->None:
        with self.registry.connect() as c:
            c.execute("""INSERT INTO child_discovery_runs(
                discovery_run_id,source_pdf_id,source_pdf_sha256,anchor_id,anchor_child_id,
                requested_scope,tiers_executed_json,tiers_skipped_json,early_stop_reason,
                candidate_count_by_tier_json,runtime_by_tier_json,metrics_json,status,
                producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run["discovery_run_id"],run["source_pdf_id"],run["source_pdf_sha256"],
                 run["anchor_id"],run["anchor_child_id"],run["requested_scope"],
                 _json(run["tiers_executed"]),_json(run["tiers_skipped"]),
                 run.get("early_stop_reason"),_json(run["candidate_count_by_tier"]),
                 _json(run["runtime_by_tier"]),_json(run["metrics"]),run["status"],
                 APP_VERSION,run["created_at"]))
            for p in candidates:
                c.execute("""INSERT INTO thin_child_table_candidates(
                    candidate_id,discovery_run_id,anchor_child_id,retrieval_tier,retrieval_method,
                    retrieval_priority,source_pdf_id,source_pdf_sha256,heading_id,raw_heading,
                    normalized_heading,section_id,section_type,start_page,end_page_hint,
                    heading_bbox_json,note_reference,statement_scope_hint,base_score,
                    warning_codes_json,hard_gate_summary_json,evidence_ref_ids_json,created_at,
                    producer_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["candidate_id"],p["discovery_run_id"],p["anchor_child_id"],
                     p["retrieval_tier"],p["retrieval_method"],p["retrieval_priority"],
                     p["source_pdf_id"],p["source_pdf_sha256"],p["heading_id"],p["raw_heading"],
                     p["normalized_heading"],p.get("section_id"),p["section_type"],p["start_page"],
                     p.get("end_page_hint"),_json(p.get("heading_bbox") or {}),
                     p.get("note_reference"),p.get("statement_scope_hint"),p["base_score"],
                     _json(p["warning_codes"]),_json(p["hard_gate_summary"]),
                     _json(p.get("evidence_ref_ids") or []),p["created_at"],APP_VERSION))
                for ev in p.get("evidence") or []:
                    c.execute("""INSERT INTO candidate_evidence(
                        evidence_id,candidate_id,evidence_type,evidence_source,scalar_value,
                        text_value,artifact_ref,bbox_ref,page_ref,confidence,producer_version,
                        created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("CEV_"+uuid.uuid4().hex,p["candidate_id"],ev["type"],ev["source"],
                         ev.get("scalar"),ev.get("text"),ev.get("artifact_ref"),
                         ev.get("bbox_ref"),str(ev.get("page_ref") or ""),ev.get("confidence",1),
                         APP_VERSION,now_iso()))

    def cached_discovery(self,*,source_pdf_sha256:str,anchor_child_id:str,
                         requested_scope:str)->dict[str,Any]|None:
        with self.registry.connect() as c:
            run=c.execute(
                """SELECT * FROM child_discovery_runs
                   WHERE source_pdf_sha256=? AND anchor_child_id=?
                   AND requested_scope=? AND producer_version=?
                   AND json_extract(metrics_json,'$.discovery_version')=?
                   ORDER BY created_at DESC LIMIT 1""",
                (
                    source_pdf_sha256,anchor_child_id,requested_scope,
                    APP_VERSION,DISCOVERY_VERSION,
                ),
            ).fetchone()
            if not run:return None
            candidates=[dict(x) for x in c.execute(
                """SELECT * FROM thin_child_table_candidates
                   WHERE discovery_run_id=? ORDER BY retrieval_priority,start_page""",
                (run["discovery_run_id"],)).fetchall()]
        run=dict(run)
        for key in ("tiers_executed","tiers_skipped","candidate_count_by_tier",
                    "runtime_by_tier","metrics"):
            run[key]=json.loads(run.pop(key+"_json") or ("[]" if key.endswith("ed") else "{}"))
        for row in candidates:
            for key in ("heading_bbox","warning_codes","hard_gate_summary","evidence_ref_ids"):
                row[key]=json.loads(row.pop(key+"_json") or ("[]" if key in {"warning_codes","evidence_ref_ids"} else "{}"))
            row["base_score"]=float(row["base_score"])
            row["evidence"]=[]
        run["metrics"]={**run["metrics"],"discovery_cache_hit":True}
        return {"run":run,"candidates":candidates}

    def _candidate_inventory_from_connection(
        self,c,candidate_id:str,
    )->dict[str,Any]|None:
        inventory_row=c.execute(
            """SELECT * FROM child_note_table_inventories
               WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        if not inventory_row:
            return None
        inventory=dict(inventory_row)
        inventory["scan_scope"]=json.loads(
            inventory.pop("scan_scope_json") or "{}"
        )
        inventory["evidence"]=json.loads(
            inventory.pop("evidence_json") or "{}"
        )
        logical_rows=c.execute(
            """SELECT * FROM child_logical_table_candidates
               WHERE note_table_inventory_candidate_id=?
               ORDER BY table_order""",
            (inventory["note_table_inventory_candidate_id"],),
        ).fetchall()
        logical_tables=[]
        for logical_row in logical_rows:
            logical=dict(logical_row)
            for field in ("bbox","signature","evidence"):
                logical[field]=json.loads(logical.pop(field+"_json") or "{}")
            logical["classification"]=logical["proposed_classification"]
            segment_rows=c.execute(
                """SELECT * FROM child_table_segment_candidates
                   WHERE logical_table_candidate_id=?
                   ORDER BY segment_order""",
                (logical["logical_table_candidate_id"],),
            ).fetchall()
            segments=[]
            for segment_row in segment_rows:
                segment=dict(segment_row)
                for field in (
                    "bbox","period_signature","header_signature",
                    "amount_lane_signature","evidence",
                ):
                    segment[field]=json.loads(segment.pop(field+"_json") or "{}")
                segment["classification"]=segment["proposed_classification"]
                segment["order"]=segment["segment_order"]
                segments.append(segment)
            logical["segments"]=segments
            logical_tables.append(logical)
        inventory["logical_tables"]=logical_tables
        return inventory

    def candidate_inventory(self,candidate_id:str)->dict[str,Any]|None:
        with self.registry.connect() as c:
            return self._candidate_inventory_from_connection(c,candidate_id)

    @staticmethod
    def _decode_resolution_case(row:Any)->dict[str,Any]:
        case=dict(row)
        for field,default in (
            ("machine_snapshot",{}),("allowed_logical_candidate_ids",[]),
            ("allowed_segment_candidate_ids",[]),("evidence",{}),
        ):
            case[field]=json.loads(
                case.pop(field+"_json") or _json(default)
            )
        return case

    def _open_unresolved_inventory_case_from_connection(
        self,c,candidate_id:str,
    )->dict[str,Any]|None:
        inventory=self._candidate_inventory_from_connection(c,candidate_id)
        if not inventory or (
            str(inventory.get("inventory_status") or "").upper()!="INCOMPLETE"
        ):
            return None
        machine_snapshot=dict(inventory)
        snapshot_sha256=_snapshot_sha256(machine_snapshot)
        logical_ids=[
            str(item["logical_table_candidate_id"])
            for item in machine_snapshot.get("logical_tables") or []
        ]
        segment_ids=[
            str(segment["segment_candidate_id"])
            for logical in machine_snapshot.get("logical_tables") or []
            for segment in logical.get("segments") or []
        ]
        thin=c.execute(
            """SELECT anchor_child_id,source_pdf_id,source_pdf_sha256,
                      discovery_run_id
               FROM thin_child_table_candidates WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        if not thin:
            raise ValueError("THIN_CHILD_TABLE_CANDIDATE_REQUIRED")
        inventory_id=str(
            inventory["note_table_inventory_candidate_id"]
        )
        resolution_case_id=_stable_candidate_id(
            "ICASE",inventory_id,snapshot_sha256,
        )
        existing=c.execute(
            """SELECT * FROM child_inventory_resolution_cases
               WHERE resolution_case_id=?""",
            (resolution_case_id,),
        ).fetchone()
        if existing:
            return self._decode_resolution_case(existing)
        c.execute(
            """UPDATE child_inventory_resolution_cases
               SET case_status='SUPERSEDED',
                   resolution_state='MACHINE_EVIDENCE_DRIFT',updated_at=?
               WHERE note_table_inventory_candidate_id=?
                 AND case_status='OPEN'
                 AND resolution_state='UNRESOLVED'""",
            (now_iso(),inventory_id),
        )
        now=now_iso()
        c.execute(
            """INSERT INTO child_inventory_resolution_cases(
               resolution_case_id,note_table_inventory_candidate_id,
               candidate_id,anchor_child_id,source_pdf_id,source_pdf_sha256,
               discovery_run_id,case_status,resolution_state,
               machine_snapshot_sha256,machine_snapshot_json,
               allowed_logical_candidate_ids_json,
               allowed_segment_candidate_ids_json,reason,evidence_json,
               producer_version,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,'OPEN','UNRESOLVED',?,?,?,?,?,?,?,?,?)""",
            (
                resolution_case_id,inventory_id,candidate_id,
                str(thin["anchor_child_id"] or ""),
                str(thin["source_pdf_id"] or ""),
                str(thin["source_pdf_sha256"] or ""),
                str(thin["discovery_run_id"] or ""),snapshot_sha256,
                _json(machine_snapshot),_json(logical_ids),_json(segment_ids),
                "PERSISTED_UNRESOLVED_NOTE_TABLE_INVENTORY",
                _json({
                    "inventory_status":inventory.get("inventory_status"),
                    "unresolved_table_count":inventory.get(
                        "unresolved_table_count"
                    ),
                }),APP_VERSION,now,now,
            ),
        )
        row=c.execute(
            """SELECT * FROM child_inventory_resolution_cases
               WHERE resolution_case_id=?""",
            (resolution_case_id,),
        ).fetchone()
        return self._decode_resolution_case(row)

    def unresolved_inventory_cases(
        self,*,anchor_child_id:str="",candidate_ids:list[str]|None=None,
    )->list[dict[str,Any]]:
        clauses=["case_status='OPEN'","resolution_state='UNRESOLVED'"]
        params:list[Any]=[]
        if anchor_child_id:
            clauses.append("anchor_child_id=?")
            params.append(anchor_child_id)
        ids=[str(value) for value in (candidate_ids or []) if str(value)]
        if ids:
            clauses.append("candidate_id IN ("+",".join("?" for _ in ids)+")")
            params.extend(ids)
        with self.registry.connect() as c:
            rows=c.execute(
                "SELECT * FROM child_inventory_resolution_cases WHERE "
                +" AND ".join(clauses)+" ORDER BY created_at",
                params,
            ).fetchall()
        return [self._decode_resolution_case(row) for row in rows]

    def ensure_unresolved_inventory_cases(
        self,*,anchor_child_id:str,candidate_ids:list[str],
    )->list[dict[str,Any]]:
        ids=sorted({str(value) for value in candidate_ids if str(value)})
        if not str(anchor_child_id or ""):
            return []
        if not ids:
            return self.unresolved_inventory_cases(
                anchor_child_id=anchor_child_id,
            )
        with self.registry.connect() as c:
            for candidate_id in ids:
                thin=c.execute(
                    """SELECT anchor_child_id FROM thin_child_table_candidates
                       WHERE candidate_id=?""",
                    (candidate_id,),
                ).fetchone()
                if not thin or str(thin["anchor_child_id"] or "")!=(
                    str(anchor_child_id)
                ):
                    continue
                self._open_unresolved_inventory_case_from_connection(
                    c,candidate_id,
                )
        return self.unresolved_inventory_cases(
            anchor_child_id=anchor_child_id,candidate_ids=ids,
        )

    def inventory_resolution_case(
        self,resolution_case_id:str,*,require_open:bool=False,
    )->dict[str,Any]|None:
        with self.registry.connect() as c:
            row=c.execute(
                """SELECT * FROM child_inventory_resolution_cases
                   WHERE resolution_case_id=?""",
                (str(resolution_case_id),),
            ).fetchone()
        if not row:
            return None
        case=self._decode_resolution_case(row)
        if require_open and (
            case["case_status"]!="OPEN"
            or case["resolution_state"]!="UNRESOLVED"
        ):
            raise PermissionError("OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED")
        return case

    @staticmethod
    def _normalise_adjudication_decisions(
        decisions:dict[str,Any],
    )->dict[str,list[dict[str,Any]]]:
        if not isinstance(decisions,dict):
            raise TypeError("INVENTORY_ADJUDICATION_DECISIONS_MUST_BE_OBJECT")
        allowed_root={"logical_tables","segments"}
        if set(decisions)-allowed_root:
            raise ValueError("ADJUDICATION_SEMANTIC_FIELDS_ONLY")
        logical_rows=decisions.get("logical_tables") or []
        segment_rows=decisions.get("segments") or []
        if not isinstance(logical_rows,list) or not isinstance(segment_rows,list):
            raise TypeError("INVENTORY_ADJUDICATION_DECISIONS_MUST_BE_LISTS")
        logical_allowed={"logical_table_candidate_id","classification"}
        segment_allowed={
            "segment_candidate_id","logical_table_candidate_id",
            "classification","continuation_of_segment_candidate_id",
        }
        normalised_logical=[];seen_logical=set()
        for raw in logical_rows:
            if not isinstance(raw,dict) or set(raw)-logical_allowed:
                raise ValueError("ADJUDICATION_SEMANTIC_FIELDS_ONLY")
            logical_id=str(raw.get("logical_table_candidate_id") or "").strip()
            classification=str(raw.get("classification") or "").strip().upper()
            if not logical_id or logical_id in seen_logical:
                raise ValueError("INVALID_ADJUDICATED_LOGICAL_CANDIDATE_ID")
            if classification not in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}:
                raise ValueError("INVALID_ADJUDICATED_LOGICAL_CLASSIFICATION")
            seen_logical.add(logical_id)
            normalised_logical.append({
                "logical_table_candidate_id":logical_id,
                "classification":classification,
            })
        normalised_segments=[];seen_segments=set()
        for raw in segment_rows:
            if not isinstance(raw,dict) or set(raw)-segment_allowed:
                raise ValueError("ADJUDICATION_SEMANTIC_FIELDS_ONLY")
            segment_id=str(raw.get("segment_candidate_id") or "").strip()
            logical_id=str(raw.get("logical_table_candidate_id") or "").strip()
            classification=str(raw.get("classification") or "").strip().upper()
            parent=str(
                raw.get("continuation_of_segment_candidate_id") or ""
            ).strip()
            if not segment_id or segment_id in seen_segments or not logical_id:
                raise ValueError("INVALID_ADJUDICATED_SEGMENT_CANDIDATE_ID")
            if classification not in {
                "PRIMARY_TABLE","SUPPLEMENTARY_TABLE","CONTINUATION_SEGMENT",
            }:
                raise ValueError("INVALID_ADJUDICATED_SEGMENT_CLASSIFICATION")
            if classification=="CONTINUATION_SEGMENT" and not parent:
                raise ValueError("ADJUDICATED_CONTINUATION_PARENT_REQUIRED")
            if classification!="CONTINUATION_SEGMENT" and parent:
                raise ValueError("ADJUDICATED_NON_CONTINUATION_PARENT_FORBIDDEN")
            seen_segments.add(segment_id)
            normalised_segments.append({
                "segment_candidate_id":segment_id,
                "logical_table_candidate_id":logical_id,
                "classification":classification,
                "continuation_of_segment_candidate_id":parent or None,
            })
        if not normalised_logical and not normalised_segments:
            raise ValueError("INVENTORY_ADJUDICATION_DECISIONS_REQUIRED")
        return {
            "logical_tables":normalised_logical,
            "segments":normalised_segments,
        }

    @staticmethod
    def _effective_inventory_snapshot(
        machine_snapshot:dict[str,Any],decisions:dict[str,list[dict[str,Any]]],
        *,adjudication_id:str,resolution_case_id:str,
    )->dict[str,Any]:
        effective=json.loads(_json(machine_snapshot))
        logical_decisions={
            item["logical_table_candidate_id"]:item["classification"]
            for item in decisions["logical_tables"]
        }
        segment_decisions={
            item["segment_candidate_id"]:item
            for item in decisions["segments"]
        }
        logical_tables=[];logical_by_id={};segments_by_logical={}
        for logical in effective.get("logical_tables") or []:
            logical_id=str(logical["logical_table_candidate_id"])
            prepared={**logical,"segments":[]}
            classification=str(
                logical_decisions.get(logical_id)
                or logical.get("classification")
                or logical.get("proposed_classification") or ""
            ).upper()
            if classification not in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}:
                raise ValueError("ADJUDICATION_LEAVES_UNRESOLVED_LOGICAL_TABLE")
            prepared["classification"]=classification
            prepared["proposed_classification"]=classification
            prepared["status"]="ADJUDICATED_READY_FOR_CERTIFICATION"
            logical_tables.append(prepared)
            logical_by_id[logical_id]=prepared
            segments_by_logical[logical_id]=[]
        for logical in effective.get("logical_tables") or []:
            logical_id=str(logical["logical_table_candidate_id"])
            for segment in logical.get("segments") or []:
                segment_id=str(segment["segment_candidate_id"])
                decision=segment_decisions.get(segment_id) or {}
                target_logical_id=str(
                    decision.get("logical_table_candidate_id")
                    or logical_id
                )
                prepared_segment={**segment}
                prepared_segment["logical_table_candidate_id"]=target_logical_id
                prepared_segment["classification"]=str(
                    decision.get("classification")
                    or segment.get("classification")
                    or segment.get("proposed_classification") or ""
                ).upper()
                prepared_segment["proposed_classification"]=(
                    prepared_segment["classification"]
                )
                if decision:
                    prepared_segment[
                        "continuation_of_segment_candidate_id"
                    ]=decision.get("continuation_of_segment_candidate_id")
                if target_logical_id not in segments_by_logical:
                    raise ValueError("ADJUDICATED_SEGMENT_TARGET_NOT_IN_INVENTORY")
                segments_by_logical[target_logical_id].append(prepared_segment)
        primary_count=0
        for logical in logical_tables:
            logical_id=str(logical["logical_table_candidate_id"])
            classification=str(logical["classification"])
            primary_count+=int(classification=="PRIMARY_TABLE")
            segments=sorted(
                segments_by_logical[logical_id],
                key=lambda item:(
                    int(item.get("start_page") or 0),
                    int(item.get("segment_order",item.get("order",0))),
                    str(item.get("segment_candidate_id") or ""),
                ),
            )
            if not segments:
                raise ValueError("ADJUDICATED_LOGICAL_TABLE_REQUIRES_SEGMENT")
            seen=set()
            for order,segment in enumerate(segments):
                segment_classification=str(segment.get("classification") or "")
                if order==0 and segment_classification=="UNRESOLVED":
                    segment_classification=classification
                if order==0 and segment_classification!=classification:
                    raise ValueError("ADJUDICATED_ROOT_SEGMENT_CLASSIFICATION_MISMATCH")
                if order>0 and segment_classification!="CONTINUATION_SEGMENT":
                    raise ValueError("ADJUDICATION_LEAVES_UNRESOLVED_SEGMENT_RELATION")
                parent=str(
                    segment.get("continuation_of_segment_candidate_id") or ""
                )
                if segment_classification=="CONTINUATION_SEGMENT":
                    if not parent or parent not in seen:
                        raise ValueError("ADJUDICATED_CONTINUATION_PARENT_INVALID")
                elif parent:
                    raise ValueError("ADJUDICATED_NON_CONTINUATION_PARENT_FORBIDDEN")
                segment["classification"]=segment_classification
                segment["proposed_classification"]=segment_classification
                segment["status"]="ADJUDICATED_READY_FOR_CERTIFICATION"
                segment["order"]=order
                segment["segment_order"]=order
                seen.add(str(segment["segment_candidate_id"]))
            logical["segments"]=segments
            logical["start_page"]=int(segments[0]["start_page"])
            logical["end_page"]=int(segments[-1]["end_page"])
        if primary_count!=1:
            raise ValueError("ADJUDICATED_INVENTORY_REQUIRES_ONE_PRIMARY_TABLE")
        scan_scope=dict(effective.get("scan_scope") or {})
        if not effective.get("next_note_boundary_page") and not bool(
            scan_scope.get("terminal_boundary_confirmed")
        ):
            raise PermissionError("MACHINE_BOUNDARY_EVIDENCE_REQUIRED")
        effective["logical_tables"]=logical_tables
        effective["logical_table_count"]=len(logical_tables)
        effective["unresolved_table_count"]=0
        effective["inventory_status"]="COMPLETE"
        effective["source_adjudication_id"]=adjudication_id
        effective["resolution_case_id"]=resolution_case_id
        effective["adjudication_overlay"]=decisions
        effective["machine_snapshot_sha256"]=_snapshot_sha256(machine_snapshot)
        return effective

    def adjudicate_inventory_case(
        self,resolution_case_id:str,*,decisions:dict[str,Any],
        reviewer:str,reason:str,
    )->dict[str,Any]:
        if not str(reviewer or "").strip():
            raise ValueError("INVENTORY_ADJUDICATION_REVIEWER_REQUIRED")
        if not str(reason or "").strip():
            raise ValueError("INVENTORY_ADJUDICATION_REASON_REQUIRED")
        normalised=self._normalise_adjudication_decisions(decisions)
        adjudication_id="IADJ_"+uuid.uuid4().hex
        with self.registry.connect() as c:
            case_row=c.execute(
                """SELECT * FROM child_inventory_resolution_cases
                   WHERE resolution_case_id=?""",
                (str(resolution_case_id),),
            ).fetchone()
            if not case_row:
                raise PermissionError("OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED")
            case=self._decode_resolution_case(case_row)
            if (
                case["case_status"]!="OPEN"
                or case["resolution_state"]!="UNRESOLVED"
            ):
                raise PermissionError("OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED")
            current=self._candidate_inventory_from_connection(
                c,str(case["candidate_id"])
            )
            if not current or _snapshot_sha256(current)!=(
                case["machine_snapshot_sha256"]
            ):
                raise PermissionError("MACHINE_INVENTORY_SNAPSHOT_DRIFT")
            allowed_logical=set(case["allowed_logical_candidate_ids"])
            allowed_segments=set(case["allowed_segment_candidate_ids"])
            for item in normalised["logical_tables"]:
                if item["logical_table_candidate_id"] not in allowed_logical:
                    raise PermissionError("LOGICAL_CANDIDATE_NOT_IN_INVENTORY_CASE")
            for item in normalised["segments"]:
                if item["segment_candidate_id"] not in allowed_segments:
                    raise PermissionError("SEGMENT_CANDIDATE_NOT_IN_INVENTORY_CASE")
                if item["logical_table_candidate_id"] not in allowed_logical:
                    raise PermissionError("LOGICAL_CANDIDATE_NOT_IN_INVENTORY_CASE")
                parent=item.get("continuation_of_segment_candidate_id")
                if parent and parent not in allowed_segments:
                    raise PermissionError("SEGMENT_PARENT_NOT_IN_INVENTORY_CASE")
            effective=self._effective_inventory_snapshot(
                case["machine_snapshot"],normalised,
                adjudication_id=adjudication_id,
                resolution_case_id=str(resolution_case_id),
            )
            effective_sha256=_snapshot_sha256(effective)
            now=now_iso()
            c.execute(
                """INSERT INTO child_inventory_adjudications(
                   adjudication_id,resolution_case_id,
                   note_table_inventory_candidate_id,candidate_id,reviewer,
                   reason,decisions_json,machine_snapshot_sha256,
                   effective_snapshot_sha256,effective_snapshot_json,
                   adjudication_status,producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,'ACCEPTED',?,?)""",
                (
                    adjudication_id,str(resolution_case_id),
                    case["note_table_inventory_candidate_id"],
                    case["candidate_id"],str(reviewer),str(reason),
                    _json(normalised),case["machine_snapshot_sha256"],
                    effective_sha256,_json(effective),APP_VERSION,now,
                ),
            )
            c.execute(
                """UPDATE child_inventory_resolution_cases
                   SET case_status='RESOLVED',
                       resolution_state='HUMAN_ADJUDICATED',updated_at=?
                   WHERE resolution_case_id=?
                     AND case_status='OPEN'
                     AND resolution_state='UNRESOLVED'""",
                (now,str(resolution_case_id)),
            )
            c.execute(
                """UPDATE child_mapping_review_queue
                   SET status='RESOLVED',updated_at=?
                   WHERE resolution_case_id=?""",
                (now,str(resolution_case_id)),
            )
        from v69_learning import propose_structural_learning_candidate
        learning=propose_structural_learning_candidate(
            self.registry,adjudication_id=adjudication_id,
        )
        return {
            "adjudication_id":adjudication_id,
            "resolution_case_id":str(resolution_case_id),
            "note_table_inventory_candidate_id":case[
                "note_table_inventory_candidate_id"
            ],
            "candidate_id":case["candidate_id"],
            "reviewer":str(reviewer),"reason":str(reason),
            "decisions":normalised,"machine_snapshot_sha256":case[
                "machine_snapshot_sha256"
            ],
            "effective_snapshot_sha256":effective_sha256,
            "effective_snapshot":effective,
            "adjudication_status":"ACCEPTED",
            "learning_candidate":learning,
            "created_at":now,
        }

    def _effective_inventory_from_connection(
        self,c,candidate_id:str,
    )->dict[str,Any]|None:
        row=c.execute(
            """SELECT * FROM child_inventory_adjudications
               WHERE candidate_id=? AND adjudication_status='ACCEPTED'
               ORDER BY created_at DESC LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        if not row:
            return None
        effective=json.loads(row["effective_snapshot_json"] or "{}")
        effective["source_adjudication_id"]=row["adjudication_id"]
        return effective

    def effective_candidate_inventory(
        self,candidate_id:str,
    )->dict[str,Any]|None:
        with self.registry.connect() as c:
            return self._effective_inventory_from_connection(c,candidate_id)

    def cached_enriched(self,candidate_id:str)->dict[str,Any]|None:
        with self.registry.connect() as c:
            row=c.execute(
                """SELECT e.*,t.*
                   FROM enriched_child_table_candidates e
                   JOIN thin_child_table_candidates t ON t.candidate_id=e.candidate_id
                   WHERE e.candidate_id=? AND e.enrichment_version=?
                   AND e.producer_version=?""",
                (candidate_id,ENRICHMENT_VERSION,APP_VERSION)).fetchone()
            inventory=self._candidate_inventory_from_connection(c,candidate_id)
            effective_inventory=self._effective_inventory_from_connection(
                c,candidate_id
            )
        if not row:return None
        p=dict(row)
        json_fields=(
            "container_page_range","possible_subtable_roles","scope_evidence",
            "period_evidence","unit_evidence","lightweight_header_signature",
            "lightweight_row_signature","amount_summary","reconciliation_candidates",
            "score_breakdown","hard_gate_results","positive_evidence","negative_evidence",
            "heading_bbox","warning_codes","hard_gate_summary","evidence_ref_ids",
        )
        for key in json_fields:
            p[key]=json.loads(p.pop(key+"_json") or ("[]" if key in {
                "container_page_range","possible_subtable_roles","lightweight_header_signature",
                "lightweight_row_signature","reconciliation_candidates","positive_evidence",
                "negative_evidence","warning_codes","evidence_ref_ids",
            } else "{}"))
        p["lightweight_table_presence"]=bool(p["lightweight_table_presence"])
        p["note_table_inventory"]=inventory
        p["effective_note_table_inventory"]=effective_inventory
        p["enrichment_cache_hit"]=True
        return p

    def _save_candidate_inventory(
        self,c,row:dict[str,Any],inventory:dict[str,Any],now:str,
    )->None:
        _assert_inventory_contains_no_amount_values(inventory)
        candidate_id=str(row["candidate_id"])
        if str(inventory.get("candidate_id") or candidate_id)!=candidate_id:
            raise ValueError("NOTE_TABLE_INVENTORY_CANDIDATE_MISMATCH")
        inventory_id=str(
            inventory.get("note_table_inventory_candidate_id") or ""
        ).strip()
        if not inventory_id:
            raise ValueError("NOTE_TABLE_INVENTORY_CANDIDATE_ID_REQUIRED")
        logical_tables=list(inventory.get("logical_tables") or [])
        if not logical_tables:
            raise ValueError("NOTE_TABLE_INVENTORY_LOGICAL_TABLES_REQUIRED")
        allowed_roots={"PRIMARY_TABLE","SUPPLEMENTARY_TABLE","UNRESOLVED"}
        allowed_segments={
            "PRIMARY_TABLE","SUPPLEMENTARY_TABLE",
            "CONTINUATION_SEGMENT","UNRESOLVED",
        }
        existing=c.execute(
            """SELECT note_table_inventory_candidate_id
               FROM child_note_table_inventories WHERE candidate_id=?""",
            (candidate_id,),
        ).fetchone()
        if existing and str(existing[0])!=inventory_id:
            raise ValueError("NOTE_TABLE_INVENTORY_CANDIDATE_ID_DRIFT")
        seen_logical=set(); seen_segments=set(); primary_count=0
        peer_count=int(inventory.get("peer_table_count") or 0)
        unresolved_count=0
        for table_order,logical in enumerate(logical_tables):
            logical_id=str(logical.get("logical_table_candidate_id") or "").strip()
            if not logical_id or logical_id in seen_logical:
                raise ValueError("INVALID_LOGICAL_TABLE_CANDIDATE_ID")
            seen_logical.add(logical_id)
            classification=str(
                logical.get("classification")
                or logical.get("proposed_classification") or ""
            ).strip().upper()
            if classification not in allowed_roots:
                raise ValueError(
                    f"UNSUPPORTED_LOGICAL_TABLE_CLASSIFICATION:{classification}"
                )
            primary_count+=int(classification=="PRIMARY_TABLE")
            logical_unresolved=classification=="UNRESOLVED"
            unresolved_count+=int(logical_unresolved)
            segments=list(logical.get("segments") or [])
            if not segments:
                raise ValueError("LOGICAL_TABLE_SEGMENT_CANDIDATES_REQUIRED")
            local_seen=set()
            for segment_order,segment in enumerate(segments):
                segment_id=str(segment.get("segment_candidate_id") or "").strip()
                if not segment_id or segment_id in seen_segments:
                    raise ValueError("INVALID_SEGMENT_CANDIDATE_ID")
                seen_segments.add(segment_id)
                segment_classification=str(
                    segment.get("classification")
                    or segment.get("proposed_classification") or ""
                ).strip().upper()
                if segment_classification not in allowed_segments:
                    raise ValueError(
                        "UNSUPPORTED_SEGMENT_CANDIDATE_CLASSIFICATION:"
                        f"{segment_classification}"
                    )
                if segment_classification=="UNRESOLVED" and not logical_unresolved:
                    unresolved_count+=1
                if segment_order==0 and segment_classification!=classification:
                    raise ValueError("LOGICAL_TABLE_ROOT_SEGMENT_CLASSIFICATION_MISMATCH")
                parent=str(
                    segment.get("continuation_of_segment_candidate_id") or ""
                ).strip()
                if segment_classification=="CONTINUATION_SEGMENT":
                    if not parent or parent not in local_seen:
                        raise ValueError("CONTINUATION_PARENT_NOT_PRECEDING_SAME_CANDIDATE")
                elif parent:
                    raise ValueError("NON_CONTINUATION_CANDIDATE_HAS_PARENT")
                local_seen.add(segment_id)
            expected=c.execute(
                """SELECT logical_table_candidate_id
                   FROM child_logical_table_candidates
                   WHERE candidate_id=? AND table_order=?""",
                (candidate_id,int(logical.get("table_order",table_order))),
            ).fetchone()
            if expected and str(expected[0])!=logical_id:
                raise ValueError("LOGICAL_TABLE_CANDIDATE_ID_DRIFT")
        inventory_status=str(
            inventory.get("inventory_status") or "INCOMPLETE"
        ).strip().upper()
        if inventory_status not in {"COMPLETE","INCOMPLETE"}:
            raise ValueError("UNSUPPORTED_NOTE_TABLE_INVENTORY_STATUS")
        if inventory_status=="COMPLETE" and primary_count!=1:
            raise ValueError("COMPLETE_NOTE_TABLE_INVENTORY_REQUIRES_ONE_PRIMARY_TABLE")
        if inventory_status=="INCOMPLETE" and primary_count>1:
            raise ValueError("INCOMPLETE_NOTE_TABLE_INVENTORY_ALLOWS_AT_MOST_ONE_PRIMARY_TABLE")
        scan_scope=dict(inventory.get("scan_scope") or {})
        next_boundary=inventory.get("next_note_boundary_page")
        terminal_confirmed=bool(scan_scope.get("terminal_boundary_confirmed"))
        if inventory_status=="COMPLETE" and (
            unresolved_count or (not next_boundary and not terminal_confirmed)
        ):
            raise ValueError("COMPLETE_NOTE_TABLE_INVENTORY_BOUNDARY_REQUIRED")
        c.execute("""INSERT INTO child_note_table_inventories(
            note_table_inventory_candidate_id,candidate_id,source_pdf_id,
            source_pdf_sha256,note_reference,note_title,scan_start_page,
            scan_end_page,next_note_boundary_page,scan_scope_json,
            logical_table_count,peer_table_count,unresolved_table_count,
            inventory_status,evidence_json,producer_version,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                source_pdf_id=excluded.source_pdf_id,
                source_pdf_sha256=excluded.source_pdf_sha256,
                note_reference=excluded.note_reference,note_title=excluded.note_title,
                scan_start_page=excluded.scan_start_page,
                scan_end_page=excluded.scan_end_page,
                next_note_boundary_page=excluded.next_note_boundary_page,
                scan_scope_json=excluded.scan_scope_json,
                logical_table_count=excluded.logical_table_count,
                peer_table_count=excluded.peer_table_count,
                unresolved_table_count=excluded.unresolved_table_count,
                inventory_status=excluded.inventory_status,
                evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",(
            inventory_id,candidate_id,
            inventory.get("source_pdf_id") or row.get("source_pdf_id") or "",
            inventory.get("source_pdf_sha256") or row.get("source_pdf_sha256") or "",
            inventory.get("note_reference") or row.get("note_reference") or "",
            inventory.get("note_title") or row.get("raw_heading") or "",
            int(inventory.get("scan_start_page") or row.get("start_page") or 1),
            int(inventory.get("scan_end_page") or row.get("start_page") or 1),
            int(next_boundary) if next_boundary else None,_json(scan_scope),
            sum(1 for item in logical_tables if str(
                item.get("classification") or item.get("proposed_classification")
            ).upper() in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}),
            peer_count,unresolved_count,inventory_status,
            _json(inventory.get("evidence") or {}),APP_VERSION,now,now,
        ))
        for table_order,logical in enumerate(logical_tables):
            logical_id=str(logical["logical_table_candidate_id"])
            classification=str(
                logical.get("classification")
                or logical.get("proposed_classification")
            ).upper()
            segments=list(logical["segments"])
            c.execute("""INSERT INTO child_logical_table_candidates(
                logical_table_candidate_id,note_table_inventory_candidate_id,
                candidate_id,table_order,proposed_classification,title,start_page,
                end_page,bbox_json,signature_json,evidence_json,confidence,status,
                producer_version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(logical_table_candidate_id) DO UPDATE SET
                    proposed_classification=excluded.proposed_classification,
                    title=excluded.title,start_page=excluded.start_page,
                    end_page=excluded.end_page,bbox_json=excluded.bbox_json,
                    signature_json=excluded.signature_json,
                    evidence_json=excluded.evidence_json,
                    confidence=excluded.confidence,status=excluded.status,
                    updated_at=excluded.updated_at""",(
                logical_id,inventory_id,candidate_id,
                int(logical.get("table_order",table_order)),classification,
                str(logical.get("title") or row.get("raw_heading") or ""),
                int(logical.get("start_page") or segments[0].get("start_page") or 1),
                int(logical.get("end_page") or segments[-1].get("end_page") or 1),
                _json(logical.get("bbox") or {}),
                _json(logical.get("signature") or {}),
                _json(logical.get("evidence") or {}),
                _confidence_value(logical.get("confidence")),
                str(logical.get("status") or (
                    "REVIEW_REQUIRED" if classification=="UNRESOLVED"
                    else "READY_FOR_CERTIFICATION"
                )),APP_VERSION,now,now,
            ))
            for segment_order,segment in enumerate(segments):
                segment_id=str(segment["segment_candidate_id"])
                segment_classification=str(
                    segment.get("classification")
                    or segment.get("proposed_classification")
                ).upper()
                segment_start=int(segment.get("start_page") or 1)
                segment_end=int(segment.get("end_page") or segment_start)
                c.execute("""INSERT INTO child_table_segment_candidates(
                    segment_candidate_id,logical_table_candidate_id,segment_order,
                    proposed_classification,start_page,end_page,bbox_json,
                    continuation_of_segment_candidate_id,period_signature_json,
                    header_signature_json,amount_lane_signature_json,evidence_json,
                    confidence,status,producer_version,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(segment_candidate_id) DO UPDATE SET
                        proposed_classification=excluded.proposed_classification,
                        start_page=excluded.start_page,end_page=excluded.end_page,
                        bbox_json=excluded.bbox_json,
                        continuation_of_segment_candidate_id=
                            excluded.continuation_of_segment_candidate_id,
                        period_signature_json=excluded.period_signature_json,
                        header_signature_json=excluded.header_signature_json,
                        amount_lane_signature_json=excluded.amount_lane_signature_json,
                        evidence_json=excluded.evidence_json,
                        confidence=excluded.confidence,status=excluded.status,
                        updated_at=excluded.updated_at""",(
                    segment_id,logical_id,
                    int(segment.get("order",segment.get("segment_order",segment_order))),
                    segment_classification,segment_start,segment_end,
                    _json(segment.get("bbox") or {}),
                    segment.get("continuation_of_segment_candidate_id") or None,
                    _json(segment.get("period_signature") or {}),
                    _json(segment.get("header_signature") or {}),
                    _json(segment.get("amount_lane_signature") or {}),
                    _json(segment.get("evidence") or {}),
                    _confidence_value(segment.get("confidence")),
                    str(segment.get("status") or (
                        "REVIEW_REQUIRED" if segment_classification=="UNRESOLVED"
                        else "READY_FOR_CERTIFICATION"
                    )),APP_VERSION,now,now,
                ))
        if inventory_status=="INCOMPLETE":
            self._open_unresolved_inventory_case_from_connection(c,candidate_id)
        else:
            c.execute(
                """UPDATE child_inventory_resolution_cases
                   SET case_status='SUPERSEDED',
                       resolution_state='MACHINE_RESOLVED',updated_at=?
                   WHERE note_table_inventory_candidate_id=?
                     AND case_status='OPEN'
                     AND resolution_state='UNRESOLVED'""",
                (now,inventory_id),
            )

    def save_enriched(
        self,row:dict[str,Any],inventory:dict[str,Any]|None=None,
    )->None:
        now=now_iso()
        with self.registry.connect() as c:
            c.execute("""INSERT OR REPLACE INTO enriched_child_table_candidates(
                candidate_id,container_page_range_json,possible_subtable_roles_json,
                scope_evidence_json,period_evidence_json,unit_evidence_json,
                lightweight_table_presence,lightweight_header_signature_json,
                lightweight_row_signature_json,amount_summary_json,
                reconciliation_candidates_json,certification_score,score_breakdown_json,
                hard_gate_results_json,positive_evidence_json,negative_evidence_json,
                enrichment_runtime_ms,enrichment_version,producer_version,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["candidate_id"],_json(row["container_page_range"]),
                 _json(row["possible_subtable_roles"]),_json(row["scope_evidence"]),
                 _json(row["period_evidence"]),_json(row["unit_evidence"]),
                 int(row["lightweight_table_presence"]),_json(row["lightweight_header_signature"]),
                 _json(row["lightweight_row_signature"]),_json(row["amount_summary"]),
                 _json(row["reconciliation_candidates"]),row["certification_score"],
                 _json(row["score_breakdown"]),_json(row["hard_gate_results"]),
                 _json(row["positive_evidence"]),_json(row["negative_evidence"]),
                 row["enrichment_runtime_ms"],ENRICHMENT_VERSION,APP_VERSION,now))
            if inventory is not None:
                self._save_candidate_inventory(c,row,inventory,now)

    def save_link_candidates(self,rows:list[dict[str,Any]])->None:
        with self.registry.connect() as c:
            for p in rows:
                c.execute("""INSERT OR REPLACE INTO child_table_link_candidates(
                    link_candidate_id,anchor_id,anchor_child_id,candidate_id,
                    logical_table_candidate_id,
                    proposed_member_table_id,proposed_subtable_role,proposed_relation_type,
                    statement_scope,report_year,retrieval_prior,evidence_score,penalty_score,
                    certification_score,score_breakdown_json,hard_gate_results_json,
                    reconciliation_relation,reconciliation_status,confidence,
                    blocking_warnings_json,ranking_position,is_recommended,is_preselected,
                    producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["link_candidate_id"],p["anchor_id"],p["anchor_child_id"],
                     p["candidate_id"],p.get("logical_table_candidate_id"),
                     p["proposed_member_table_id"],
                     p["proposed_subtable_role"],p["proposed_relation_type"],
                     p["statement_scope"],p.get("report_year"),p["retrieval_prior"],
                     p["evidence_score"],p["penalty_score"],p["certification_score"],
                     _json(p["score_breakdown"]),_json(p["hard_gate_results"]),
                     p.get("reconciliation_relation"),p.get("reconciliation_status"),
                     p["confidence"],_json(p["blocking_warnings"]),
                     p.get("ranking_position"),int(p["is_recommended"]),
                     int(p["is_preselected"]),APP_VERSION,now_iso()))

    def save_assignment(self,p:dict[str,Any])->dict[str,Any]:
        with self.registry.connect() as c:
            c.execute("""INSERT INTO global_child_assignments(
                assignment_id,anchor_id,statement_scope,decisions_json,conflicts_json,
                rejected_links_json,evidence_json,assignment_runtime_ms,producer_version,
                created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (p["assignment_id"],p["anchor_id"],p["statement_scope"],
                 _json(p["decisions"]),_json(p["conflicts"]),_json(p["rejected_links"]),
                 _json(p["evidence"]),p["assignment_runtime_ms"],APP_VERSION,now_iso()))
        return p

    def enqueue_child_review(self,*,anchor_id:str,anchor_child_id:str,
                             logical_asset_id:str,source_pdf_id:str,
                             statement_scope:str,candidate_ids:list[str],
                             resolution_case_id:str,
                             reason:str,evidence:dict[str,Any])->dict[str,Any]:
        now=now_iso(); queue_id="CMRQ_"+uuid.uuid4().hex
        with self.registry.connect() as c:
            case_row=c.execute(
                """SELECT * FROM child_inventory_resolution_cases
                   WHERE resolution_case_id=? AND anchor_child_id=?
                     AND case_status='OPEN'
                     AND resolution_state='UNRESOLVED'""",
                (str(resolution_case_id),anchor_child_id),
            ).fetchone()
            if not case_row:
                raise PermissionError(
                    "OPEN_UNRESOLVED_INVENTORY_CASE_REQUIRED"
                )
            case_candidate_id=str(case_row["candidate_id"] or "")
            candidate_ids=list(dict.fromkeys([
                case_candidate_id,
                *(str(value) for value in candidate_ids if str(value)),
            ]))
            existing=c.execute(
                """SELECT queue_id FROM child_mapping_review_queue
                   WHERE anchor_child_id=? AND statement_scope=?""",
                (anchor_child_id,statement_scope)).fetchone()
            if existing:queue_id=existing["queue_id"]
            c.execute(
                """INSERT INTO child_mapping_review_queue(
                   queue_id,anchor_id,anchor_child_id,logical_asset_id,source_pdf_id,
                   statement_scope,resolution_case_id,status,
                   primary_review_reason,candidate_ids_json,evidence_json,
                   producer_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?,?,?,?)
                   ON CONFLICT(anchor_child_id,statement_scope) DO UPDATE SET
                   resolution_case_id=excluded.resolution_case_id,status='PENDING',
                   primary_review_reason=excluded.primary_review_reason,
                   candidate_ids_json=excluded.candidate_ids_json,
                   evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                (queue_id,anchor_id,anchor_child_id,logical_asset_id,source_pdf_id,
                 statement_scope,str(resolution_case_id),reason,
                 _json(candidate_ids),_json(evidence),APP_VERSION,now,now))
        return {
            "queue_id":queue_id,"status":"PENDING","reason":reason,
            "resolution_case_id":str(resolution_case_id),
        }

    def child_review_queue(self,status:str="PENDING")->list[dict[str,Any]]:
        with self.registry.connect() as c:
            rows=[dict(x) for x in c.execute(
                """SELECT q.*,a.canonical_concept_id,a.raw_label
                   FROM child_mapping_review_queue q
                   JOIN anchor_child_concepts a ON a.anchor_child_id=q.anchor_child_id
                   WHERE q.status=? ORDER BY q.created_at""",(status,)).fetchall()]
        for row in rows:
            row["candidate_ids"]=json.loads(row.pop("candidate_ids_json") or "[]")
            row["evidence"]=json.loads(row.pop("evidence_json") or "{}")
        return rows

    def mapping_workspace(self,*,logical_asset_id:str="",anchor_id:str="")->list[dict[str,Any]]:
        clauses=[];params=[]
        if logical_asset_id:clauses.append("a.logical_asset_id=?");params.append(logical_asset_id)
        if anchor_id:clauses.append("a.anchor_id=?");params.append(anchor_id)
        sql="""SELECT a.*,l.link_candidate_id,l.candidate_id,l.proposed_member_table_id,
            l.proposed_subtable_role,l.proposed_relation_type,l.certification_score,
            l.score_breakdown_json,l.hard_gate_results_json,l.reconciliation_relation,
            l.reconciliation_status,l.blocking_warnings_json,l.ranking_position,
            l.is_recommended,l.is_preselected,t.retrieval_tier,t.retrieval_method,
            t.raw_heading,t.start_page,t.end_page_hint,t.note_reference,
            t.warning_codes_json,t.source_pdf_id
            FROM anchor_child_concepts a
            LEFT JOIN child_table_link_candidates l ON l.anchor_child_id=a.anchor_child_id
            LEFT JOIN thin_child_table_candidates t ON t.candidate_id=l.candidate_id"""
        # Evidence is append-only, but an operator must not review stale
        # candidates from an earlier discovery run beside the current result.
        # Keep the anchor row when no candidate exists; otherwise show only the
        # newest run for that exact AnchorChildConcept.
        clauses.append("""(t.discovery_run_id IS NULL OR t.discovery_run_id=(
            SELECT rr.discovery_run_id FROM child_discovery_runs rr
            WHERE rr.anchor_child_id=a.anchor_child_id
            ORDER BY rr.created_at DESC LIMIT 1
        ))""")
        sql+=" WHERE "+" AND ".join(clauses)
        sql+=" ORDER BY a.row_order,l.ranking_position"
        with self.registry.connect() as c:rows=[dict(x) for x in c.execute(sql,params).fetchall()]
        for row in rows:
            for field in ("score_breakdown_json","hard_gate_results_json","blocking_warnings_json","warning_codes_json"):
                row[field.removesuffix("_json")]=json.loads(row.pop(field) or ("[]" if "warnings" in field else "{}"))
        return rows

    @staticmethod
    def _normalise_certified_segments(
        certified_segments:list[dict[str,Any]]|None, *,
        certified_link_id:str,table_classification:str,
        reviewer:str,certified_at:str,
    )->list[dict[str,Any]]:
        if certified_segments is None:
            return []
        if not isinstance(certified_segments,list) or not certified_segments:
            raise ValueError("CERTIFIED_SEGMENT_MANIFEST_REQUIRED")
        allowed={"PRIMARY_TABLE","SUPPLEMENTARY_TABLE","CONTINUATION_SEGMENT"}
        prepared=[]
        for position,raw in enumerate(certified_segments):
            if not isinstance(raw,dict):
                raise TypeError("CERTIFIED_SEGMENT_MUST_BE_OBJECT")
            classification=str(raw.get("classification") or "").strip().upper()
            if classification not in allowed:
                raise ValueError(
                    f"UNSUPPORTED_CERTIFIED_SEGMENT_CLASSIFICATION:{classification}"
                )
            try:
                segment_order=int(raw.get("order",position))
                start_page=int(raw["start_page"])
                end_page=int(raw["end_page"])
                confidence=float(raw["confidence"])
            except (KeyError,TypeError,ValueError) as exc:
                raise ValueError("INVALID_CERTIFIED_SEGMENT_SCALAR_FIELDS") from exc
            if segment_order<0:
                raise ValueError("CERTIFIED_SEGMENT_ORDER_MUST_BE_NONNEGATIVE")
            if start_page<1 or end_page<start_page:
                raise ValueError("INVALID_CERTIFIED_SEGMENT_PAGE_RANGE")
            if not 0<=confidence<=1:
                raise ValueError("INVALID_CERTIFIED_SEGMENT_CONFIDENCE")
            payloads={}
            for field in (
                "bbox","header_signature","period_signature",
                "amount_lane_signature","evidence",
            ):
                value=raw.get(field) or {}
                if not isinstance(value,dict):
                    raise TypeError(
                        f"CERTIFIED_SEGMENT_{field.upper()}_MUST_BE_OBJECT"
                    )
                payloads[field]=dict(value)
            prepared.append({
                "certified_segment_id":str(
                    raw.get("certified_segment_id") or "CSEG_"+uuid.uuid4().hex
                ),
                "certified_link_id":certified_link_id,
                "order":segment_order,
                "classification":classification,
                "start_page":start_page,
                "end_page":end_page,
                "bbox":payloads["bbox"],
                "continuation_of_segment_id":str(
                    raw.get("continuation_of_segment_id") or ""
                ) or None,
                "header_signature":payloads["header_signature"],
                "period_signature":payloads["period_signature"],
                "amount_lane_signature":payloads["amount_lane_signature"],
                "confidence":confidence,
                "evidence":payloads["evidence"],
                "certification_status":"CERTIFIED",
                "reviewer":reviewer,
                "certified_at":certified_at,
                "producer_version":APP_VERSION,
            })
        orders=[item["order"] for item in prepared]
        segment_ids=[item["certified_segment_id"] for item in prepared]
        if len(set(orders))!=len(orders):
            raise ValueError("DUPLICATE_CERTIFIED_SEGMENT_ORDER")
        if len(set(segment_ids))!=len(segment_ids):
            raise ValueError("DUPLICATE_CERTIFIED_SEGMENT_ID")
        prepared.sort(key=lambda item:item["order"])
        if prepared[0]["classification"]!=table_classification:
            raise ValueError("FIRST_SEGMENT_CLASSIFICATION_MISMATCH")
        seen=set()
        for item in prepared:
            parent=item["continuation_of_segment_id"]
            if item["classification"]=="CONTINUATION_SEGMENT":
                if not parent:
                    raise ValueError("CONTINUATION_PARENT_REQUIRED")
                if parent not in seen:
                    raise ValueError(
                        "CONTINUATION_PARENT_NOT_PRECEDING_SAME_LINK"
                    )
            elif parent:
                raise ValueError("NON_CONTINUATION_SEGMENT_HAS_PARENT")
            seen.add(item["certified_segment_id"])
        return prepared

    def _segments_from_logical_table_candidate(
        self,logical_table_candidate_id:str, *, expected_candidate_id:str,
    )->tuple[dict[str,Any],list[dict[str,Any]]]:
        with self.registry.connect() as c:
            logical_row=c.execute(
                """SELECT * FROM child_logical_table_candidates
                   WHERE logical_table_candidate_id=?""",
                (logical_table_candidate_id,),
            ).fetchone()
            certified_inventory_row=c.execute(
                """SELECT ci.*
                   FROM certified_note_table_inventories ci
                   JOIN child_logical_table_candidates lt
                     ON lt.note_table_inventory_candidate_id=
                        ci.note_table_inventory_candidate_id
                   WHERE lt.logical_table_candidate_id=?
                     AND ci.certification_status='CERTIFIED'""",
                (logical_table_candidate_id,),
            ).fetchone() if logical_row else None
        if not logical_row:
            raise PermissionError("LOGICAL_TABLE_CANDIDATE_REQUIRED")
        logical=dict(logical_row)
        if str(logical["candidate_id"])!=str(expected_candidate_id):
            raise ValueError("LOGICAL_TABLE_CANDIDATE_LINK_MISMATCH")
        if str(logical.get("status") or "").upper() in {"REJECTED","ARCHIVED"}:
            raise PermissionError("LOGICAL_TABLE_CANDIDATE_NOT_CERTIFIABLE")
        if not certified_inventory_row:
            raise PermissionError("CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED")
        certified_inventory=dict(certified_inventory_row)
        if str(certified_inventory.get("inventory_status") or "").upper()!="COMPLETE":
            raise PermissionError("CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED")
        snapshot=json.loads(
            certified_inventory.get("inventory_snapshot_json") or "{}"
        )
        if not isinstance(snapshot,dict):
            raise ValueError("CERTIFIED_NOTE_TABLE_INVENTORY_SNAPSHOT_INVALID")
        snapshot_logical_tables=list(snapshot.get("logical_tables") or [])
        logical_matches=[
            item for item in snapshot_logical_tables
            if str(item.get("logical_table_candidate_id") or "")
            ==logical_table_candidate_id
        ]
        if len(logical_matches)!=1:
            raise PermissionError("LOGICAL_TABLE_NOT_IN_CERTIFIED_INVENTORY")
        logical_snapshot=dict(logical_matches[0])
        if str(logical_snapshot.get("candidate_id") or expected_candidate_id)!=str(
            expected_candidate_id
        ):
            raise ValueError("CERTIFIED_INVENTORY_CANDIDATE_LINK_MISMATCH")
        if str(logical_snapshot.get("status") or "").upper() in {
            "REJECTED","ARCHIVED","SUPERSEDED","REVIEW_REQUIRED",
        }:
            raise PermissionError("LOGICAL_TABLE_CANDIDATE_NOT_CERTIFIABLE")
        segment_rows=[
            dict(item) for item in (logical_snapshot.get("segments") or [])
            if isinstance(item,dict)
        ]
        segment_rows.sort(
            key=lambda item:int(item.get("segment_order",item.get("order",0)))
        )
        if not segment_rows:
            raise ValueError("LOGICAL_TABLE_CANDIDATE_SEGMENTS_REQUIRED")
        segment_id_map={
            str(row.get("segment_candidate_id") or ""):"CSEG_"+uuid.uuid4().hex
            for row in segment_rows
        }
        if "" in segment_id_map or len(segment_id_map)!=len(segment_rows):
            raise ValueError("INVALID_CERTIFIED_INVENTORY_SEGMENT_CANDIDATE_ID")
        segments=[]
        for row in segment_rows:
            source=dict(row)
            if str(source.get("status") or "").upper() in {
                "REJECTED","ARCHIVED","SUPERSEDED","REVIEW_REQUIRED",
            }:
                raise PermissionError("SEGMENT_CANDIDATE_NOT_CERTIFIABLE")
            source_parent=str(
                source.get("continuation_of_segment_candidate_id") or ""
            )
            if source_parent and source_parent not in segment_id_map:
                raise ValueError(
                    "CONTINUATION_PARENT_NOT_SAME_LOGICAL_TABLE_CANDIDATE"
                )
            raw_evidence=source.get("evidence")
            evidence=(
                dict(raw_evidence)
                if isinstance(raw_evidence,dict)
                else json.loads(source.get("evidence_json") or "{}")
            )
            if not isinstance(evidence,dict):
                raise ValueError("SEGMENT_CANDIDATE_EVIDENCE_MUST_BE_OBJECT")
            evidence={
                **evidence,
                "source_logical_table_candidate_id":logical_table_candidate_id,
                "source_segment_candidate_id":source["segment_candidate_id"],
            }
            segments.append({
                "certified_segment_id":segment_id_map[
                    str(source["segment_candidate_id"])
                ],
                "order":int(source.get("segment_order",source.get("order",0))),
                "classification":str(
                    source.get("classification")
                    or source.get("proposed_classification") or ""
                ).upper(),
                "start_page":source["start_page"],
                "end_page":source["end_page"],
                "bbox":dict(source.get("bbox") or {}),
                "continuation_of_segment_id":(
                    segment_id_map[source_parent] if source_parent else None
                ),
                "period_signature":dict(source.get("period_signature") or {}),
                "header_signature":dict(source.get("header_signature") or {}),
                "amount_lane_signature":dict(
                    source.get("amount_lane_signature") or {}
                ),
                "confidence":source["confidence"],
                "evidence":evidence,
            })
        logical_snapshot["note_table_inventory_candidate_id"]=(
            certified_inventory["note_table_inventory_candidate_id"]
        )
        logical_snapshot["proposed_classification"]=(
            logical_snapshot.get("proposed_classification")
            or logical_snapshot.get("classification")
        )
        return logical_snapshot,segments

    def certify_note_table_inventory(
        self,note_table_inventory_candidate_id:str,*,reviewer:str,method:str,
        reason:str="",evidence:dict[str,Any]|None=None,
        source_adjudication_id:str="",
    )->dict[str,Any]:
        inventory_candidate_id=str(note_table_inventory_candidate_id or "").strip()
        if not inventory_candidate_id:
            raise ValueError("NOTE_TABLE_INVENTORY_CANDIDATE_ID_REQUIRED")
        if not str(reviewer or "").strip():
            raise ValueError("NOTE_TABLE_INVENTORY_REVIEWER_REQUIRED")
        if not str(method or "").strip():
            raise ValueError("NOTE_TABLE_INVENTORY_CERTIFICATION_METHOD_REQUIRED")
        with self.registry.connect() as c:
            inventory_row=c.execute(
                """SELECT * FROM child_note_table_inventories
                   WHERE note_table_inventory_candidate_id=?""",
                (inventory_candidate_id,),
            ).fetchone()
            if not inventory_row:
                raise PermissionError("NOTE_TABLE_INVENTORY_CANDIDATE_REQUIRED")
            inventory=dict(inventory_row)
            adjudication_id=str(source_adjudication_id or "").strip()
            machine_complete=(
                str(inventory.get("inventory_status") or "").upper()=="COMPLETE"
                and int(inventory.get("unresolved_table_count") or 0)==0
            )
            if machine_complete and not adjudication_id:
                candidate_payload=self._candidate_inventory_from_connection(
                    c,str(inventory["candidate_id"])
                )
            else:
                if not adjudication_id:
                    if str(inventory.get("inventory_status") or "").upper()!="COMPLETE":
                        raise PermissionError(
                            "INCOMPLETE_NOTE_TABLE_INVENTORY_NOT_CERTIFIABLE"
                        )
                    raise PermissionError(
                        "UNRESOLVED_NOTE_TABLE_INVENTORY_NOT_CERTIFIABLE"
                    )
                adjudication_row=c.execute(
                    """SELECT * FROM child_inventory_adjudications
                       WHERE adjudication_id=?
                         AND note_table_inventory_candidate_id=?
                         AND adjudication_status='ACCEPTED'""",
                    (adjudication_id,inventory_candidate_id),
                ).fetchone()
                if not adjudication_row:
                    raise PermissionError(
                        "ACCEPTED_INVENTORY_ADJUDICATION_REQUIRED"
                    )
                candidate_payload=json.loads(
                    adjudication_row["effective_snapshot_json"] or "{}"
                )
                if (
                    str(candidate_payload.get("inventory_status") or "").upper()
                    !="COMPLETE"
                    or int(candidate_payload.get("unresolved_table_count") or 0)
                ):
                    raise PermissionError(
                        "ADJUDICATED_INVENTORY_NOT_CERTIFIABLE"
                    )
            logical_tables=list(
                (candidate_payload or {}).get("logical_tables") or []
            )
            certifiable=[
                item for item in logical_tables
                if str(
                    item.get("classification")
                    or item.get("proposed_classification") or ""
                ).upper() in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}
            ]
            if sum(
                str(
                    item.get("classification")
                    or item.get("proposed_classification") or ""
                ).upper()=="PRIMARY_TABLE"
                for item in certifiable
            )!=1:
                raise ValueError("CERTIFIED_INVENTORY_REQUIRES_ONE_PRIMARY_TABLE")
            if any(
                str(item.get("status") or "").upper() in {
                    "REJECTED","ARCHIVED","SUPERSEDED","REVIEW_REQUIRED",
                }
                for item in certifiable
            ):
                raise PermissionError("NOTE_TABLE_INVENTORY_REVIEW_INCOMPLETE")
            if any(
                str(
                    segment.get("classification")
                    or segment.get("proposed_classification") or ""
                ).upper()=="UNRESOLVED"
                or str(segment.get("status") or "").upper() in {
                    "REJECTED","ARCHIVED","SUPERSEDED","REVIEW_REQUIRED",
                }
                for item in certifiable
                for segment in item.get("segments") or []
            ):
                raise PermissionError("NOTE_TABLE_INVENTORY_REVIEW_INCOMPLETE")
            existing=c.execute(
                """SELECT * FROM certified_note_table_inventories
                   WHERE note_table_inventory_candidate_id=?""",
                (inventory_candidate_id,),
            ).fetchone()
            if existing:
                persisted=dict(existing)
                if str(persisted.get("certification_status") or "")!="CERTIFIED":
                    raise PermissionError("NOTE_TABLE_INVENTORY_CERTIFICATION_NOT_ACTIVE")
                persisted_adjudication=str(
                    persisted.get("source_adjudication_id") or ""
                )
                if adjudication_id and persisted_adjudication!=adjudication_id:
                    raise ValueError("CERTIFIED_INVENTORY_ADJUDICATION_MISMATCH")
                for field in ("logical_table_ids","inventory_snapshot"):
                    persisted[field]=json.loads(
                        persisted.pop(field+"_json") or ("[]" if field.endswith("ids") else "{}")
                    )
                return persisted
            now=now_iso()
            certified_inventory_id="CINV_"+uuid.uuid4().hex
            logical_ids=[
                str(item["logical_table_candidate_id"]) for item in certifiable
            ]
            snapshot={
                **dict(candidate_payload or {}),
                "certification_reason":str(reason or ""),
                "certification_evidence":dict(evidence or {}),
            }
            c.execute("""INSERT INTO certified_note_table_inventories(
                note_table_inventory_id,note_table_inventory_candidate_id,
                source_pdf_id,source_pdf_sha256,note_reference,note_title,
                scan_start_page,scan_end_page,next_note_boundary_page,
                logical_table_ids_json,inventory_snapshot_json,inventory_status,
                certification_method,certification_status,
                source_adjudication_id,reviewer,certified_at,
                producer_version,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                certified_inventory_id,inventory_candidate_id,
                inventory.get("source_pdf_id") or "",
                inventory.get("source_pdf_sha256") or "",
                inventory.get("note_reference") or "",
                inventory.get("note_title") or "",
                int(inventory.get("scan_start_page") or 1),
                int(inventory.get("scan_end_page") or 1),
                inventory.get("next_note_boundary_page"),_json(logical_ids),
                _json(snapshot),"COMPLETE",str(method),"CERTIFIED",
                adjudication_id or None,str(reviewer),now,APP_VERSION,now,
            ))
        return {
            "note_table_inventory_id":certified_inventory_id,
            "note_table_inventory_candidate_id":inventory_candidate_id,
            "logical_table_ids":logical_ids,
            "inventory_snapshot":snapshot,
            "inventory_status":"COMPLETE",
            "certification_method":str(method),
            "certification_status":"CERTIFIED",
            "source_adjudication_id":adjudication_id or None,
            "reviewer":str(reviewer),"certified_at":now,
            "producer_version":APP_VERSION,"created_at":now,
        }

    def certify(self,link:dict[str,Any],*,reviewer:str,method:str,reason:str="",
                certified_segments:list[dict[str,Any]]|None=None)->dict[str,Any]:
        logical_table_candidate_id=str(
            link.get("logical_table_candidate_id") or ""
        ).strip()
        if certified_segments is not None:
            raise PermissionError(
                "CERTIFIED_SEGMENTS_MUST_PROMOTE_DISCOVERED_CANDIDATES"
            )
        if not logical_table_candidate_id:
            raise PermissionError("LOGICAL_TABLE_CANDIDATE_REQUIRED")
        logical_candidate,certified_segments=(
            self._segments_from_logical_table_candidate(
                logical_table_candidate_id,
                expected_candidate_id=str(link.get("candidate_id") or ""),
            )
        )
        inventory_candidate_id=str(
            logical_candidate.get("note_table_inventory_candidate_id") or ""
        ).strip()
        if not inventory_candidate_id:
            raise PermissionError("CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED")
        with self.registry.connect() as c:
            certified_inventory_row=c.execute(
                """SELECT * FROM certified_note_table_inventories
                   WHERE note_table_inventory_candidate_id=?
                     AND certification_status='CERTIFIED'""",
                (inventory_candidate_id,),
            ).fetchone()
            existing_link=c.execute(
                """SELECT * FROM certified_child_table_links
                   WHERE logical_table_candidate_id=?
                     AND certification_status='CERTIFIED'
                   ORDER BY certified_at DESC LIMIT 1""",
                (logical_table_candidate_id,),
            ).fetchone()
        if not certified_inventory_row:
            raise PermissionError("CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED")
        certified_inventory=dict(certified_inventory_row)
        certified_logical_ids=json.loads(
            certified_inventory.get("logical_table_ids_json") or "[]"
        )
        if logical_table_candidate_id not in certified_logical_ids:
            raise PermissionError("LOGICAL_TABLE_NOT_IN_CERTIFIED_INVENTORY")
        certified_inventory_id=str(
            certified_inventory.get("note_table_inventory_id") or ""
        ).strip()
        caller_inventory_id=str(
            link.get("note_table_inventory_id") or ""
        ).strip()
        if caller_inventory_id and caller_inventory_id!=certified_inventory_id:
            raise ValueError("NOTE_TABLE_INVENTORY_ID_MISMATCH")
        caller_inventory_status=str(
            link.get("note_table_inventory_status") or ""
        ).strip().upper()
        if caller_inventory_status and caller_inventory_status!="COMPLETE":
            raise ValueError("NOTE_TABLE_INVENTORY_STATUS_MISMATCH")
        if existing_link:
            persisted=dict(existing_link)
            target=self.certified_target(str(persisted["certified_link_id"]))
            persisted["certified_segments"]=target["certified_segments"]
            return persisted
        certified_id="CLINK_"+uuid.uuid4().hex; now=now_iso()
        proposed_classification=str(
            logical_candidate.get("proposed_classification") or ""
        ).strip().upper()
        table_classification=str(
            link.get("table_classification")
            or proposed_classification
            or "PRIMARY_TABLE"
        ).strip().upper()
        if proposed_classification and table_classification!=proposed_classification:
            raise ValueError("LOGICAL_TABLE_CLASSIFICATION_MISMATCH")
        if table_classification not in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}:
            raise ValueError(
                f"UNSUPPORTED_CERTIFIED_TABLE_CLASSIFICATION:{table_classification}"
            )
        logical_table_id=str(
            link.get("logical_table_id")
            or logical_table_candidate_id
            or link.get("member_table_id")
            or ""
        ).strip()
        if not logical_table_id:
            raise ValueError("LOGICAL_TABLE_ID_REQUIRED")
        normalised_segments=self._normalise_certified_segments(
            certified_segments,certified_link_id=certified_id,
            table_classification=table_classification,reviewer=reviewer,
            certified_at=now,
        )
        manifest_status="CERTIFIED_SEGMENT_MANIFEST"
        inventory_id=str(
            certified_inventory.get("note_table_inventory_id")
            or link.get("note_table_inventory_id") or ""
        ).strip()
        caller_inventory_id=str(
            link.get("note_table_inventory_id") or ""
        ).strip()
        if caller_inventory_id and inventory_id!=caller_inventory_id:
            raise ValueError("NOTE_TABLE_INVENTORY_ID_MISMATCH")
        inventory_status=str(
            certified_inventory.get("inventory_status")
            or link.get("note_table_inventory_status") or ""
        ).strip().upper()
        caller_inventory_status=str(
            link.get("note_table_inventory_status") or ""
        ).strip().upper()
        if caller_inventory_status and caller_inventory_status!=inventory_status:
            raise ValueError("NOTE_TABLE_INVENTORY_STATUS_MISMATCH")
        if inventory_status!="COMPLETE" or not inventory_id:
            raise PermissionError("CERTIFIED_NOTE_TABLE_INVENTORY_REQUIRED")
        p={**link,"certified_link_id":certified_id,"certification_method":method,
           "certification_status":"CERTIFIED","reviewer":reviewer,"certified_at":now,
           "logical_table_id":logical_table_id,
           "table_classification":table_classification,
           "segment_manifest_status":manifest_status,
           "note_table_inventory_id":inventory_id,
           "note_table_inventory_status":inventory_status,
           "logical_table_candidate_id":logical_table_candidate_id or None,
           "certified_segments":normalised_segments}
        with self.registry.connect() as c:
            candidate_context=c.execute(
                """SELECT source_pdf_id,note_reference
                   FROM thin_child_table_candidates WHERE candidate_id=?""",
                (p["candidate_id"],),
            ).fetchone()
            if inventory_id and (
                not candidate_context or not candidate_context["note_reference"]
            ):
                raise ValueError("NOTE_TABLE_INVENTORY_NOTE_CONTEXT_REQUIRED")
            if inventory_id:
                note_ordinal=_leaf_note_ordinal(
                    str(candidate_context["note_reference"])
                )
                existing_inventory_ids={
                    str(row["note_table_inventory_id"])
                    for row in c.execute(
                        """SELECT DISTINCT l.note_table_inventory_id
                                  ,t.note_reference
                           FROM certified_child_table_links l
                           JOIN thin_child_table_candidates t
                             ON t.candidate_id=l.candidate_id
                           WHERE t.source_pdf_id=?
                             AND l.certification_status='CERTIFIED'
                             AND COALESCE(l.note_table_inventory_id,'')<>''""",
                        (candidate_context["source_pdf_id"],),
                    ).fetchall()
                    if _leaf_note_ordinal(str(row["note_reference"] or ""))
                    ==note_ordinal
                }
                if existing_inventory_ids-{inventory_id}:
                    raise ValueError("NOTE_TABLE_INVENTORY_ID_MISMATCH")
            c.execute("""INSERT INTO certified_child_table_links(
                certified_link_id,research_project_id,research_task_id,anchor_id,
                anchor_child_id,candidate_id,link_candidate_id,table_family_id,
                member_table_id,subtable_role,relation_type,statement_scope,report_year,
                data_year,certification_method,certification_status,score_snapshot_json,
                evidence_snapshot_json,reconciliation_result_json,recommended_candidate_id,
                selected_candidate_id,alternative_candidates_json,reviewer,certified_at,
                research_definition_id,definition_version,producer_version,
                logical_table_id,table_classification,segment_manifest_status,
                note_table_inventory_id,note_table_inventory_status,
                logical_table_candidate_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (certified_id,p.get("research_project_id"),p.get("research_task_id"),
                 p["anchor_id"],p["anchor_child_id"],p["candidate_id"],
                 p["link_candidate_id"],p["table_family_id"],p["member_table_id"],
                 p["subtable_role"],p["relation_type"],p["statement_scope"],
                 p.get("report_year"),p.get("data_year"),method,"CERTIFIED",
                 _json(p.get("score_snapshot") or {}),_json(p.get("evidence_snapshot") or {}),
                 _json(p.get("reconciliation_result") or {}),
                 p.get("recommended_candidate_id"),p["selected_candidate_id"],
                 _json(p.get("alternative_candidates") or []),reviewer,now,
                 p.get("research_definition_id"),p.get("definition_version"),APP_VERSION,
                 logical_table_id,table_classification,manifest_status,
                 inventory_id,inventory_status,
                 logical_table_candidate_id or None))
            for segment in normalised_segments:
                c.execute("""INSERT INTO certified_child_table_segments(
                    certified_segment_id,certified_link_id,"order",classification,
                    start_page,end_page,bbox_json,continuation_of_segment_id,
                    header_signature_json,period_signature_json,
                    amount_lane_signature_json,confidence,evidence_json,
                    certification_status,reviewer,certified_at,producer_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    segment["certified_segment_id"],certified_id,segment["order"],
                    segment["classification"],segment["start_page"],segment["end_page"],
                    _json(segment["bbox"]),segment["continuation_of_segment_id"],
                    _json(segment["header_signature"]),
                    _json(segment["period_signature"]),
                    _json(segment["amount_lane_signature"]),segment["confidence"],
                    _json(segment["evidence"]),"CERTIFIED",reviewer,now,APP_VERSION,
                ))
            c.execute("""INSERT INTO child_mapping_review_records(
                review_record_id,anchor_child_id,action,selected_candidate_id,
                rejected_candidates_json,reason,reviewer,evidence_json,producer_version,
                created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("CMREV_"+uuid.uuid4().hex,p["anchor_child_id"],method,p["candidate_id"],
                 _json(p.get("alternative_candidates") or []),reason,reviewer,
                 _json({"link_candidate_id":p["link_candidate_id"],
                        "logical_table_id":logical_table_id,
                        "table_classification":table_classification,
                        "certified_segment_ids":[
                            item["certified_segment_id"] for item in normalised_segments
                        ],"note_table_inventory_id":inventory_id,
                        "note_table_inventory_status":inventory_status,
                        "logical_table_candidate_id":logical_table_candidate_id}),APP_VERSION,now))
            c.execute(
                """UPDATE child_mapping_review_queue
                   SET status='RESOLVED',updated_at=?
                   WHERE anchor_child_id=? AND statement_scope=?""",
                (now,p["anchor_child_id"],p["statement_scope"]))
        return p

    def review_mapping(self,anchor_child_id:str,action:str,*,reviewer:str,
                       selected_candidate_id:str="",reason:str="",
                       rejected_candidates:list[str]|None=None,
                       evidence:dict[str,Any]|None=None)->dict[str,Any]:
        if str(action or "").upper()=="MANUAL_ADD_LINK":
            raise PermissionError("MANUAL_ADD_LINK_FORBIDDEN")
        raise PermissionError("INVENTORY_ADJUDICATION_OVERLAY_REQUIRED")

    def certify_direct_main_statement(
        self,
        anchor: dict[str, Any],
        child: dict[str, Any],
        member_contract: dict[str, Any],
        *,
        reviewer: str = "SYSTEM_REGISTRY",
    ) -> dict[str, Any]:
        """Materialise a reviewed primary statement through the same link owner.

        A main statement has no financial-note container, so the inventory
        fields are explicitly ``NOT_APPLICABLE`` rather than fabricated.  The
        target is nevertheless a persisted ``CertifiedChildTableLink`` with a
        single certified physical segment and therefore enters the normal
        CaptureRequest/Capture/Canonical/Merge path.
        """
        evidence = dict(child.get("inline_note_reference_evidence") or {})
        if not bool(child.get("direct_main_statement") or evidence.get("direct_main_statement") or member_contract.get("direct_main_statement")):
            raise PermissionError("DIRECT_MAIN_STATEMENT_CONTRACT_REQUIRED")
        source_pdf_id = str(anchor.get("pdf_id") or "").strip()
        source_pdf = Path(source_pdf_id)
        if not source_pdf.is_file():
            raise PermissionError("DIRECT_MAIN_STATEMENT_SOURCE_PDF_REQUIRED")
        page = child.get("candidate_note_pdf_page_index") or anchor.get("statement_pdf_page_index")
        if not str(page or "").isdigit() or int(page) < 1:
            raise ValueError("DIRECT_MAIN_STATEMENT_PAGE_REQUIRED")
        page = int(page)
        end_page = child.get("direct_end_page") or evidence.get("direct_end_page") or page
        if not str(end_page or "").isdigit() or int(end_page) < page:
            raise ValueError("DIRECT_MAIN_STATEMENT_END_PAGE_INVALID")
        end_page = int(end_page)
        title = str(
            child.get("direct_capture_title")
            or evidence.get("direct_capture_title")
            or anchor.get("source_table_title")
            or member_contract.get("canonical_title")
            or child.get("canonical_display_name")
            or child.get("raw_label")
            or ""
        ).strip()
        if not title:
            raise ValueError("DIRECT_MAIN_STATEMENT_TITLE_REQUIRED")
        anchor_id = str(anchor.get("occurrence_id") or "")
        child_id = str(child.get("anchor_child_id") or "")
        if not anchor_id or not child_id:
            raise ValueError("DIRECT_MAIN_STATEMENT_ANCHOR_CHILD_REQUIRED")
        family_id = str(anchor.get("table_family") or anchor.get("table_family_id") or "")
        member_id = str(member_contract.get("member_table_id") or child.get("canonical_concept_id") or "")
        scope = str(child.get("statement_scope") or anchor.get("scope") or "")
        if scope not in {"CONSOLIDATED", "PARENT_COMPANY"}:
            raise ValueError("DIRECT_MAIN_STATEMENT_SCOPE_REQUIRED")
        digest = _sha(source_pdf)
        now = now_iso()
        with self.registry.connect() as c:
            existing = c.execute(
                """SELECT * FROM certified_child_table_links
                   WHERE anchor_id=? AND anchor_child_id=?
                     AND certification_status='CERTIFIED'
                     AND relation_type='DIRECT_MAIN_STATEMENT_WHOLE_TABLE'
                   ORDER BY certified_at DESC LIMIT 1""",
                (anchor_id, child_id),
            ).fetchone()
            if existing:
                return dict(existing)
            run_id = "CDRUN_" + uuid.uuid4().hex
            candidate_id = "TCAND_" + uuid.uuid4().hex
            link_candidate_id = "LKC_" + uuid.uuid4().hex
            certified_link_id = "CLINK_" + uuid.uuid4().hex
            segment_id = "CSEG_" + uuid.uuid4().hex
            c.execute(
                """INSERT INTO child_discovery_runs(
                   discovery_run_id,source_pdf_id,source_pdf_sha256,anchor_id,anchor_child_id,
                   requested_scope,tiers_executed_json,tiers_skipped_json,early_stop_reason,
                   candidate_count_by_tier_json,runtime_by_tier_json,metrics_json,status,
                   producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, source_pdf_id, digest, anchor_id, child_id, scope,
                 _json(["DIRECT_MAIN_STATEMENT"]), _json([]), None, _json({"DIRECT_MAIN_STATEMENT": 1}),
                 _json({}), _json({"strategy": "DIRECT_MAIN_STATEMENT_TABLE"}), "COMPLETE", APP_VERSION, now),
            )
            c.execute(
                """INSERT INTO thin_child_table_candidates(
                   candidate_id,discovery_run_id,anchor_child_id,retrieval_tier,retrieval_method,retrieval_priority,
                   source_pdf_id,source_pdf_sha256,heading_id,raw_heading,normalized_heading,section_id,section_type,
                   start_page,end_page_hint,heading_bbox_json,note_reference,statement_scope_hint,base_score,
                   warning_codes_json,hard_gate_summary_json,evidence_ref_ids_json,created_at,producer_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (candidate_id, run_id, child_id, "DIRECT_MAIN_STATEMENT", "DIRECT_MAIN_STATEMENT_CERTIFIED_ANCHOR", 1,
                 source_pdf_id, digest, "PRIMARY_STATEMENT::" + anchor_id, title, _norm(title),
                 "PRIMARY_FINANCIAL_STATEMENTS", "PRIMARY_FINANCIAL_STATEMENT", page, end_page, _json({}), "", scope,
                 1.0, _json([]), _json({"certified_anchor": True, "same_page_primary_statement": True}), _json([]), now, APP_VERSION),
            )
            c.execute(
                """INSERT INTO child_table_link_candidates(
                   link_candidate_id,anchor_id,anchor_child_id,candidate_id,logical_table_candidate_id,
                   proposed_member_table_id,proposed_subtable_role,proposed_relation_type,statement_scope,report_year,
                   retrieval_prior,evidence_score,penalty_score,certification_score,score_breakdown_json,
                   hard_gate_results_json,reconciliation_relation,reconciliation_status,confidence,
                   blocking_warnings_json,ranking_position,is_recommended,is_preselected,producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (link_candidate_id, anchor_id, child_id, candidate_id, None, member_id,
                 "PRIMARY_MAIN_STATEMENT_TABLE", "DIRECT_MAIN_STATEMENT_WHOLE_TABLE", scope, child.get("report_year"),
                 1.0, 1.0, 0.0, 1.0, _json({"strategy": "DIRECT_MAIN_STATEMENT_TABLE"}),
                 _json({"certified_anchor": True, "same_page_primary_statement": True}),
                 "NOT_APPLICABLE", "NOT_APPLICABLE", 1.0, _json([]), 1, 1, 1, APP_VERSION, now),
            )
            score_snapshot = _json({"certification_score": 1.0, "strategy": "DIRECT_MAIN_STATEMENT_TABLE"})
            evidence_snapshot = _json({
                "anchor_occurrence_id": anchor_id,
                "direct_main_statement": True,
                "direct_capture_title": title,
                "main_statement_page": page,
                "main_statement_end_page": end_page,
                "anchor_note_reference": "",
            })
            c.execute(
                """INSERT INTO certified_child_table_links(
                   certified_link_id,research_project_id,research_task_id,anchor_id,anchor_child_id,candidate_id,
                   link_candidate_id,table_family_id,member_table_id,subtable_role,relation_type,statement_scope,
                   report_year,data_year,certification_method,certification_status,score_snapshot_json,evidence_snapshot_json,
                   reconciliation_result_json,recommended_candidate_id,selected_candidate_id,alternative_candidates_json,
                   reviewer,certified_at,research_definition_id,definition_version,producer_version,logical_table_id,
                   table_classification,segment_manifest_status,note_table_inventory_id,note_table_inventory_status,
                   logical_table_candidate_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (certified_link_id, anchor.get("research_project_id"), anchor.get("research_task_id"), anchor_id, child_id, candidate_id,
                 link_candidate_id, family_id, member_id, "PRIMARY_MAIN_STATEMENT_TABLE", "DIRECT_MAIN_STATEMENT_WHOLE_TABLE", scope,
                 child.get("report_year"), child.get("data_year"), "DIRECT_MAIN_STATEMENT_CERTIFIED_ANCHOR", "CERTIFIED", score_snapshot,
                 evidence_snapshot, _json({"status": "NOT_APPLICABLE"}), link_candidate_id, candidate_id, _json([]), reviewer, now,
                 child.get("research_definition_id"), child.get("definition_version"), APP_VERSION, member_id,
                 "PRIMARY_TABLE", "DIRECT_MAIN_STATEMENT_SINGLE_SEGMENT", "", "NOT_APPLICABLE_DIRECT_MAIN_STATEMENT", None),
            )
            c.execute(
                """INSERT INTO certified_child_table_segments(
                   certified_segment_id,certified_link_id,"order",classification,start_page,end_page,bbox_json,
                   continuation_of_segment_id,header_signature_json,period_signature_json,amount_lane_signature_json,
                   confidence,evidence_json,certification_status,reviewer,certified_at,producer_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (segment_id, certified_link_id, 0, "PRIMARY_TABLE", page, end_page, _json({}), None,
                 _json({"title": title}), _json({}), _json({}), 1.0,
                 _json({"strategy": "DIRECT_MAIN_STATEMENT_TABLE", "same_page_as_anchor": True}),
                 "CERTIFIED", reviewer, now, APP_VERSION),
            )
            c.execute(
                """INSERT INTO child_mapping_review_records(
                   review_record_id,anchor_child_id,action,selected_candidate_id,rejected_candidates_json,reason,
                   reviewer,evidence_json,producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("CMREV_" + uuid.uuid4().hex, child_id, "DIRECT_MAIN_STATEMENT_CERTIFIED_ANCHOR", candidate_id, _json([]),
                 "已认证主表整表，未创建附注容器", reviewer, evidence_snapshot, APP_VERSION, now),
            )
        return {
            "certified_link_id": certified_link_id, "anchor_id": anchor_id, "anchor_child_id": child_id,
            "candidate_id": candidate_id, "link_candidate_id": link_candidate_id, "table_family_id": family_id,
            "member_table_id": member_id, "statement_scope": scope, "report_year": child.get("report_year"),
            "research_definition_id": child.get("research_definition_id"), "definition_version": child.get("definition_version"),
            "subtable_role": "PRIMARY_MAIN_STATEMENT_TABLE", "relation_type": "DIRECT_MAIN_STATEMENT_WHOLE_TABLE",
            "certification_status": "CERTIFIED", "direct_main_statement": True,
        }

    def certify_direct_portfolio_table(
        self,
        anchor: dict[str, Any],
        child: dict[str, Any],
        member_contract: dict[str, Any],
        *,
        reviewer: str = "SYSTEM_REGISTRY",
    ) -> dict[str, Any]:
        """Certify one directly disclosed portfolio physical table.

        This deliberately bypasses financial-note retrieval and inventory
        inference, while still producing the same CertifiedChildTableLink and
        certified-segment records consumed by the existing Capture pipeline.
        Compound-table logical axes share one physical link; same-page
        separate tables retain separate physical links.
        """
        evidence = dict(child.get("inline_note_reference_evidence") or {})
        if not bool(
            child.get("direct_portfolio_table")
            or evidence.get("direct_portfolio_table")
            or member_contract.get("direct_portfolio_table")
        ):
            raise PermissionError("DIRECT_PORTFOLIO_TABLE_CONTRACT_REQUIRED")
        source_pdf_id = str(anchor.get("pdf_id") or "").strip()
        source_pdf = Path(source_pdf_id)
        if not source_pdf.is_file():
            raise PermissionError("DIRECT_PORTFOLIO_SOURCE_PDF_REQUIRED")
        page = child.get("candidate_note_pdf_page_index") or anchor.get("statement_pdf_page_index")
        if not str(page or "").isdigit() or int(page) < 1:
            raise ValueError("DIRECT_PORTFOLIO_PAGE_REQUIRED")
        page = int(page)
        end_page = int(child.get("direct_end_page") or evidence.get("direct_end_page") or page)
        if end_page < page:
            raise ValueError("DIRECT_PORTFOLIO_END_PAGE_INVALID")
        title = str(
            child.get("direct_capture_title")
            or evidence.get("direct_capture_title")
            or anchor.get("source_table_title")
            or member_contract.get("canonical_title")
            or ""
        ).strip()
        if not title:
            raise ValueError("DIRECT_PORTFOLIO_TITLE_REQUIRED")
        anchor_id = str(anchor.get("occurrence_id") or "")
        child_id = str(child.get("anchor_child_id") or "")
        physical_asset_id = str(
            child.get("physical_asset_id")
            or evidence.get("physical_asset_id")
            or member_contract.get("physical_asset_id")
            or ""
        )
        if not anchor_id or not child_id or not physical_asset_id:
            raise ValueError("DIRECT_PORTFOLIO_PHYSICAL_ANCHOR_CHILD_REQUIRED")
        family_id = str(anchor.get("table_family") or anchor.get("table_family_id") or "")
        member_id = str(member_contract.get("member_table_id") or child.get("canonical_concept_id") or "")
        scope = str(child.get("statement_scope") or anchor.get("scope") or "")
        if scope not in {"CONSOLIDATED", "PARENT_COMPANY"}:
            raise ValueError("DIRECT_PORTFOLIO_SCOPE_REQUIRED")
        topology = str(child.get("disclosure_topology") or evidence.get("disclosure_topology") or "")
        axis = str(child.get("classification_axis") or evidence.get("classification_axis") or "")
        logical_block_id = str(child.get("logical_block_id") or evidence.get("logical_block_id") or "")
        member_table_ids = list(dict.fromkeys(
            str(value) for value in (
                member_contract.get("member_table_ids") or [member_id]
            ) if str(value)
        ))
        logical_block_ids = list(dict.fromkeys(
            str(value) for value in (
                member_contract.get("logical_block_ids") or [logical_block_id]
            ) if str(value)
        ))
        classification_axes = list(dict.fromkeys(
            str(value) for value in (
                member_contract.get("classification_axes") or [axis]
            ) if str(value)
        ))
        conditional_logical_members = list(
            member_contract.get("conditional_logical_members") or []
        )
        period_labels = list(dict.fromkeys(
            str(value).strip() for value in (
                member_contract.get("period_labels")
                or evidence.get("period_headers")
                or []
            ) if str(value).strip()
        ))
        physical_bbox = dict(
            child.get("physical_bbox")
            or evidence.get("physical_bbox")
            or {}
        )
        if not all(key in physical_bbox for key in ("x0", "y0", "x1", "y1")):
            raise ValueError("DIRECT_PORTFOLIO_PHYSICAL_BBOX_REQUIRED")
        if (
            float(physical_bbox["x1"]) <= float(physical_bbox["x0"])
            or float(physical_bbox["y1"]) <= float(physical_bbox["y0"])
        ):
            raise ValueError("DIRECT_PORTFOLIO_PHYSICAL_BBOX_INVALID")
        from spatial_table_capture import build_certified_column_topology_from_pdf

        certified_topology = build_certified_column_topology_from_pdf(
            source_pdf,
            page_number=page,
            bbox=physical_bbox,
            period_labels=period_labels,
        )
        if certified_topology is None:
            raise ValueError("DIRECT_PORTFOLIO_CERTIFIED_COLUMN_TOPOLOGY_REQUIRED")
        period_signature = dict(certified_topology["period_signature"])
        header_signature = dict(certified_topology["header_signature"])
        amount_lane_signature = dict(certified_topology["amount_lane_signature"])
        digest = _sha(source_pdf)
        now = now_iso()
        with self.registry.connect() as c:
            existing = c.execute(
                """SELECT * FROM certified_child_table_links
                   WHERE anchor_id=? AND logical_table_id=?
                     AND certification_status='CERTIFIED'
                     AND relation_type='DIRECT_PORTFOLIO_WHOLE_TABLE'
                   ORDER BY certified_at DESC LIMIT 1""",
                (anchor_id, physical_asset_id),
            ).fetchone()
            existing_contract_version = 0
            if existing:
                existing_segment = c.execute(
                    """SELECT period_signature_json
                       FROM certified_child_table_segments
                       WHERE certified_link_id=? AND \"order\"=0
                       LIMIT 1""",
                    (existing["certified_link_id"],),
                ).fetchone()
                if existing_segment:
                    try:
                        existing_contract_version = int(
                            json.loads(existing_segment["period_signature_json"])
                            .get("contract_version")
                            or 0
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        existing_contract_version = 0
                if existing_contract_version >= 3:
                    return dict(existing)
            run_id = "CDRUN_" + uuid.uuid4().hex
            candidate_id = "TCAND_" + uuid.uuid4().hex
            link_candidate_id = "LKC_" + uuid.uuid4().hex
            certified_link_id = "CLINK_" + uuid.uuid4().hex
            segment_id = "CSEG_" + uuid.uuid4().hex
            audit = {
                "strategy": "DIRECT_PORTFOLIO_TABLES",
                "disclosure_topology": topology,
                "physical_asset_id": physical_asset_id,
                "logical_block_id": logical_block_id,
                "classification_axis": axis,
                "member_table_ids": member_table_ids,
                "logical_block_ids": logical_block_ids,
                "classification_axes": classification_axes,
                "conditional_logical_members": conditional_logical_members,
                "period_labels": period_labels,
                "physical_bbox": physical_bbox,
                "unit": str(child.get("unit") or evidence.get("unit") or ""),
                "not_applicable_members": list(evidence.get("not_applicable_members") or []),
                "supersedes_certified_link_id": (
                    str(existing["certified_link_id"]) if existing else ""
                ),
                "column_topology_upgrade_from_version": existing_contract_version,
                **dict(certified_topology.get("evidence") or {}),
            }
            c.execute(
                """INSERT INTO child_discovery_runs(
                   discovery_run_id,source_pdf_id,source_pdf_sha256,anchor_id,anchor_child_id,
                   requested_scope,tiers_executed_json,tiers_skipped_json,early_stop_reason,
                   candidate_count_by_tier_json,runtime_by_tier_json,metrics_json,status,
                   producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, source_pdf_id, digest, anchor_id, child_id, scope,
                 _json(["DIRECT_PORTFOLIO_TABLE"]), _json(["NOTE_RETRIEVAL_NOT_APPLICABLE"]), None,
                 _json({"DIRECT_PORTFOLIO_TABLE": 1}), _json({}), _json(audit), "COMPLETE", APP_VERSION, now),
            )
            c.execute(
                """INSERT INTO thin_child_table_candidates(
                   candidate_id,discovery_run_id,anchor_child_id,retrieval_tier,retrieval_method,retrieval_priority,
                   source_pdf_id,source_pdf_sha256,heading_id,raw_heading,normalized_heading,section_id,section_type,
                   start_page,end_page_hint,heading_bbox_json,note_reference,statement_scope_hint,base_score,
                   warning_codes_json,hard_gate_summary_json,evidence_ref_ids_json,created_at,producer_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (candidate_id, run_id, child_id, "DIRECT_PORTFOLIO_TABLE", "DIRECT_PORTFOLIO_CERTIFIED_ANCHOR", 1,
                 source_pdf_id, digest, physical_asset_id, title, _norm(title),
                 "DIRECT_PORTFOLIO_DISCLOSURE", "DIRECT_DISCLOSURE_TABLE", page, end_page, _json({}), "", scope,
                 1.0, _json([]), _json({"certified_anchor": True, **audit}), _json([]), now, APP_VERSION),
            )
            c.execute(
                """INSERT INTO child_table_link_candidates(
                   link_candidate_id,anchor_id,anchor_child_id,candidate_id,logical_table_candidate_id,
                   proposed_member_table_id,proposed_subtable_role,proposed_relation_type,statement_scope,report_year,
                   retrieval_prior,evidence_score,penalty_score,certification_score,score_breakdown_json,
                   hard_gate_results_json,reconciliation_relation,reconciliation_status,confidence,
                   blocking_warnings_json,ranking_position,is_recommended,is_preselected,producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (link_candidate_id, anchor_id, child_id, candidate_id, None, member_id,
                 "DIRECT_DISCLOSURE_TABLE", "DIRECT_PORTFOLIO_WHOLE_TABLE", scope, child.get("report_year"),
                 1.0, 1.0, 0.0, 1.0, _json(audit), _json({"topology_resolved": True}),
                 "NOT_APPLICABLE", "NOT_APPLICABLE", 1.0, _json([]), 1, 1, 1, APP_VERSION, now),
            )
            score_snapshot = _json({"certification_score": 1.0, **audit})
            evidence_snapshot = _json({
                "anchor_occurrence_id": anchor_id,
                "direct_portfolio_table": True,
                "direct_capture_title": title,
                "portfolio_page": page,
                "portfolio_end_page": end_page,
                "anchor_note_reference": "",
                **audit,
            })
            c.execute(
                """INSERT INTO certified_child_table_links(
                   certified_link_id,research_project_id,research_task_id,anchor_id,anchor_child_id,candidate_id,
                   link_candidate_id,table_family_id,member_table_id,subtable_role,relation_type,statement_scope,
                   report_year,data_year,certification_method,certification_status,score_snapshot_json,evidence_snapshot_json,
                   reconciliation_result_json,recommended_candidate_id,selected_candidate_id,alternative_candidates_json,
                   reviewer,certified_at,research_definition_id,definition_version,producer_version,logical_table_id,
                   table_classification,segment_manifest_status,note_table_inventory_id,note_table_inventory_status,
                   logical_table_candidate_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (certified_link_id, anchor.get("research_project_id"), anchor.get("research_task_id"), anchor_id, child_id, candidate_id,
                 link_candidate_id, family_id, member_id, "DIRECT_DISCLOSURE_TABLE", "DIRECT_PORTFOLIO_WHOLE_TABLE", scope,
                 child.get("report_year"), child.get("data_year"), "DIRECT_PORTFOLIO_CERTIFIED_ANCHOR", "CERTIFIED",
                 score_snapshot, evidence_snapshot, _json({"status": "NOT_APPLICABLE"}), link_candidate_id, candidate_id,
                 _json([]), reviewer, now, child.get("research_definition_id"), child.get("definition_version"), APP_VERSION,
                 physical_asset_id, "PRIMARY_TABLE", "CERTIFIED_SEGMENT_MANIFEST", "", "NOT_APPLICABLE_DIRECT_PORTFOLIO", None),
            )
            c.execute(
                """INSERT INTO certified_child_table_segments(
                   certified_segment_id,certified_link_id,"order",classification,start_page,end_page,bbox_json,
                   continuation_of_segment_id,header_signature_json,period_signature_json,amount_lane_signature_json,
                   confidence,evidence_json,certification_status,reviewer,certified_at,producer_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (segment_id, certified_link_id, 0, "PRIMARY_TABLE", page, end_page, _json(physical_bbox), None,
                 _json(header_signature), _json(period_signature), _json(amount_lane_signature),
                 1.0, _json(audit),
                 "CERTIFIED", reviewer, now, APP_VERSION),
            )
            c.execute(
                """INSERT INTO child_mapping_review_records(
                   review_record_id,anchor_child_id,action,selected_candidate_id,rejected_candidates_json,reason,
                   reviewer,evidence_json,producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("CMREV_" + uuid.uuid4().hex, child_id, "DIRECT_PORTFOLIO_CERTIFIED_ANCHOR", candidate_id,
                 _json([]), "已按投资组合拓扑认证直接披露物理表，未运行金融附注成员审核", reviewer,
                 evidence_snapshot, APP_VERSION, now),
            )
        return {
            "certified_link_id": certified_link_id,
            "anchor_id": anchor_id,
            "anchor_child_id": child_id,
            "candidate_id": candidate_id,
            "link_candidate_id": link_candidate_id,
            "table_family_id": family_id,
            "member_table_id": member_id,
            "statement_scope": scope,
            "report_year": child.get("report_year"),
            "research_definition_id": child.get("research_definition_id"),
            "definition_version": child.get("definition_version"),
            "subtable_role": "DIRECT_DISCLOSURE_TABLE",
            "relation_type": "DIRECT_PORTFOLIO_WHOLE_TABLE",
            "logical_table_id": physical_asset_id,
            "member_table_ids": member_table_ids,
            "logical_block_ids": logical_block_ids,
            "classification_axes": classification_axes,
            "conditional_logical_members": conditional_logical_members,
            "period_labels": period_labels,
            "certification_status": "CERTIFIED",
            "direct_portfolio_table": True,
        }

    def revoke_certified_link(
        self,
        certified_link_id:str,
        *,
        reviewer:str,
        reason_code:str,
        reason:str,
        evidence:dict[str,Any]|None=None,
    )->dict[str,Any]:
        """Revoke a certified target through the owning repository.

        Revocation is append-audited and keeps the original machine and human
        evidence intact.  It is intended for source-identity corrections such
        as a current/comparative period reclassification; callers may not
        delete or rewrite a certified link directly.
        """
        reviewer=str(reviewer or "").strip()
        reason_code=str(reason_code or "").strip().upper()
        reason=str(reason or "").strip()
        if not reviewer:
            raise ValueError("CERTIFIED_LINK_REVOCATION_REVIEWER_REQUIRED")
        if not reason_code:
            raise ValueError("CERTIFIED_LINK_REVOCATION_REASON_CODE_REQUIRED")
        if not reason:
            raise ValueError("CERTIFIED_LINK_REVOCATION_REASON_REQUIRED")
        now=now_iso()
        with self.registry.connect() as c:
            row=c.execute(
                "SELECT * FROM certified_child_table_links WHERE certified_link_id=?",
                (certified_link_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"CERTIFIED_CHILD_TABLE_LINK_NOT_FOUND:{certified_link_id}")
            persisted=dict(row)
            status=str(persisted.get("certification_status") or "").upper()
            if status=="REVOKED":
                return persisted
            if status!="CERTIFIED":
                raise PermissionError(
                    f"CERTIFIED_CHILD_TABLE_LINK_NOT_REVOCABLE:{status}"
                )
            c.execute(
                """UPDATE certified_child_table_links
                   SET certification_status='REVOKED'
                   WHERE certified_link_id=? AND certification_status='CERTIFIED'""",
                (certified_link_id,),
            )
            if c.total_changes<1:
                raise RuntimeError("CERTIFIED_CHILD_TABLE_LINK_REVOCATION_LOST_UPDATE")
            c.execute(
                """UPDATE certified_child_table_segments
                   SET certification_status='REVOKED'
                   WHERE certified_link_id=? AND certification_status='CERTIFIED'""",
                (certified_link_id,),
            )
            audit_evidence={
                "certified_link_id":certified_link_id,
                "reason_code":reason_code,
                "previous_certification_status":status,
                "member_table_id":persisted.get("member_table_id"),
                "logical_table_id":persisted.get("logical_table_id"),
                **dict(evidence or {}),
            }
            c.execute(
                """INSERT INTO child_mapping_review_records(
                   review_record_id,anchor_child_id,action,selected_candidate_id,
                   rejected_candidates_json,reason,reviewer,evidence_json,
                   producer_version,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    "CMREV_"+uuid.uuid4().hex,
                    persisted["anchor_child_id"],
                    "REVOKE_CERTIFIED_CHILD_TABLE_LINK",
                    persisted.get("selected_candidate_id") or persisted.get("candidate_id"),
                    _json([]),reason,reviewer,_json(audit_evidence),APP_VERSION,now,
                ),
            )
        return {**persisted,"certification_status":"REVOKED",
                "revocation_reason_code":reason_code,"revoked_at":now}

    def certified_target(self,certified_link_id:str)->dict[str,Any]:
        with self.registry.connect() as c:
            row=c.execute("""SELECT l.*,t.start_page,t.end_page_hint,t.raw_heading,
                t.note_reference,t.source_pdf_id,t.heading_bbox_json,
                lt.title AS logical_title,
                lt.start_page AS logical_start_page,
                lt.end_page AS logical_end_page,
                lt.bbox_json AS logical_bbox_json,
                a.inline_note_reference AS anchor_inline_note_reference
                FROM certified_child_table_links l
                JOIN thin_child_table_candidates t ON t.candidate_id=l.candidate_id
                LEFT JOIN child_logical_table_candidates lt
                  ON lt.logical_table_candidate_id=l.logical_table_candidate_id
                LEFT JOIN anchor_child_concepts a
                  ON a.anchor_child_id=l.anchor_child_id
                WHERE l.certified_link_id=? AND l.certification_status='CERTIFIED'""",
                (certified_link_id,)).fetchone()
            segment_rows=c.execute(
                """SELECT * FROM certified_child_table_segments
                   WHERE certified_link_id=? AND certification_status='CERTIFIED'
                   ORDER BY "order" ASC""",
                (certified_link_id,),
            ).fetchall() if row else []
        if not row:raise PermissionError("CERTIFIED_CHILD_TABLE_LINK_REQUIRED")
        p=dict(row)
        certified_segments=[]
        for segment_row in segment_rows:
            segment=dict(segment_row)
            for field in (
                "bbox","header_signature","period_signature",
                "amount_lane_signature","evidence",
            ):
                segment[field]=json.loads(segment.pop(field+"_json") or "{}")
            certified_segments.append(segment)
        evidence_snapshot=json.loads(p.get("evidence_snapshot_json") or "{}")
        anchor_note_reference=str(
            evidence_snapshot.get("anchor_note_reference")
            or p.get("anchor_inline_note_reference")
            or ""
        )
        candidate_note_reference=str(p.get("note_reference") or "")
        if (
            anchor_note_reference
            and candidate_note_reference
            and _leaf_note_ordinal(anchor_note_reference)
            != _leaf_note_ordinal(candidate_note_reference)
        ):
            raise PermissionError(
                "CERTIFIED_TARGET_NOTE_REFERENCE_MISMATCH_REVIEW_REQUIRED:"
                f"anchor={anchor_note_reference},candidate={candidate_note_reference}"
            )
        target_heading=str(p.get("logical_title") or p["raw_heading"])
        target_start_page=int(p.get("logical_start_page") or p["start_page"])
        target_end_page=int(
            p.get("logical_end_page") or p["end_page_hint"] or target_start_page
        )
        capture_query=_capture_query_heading(target_heading)
        return {
            "certified_link_id":certified_link_id,"source_pdf_id":p["source_pdf_id"],
            "confirmed_note_pdf_page_index":target_start_page,
            "end_page":target_end_page,
            # The Registry member id is an internal, stable research identity;
            # it is often not the literal PDF heading.  Spatial capture must
            # receive the reviewed source heading, otherwise strict identity
            # can target a valid page with an unmatchable query and later
            # report a misleading header/boundary failure.
            "target_heading":target_heading,"capture_query_title":capture_query,
            "member_table_id":p["member_table_id"],
            "logical_table_id":p["logical_table_id"],
            "table_classification":p["table_classification"],
            "segment_manifest_status":p["segment_manifest_status"],
            "note_table_inventory_id":p["note_table_inventory_id"],
            "note_table_inventory_status":p["note_table_inventory_status"],
            "logical_table_candidate_id":p["logical_table_candidate_id"],
            "certified_segments":certified_segments,
            "relation_type":p.get("relation_type"),
            "direct_portfolio_table":bool(evidence_snapshot.get("direct_portfolio_table")),
            "disclosure_topology":evidence_snapshot.get("disclosure_topology"),
            "physical_asset_id":evidence_snapshot.get("physical_asset_id"),
            "logical_block_id":evidence_snapshot.get("logical_block_id"),
            "classification_axis":evidence_snapshot.get("classification_axis"),
            "member_table_ids":list(evidence_snapshot.get("member_table_ids") or []),
            "logical_block_ids":list(evidence_snapshot.get("logical_block_ids") or []),
            "classification_axes":list(evidence_snapshot.get("classification_axes") or []),
            "conditional_logical_members":list(
                evidence_snapshot.get("conditional_logical_members") or []
            ),
            "period_labels":list(evidence_snapshot.get("period_labels") or []),
            "unit":evidence_snapshot.get("unit"),
            "note_reference":anchor_note_reference or candidate_note_reference,"statement_scope":p["statement_scope"],
            "confidence":json.loads(p["score_snapshot_json"] or "{}").get("certification_score",1),
            "status":"CERTIFIED_NOTE_TARGET",
            "evidence":{"certified_child_table_link":certified_link_id,
                        "logical_table_bbox":json.loads(
                            p.get("logical_bbox_json") or "{}"
                        ),
                        "anchor_note_reference":anchor_note_reference},
        }

    def certified_links_for_anchor(
        self,
        anchor_id: str,
        *,
        table_family_id: str,
        statement_scope: str,
        research_definition_id: str,
        definition_version: str,
    ) -> list[dict[str, Any]]:
        """Return the exact owner-certified Stage-B inventory for one Anchor."""
        identity = {
            "anchor_id": str(anchor_id or "").strip(),
            "table_family_id": str(table_family_id or "").strip(),
            "statement_scope": str(statement_scope or "").strip(),
            "research_definition_id": str(research_definition_id or "").strip(),
            "definition_version": str(definition_version or "").strip(),
        }
        missing = [key for key, value in identity.items() if not value]
        if missing:
            raise ValueError(
                "CERTIFIED_LINK_RESTORE_IDENTITY_REQUIRED:" + ",".join(missing)
            )
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT l.*
                   FROM certified_child_table_links l
                   WHERE l.anchor_id=?
                     AND l.table_family_id=?
                     AND l.statement_scope=?
                     AND l.research_definition_id=?
                     AND l.definition_version=?
                     AND l.certification_status='CERTIFIED'
                   ORDER BY l.member_table_id ASC,
                            l.table_classification ASC,
                            l.logical_table_id ASC,
                            l.certified_at ASC,
                            l.certified_link_id ASC""",
                (
                    identity["anchor_id"],
                    identity["table_family_id"],
                    identity["statement_scope"],
                    identity["research_definition_id"],
                    identity["definition_version"],
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def certified_links_for_physical_anchor(
        self,
        candidate: dict[str, Any],
        *,
        table_family_id: str,
        statement_scope: str,
        research_definition_id: str,
        definition_version: str,
    ) -> list[dict[str, Any]]:
        """Restore links across append-only occurrence revisions.

        The owner Anchor must have a formal certification audit and match the
        fresh occurrence on immutable filing/page/scope identity.  Labels and
        ranking scores are intentionally excluded from the fallback.
        """
        identity = {
            "pdf_id": str(candidate.get("pdf_id") or "").strip().lower(),
            "report_year": str(candidate.get("report_year") or "").strip(),
            "statement_scope": str(statement_scope or "").strip(),
            "statement_type": str(candidate.get("statement_type") or "").strip(),
            "table_family_id": str(table_family_id or "").strip(),
            "research_definition_id": str(research_definition_id or "").strip(),
            "definition_version": str(definition_version or "").strip(),
        }
        page = candidate.get("statement_pdf_page_index")
        missing = [key for key, value in identity.items() if not value]
        if page in (None, ""):
            missing.append("statement_pdf_page_index")
        if missing:
            raise ValueError(
                "CERTIFIED_PHYSICAL_ANCHOR_IDENTITY_REQUIRED:" + ",".join(missing)
            )
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT l.*
                   FROM certified_child_table_links l
                   JOIN statement_occurrences o ON o.occurrence_id=l.anchor_id
                   JOIN anchor_certification_audit a
                     ON a.selected_candidate_id=o.occurrence_id
                   WHERE lower(o.pdf_id)=?
                     AND o.report_year=?
                     AND o.scope=?
                     AND o.statement_pdf_page_index=?
                     AND o.statement_type=?
                     AND o.table_family=?
                     AND l.table_family_id=?
                     AND l.statement_scope=?
                     AND l.research_definition_id=?
                     AND l.definition_version=?
                     AND l.certification_status='CERTIFIED'
                   ORDER BY l.member_table_id ASC,
                            l.table_classification ASC,
                            l.logical_table_id ASC,
                            l.certified_at ASC,
                            l.certified_link_id ASC""",
                (
                    identity["pdf_id"], identity["report_year"],
                    identity["statement_scope"], int(page),
                    identity["statement_type"], identity["table_family_id"],
                    identity["table_family_id"], identity["statement_scope"],
                    identity["research_definition_id"],
                    identity["definition_version"],
                ),
            ).fetchall()
        return [dict(row) for row in rows]


class FinancialNoteIndexService:
    def __init__(self,repository:ChildDiscoveryRepository):
        self.repo=repository; self.registry=repository.registry

    def build(self,pdf_path:Path,options:dict[str,Any]|None=None)->dict[str,Any]:
        pdf_path=Path(pdf_path); digest=_sha(pdf_path); options=dict(options or {"section":"FINANCIAL_STATEMENT_NOTES"})
        key_options=_json(options)
        with self.registry.connect() as c:
            existing=c.execute("""SELECT * FROM financial_note_indexes
                WHERE source_pdf_sha256=? AND index_version=? AND index_options_json=?
                AND producer_version=?""",(digest,INDEX_VERSION,key_options,APP_VERSION)).fetchone()
            if existing:
                return dict(existing)|{"cache_hit":True}
        started=time.perf_counter(); headings=[]; notes_start=None
        with fitz.open(str(pdf_path)) as doc:
            page_texts=[page.get_text("text") for page in doc]
            formal_candidates=[
                i+1 for i,text in enumerate(page_texts)
                if i+1>=max(1,int(doc.page_count*0.25))
                and 0<=text.find("财务报表附注")<=180
            ]
            notes_start=formal_candidates[0] if formal_candidates else None
            for page_index,page in enumerate(doc):
                text=page_texts[page_index]
                if notes_start is None or page_index+1<notes_start:continue
                text_dict=page.get_text("dict")
                scope=_scope(text); unit=_unit(text)
                pending_ordinal=None
                for block in text_dict.get("blocks") or []:
                    if int(block.get("type",0))!=0:
                        continue
                    block_bbox=block.get("bbox") or (0.0,0.0,0.0,0.0)
                    native_lines=list(block.get("lines") or [])
                    line_index=0
                    while line_index<len(native_lines):
                        native_line=native_lines[line_index]
                        label="".join(
                            str(span.get("text") or "")
                            for span in native_line.get("spans") or []
                        ).strip()
                        line_bbox=native_line.get("bbox") or block_bbox
                        x0,y0,x1,y1=(float(value) for value in line_bbox)
                        if (
                            re.fullmatch(
                                r"(?:附注)?[（(]?[一二三四五六七八九十百\d]+[）)]?",
                                label,
                            )
                            and line_index+1<len(native_lines)
                        ):
                            next_line=native_lines[line_index+1]
                            next_label="".join(
                                str(span.get("text") or "")
                                for span in next_line.get("spans") or []
                            ).strip()
                            next_bbox=next_line.get("bbox") or block_bbox
                            nx0,ny0,nx1,ny1=(
                                float(value) for value in next_bbox
                            )
                            baseline_aligned=bool(
                                nx0>x0
                                and min(y1,ny1)-max(y0,ny0)
                                >=0.5*min(y1-y0,ny1-ny0)
                            )
                            if (
                                baseline_aligned
                                and re.search(r"[A-Za-z\u4e00-\u9fff]",next_label)
                                and len(next_label)<=70
                            ):
                                label=f"{label} {next_label}"
                                x0,y0,x1,y1=(
                                    min(x0,nx0),min(y0,ny0),
                                    max(x1,nx1),max(y1,ny1),
                                )
                                line_index+=1
                        line_index+=1
                        if not (2<=len(label)<=80):continue
                        # Do not turn a numeric note-body value such as
                        # ``7.1884`` (exchange rate) into a fictitious
                        # "note 7" heading merely because the decimal point
                        # resembles a heading separator.
                        if re.fullmatch(r"[（(]?-?\d+(?:[.,，]\d+)+%?[）)]?", label):
                            continue
                        bare_ordinal=re.match(
                            r"^\s*(?:附注)?[（(]?([一二三四五六七八九十百\d]+)"
                            r"[）)、.．]\s*$",
                            label,
                        )
                        if bare_ordinal:
                            pending_ordinal=bare_ordinal.group(1)
                            continue
                        ordinal=re.match(r"^\s*(?:附注)?[（(]?([一二三四五六七八九十百\d]+)[）)、.．\s]+(.+)$",label)
                        ordinal_title=(ordinal.group(2).strip() if ordinal else "")
                        looks_title=bool(
                            (ordinal and re.search(r"[\u4e00-\u9fff]", ordinal_title))
                            or (re.search(r"[\u4e00-\u9fff]", label)
                                and re.search(r"投资|资产|负债|合同|收益|准备金|应收|应付",label))
                        )
                        if not looks_title:continue
                        composed_ordinal=ordinal.group(1) if ordinal else pending_ordinal
                        if pending_ordinal and not ordinal:
                            pending_ordinal=None
                        headings.append({
                            "raw_heading":label,"normalized_heading":_norm(label),
                            "note_ordinal":composed_ordinal,
                            "start_page":page_index+1,"bbox":[x0,y0,x1,y1],
                            "scope":scope,"unit":unit,"order":len(headings),
                        })
        build_ms=(time.perf_counter()-started)*1000
        index_id="FNIDX_"+uuid.uuid4().hex; now=now_iso()
        with self.registry.connect() as c:
            c.execute("""INSERT INTO financial_note_indexes(
                index_id,source_pdf_sha256,source_pdf_id,index_version,index_options_json,
                producer_version,notes_start_page,notes_end_page,index_build_ms,status,
                created_at) VALUES(?,?,?,?,?,?,?,?,?,'READY',?)""",
                (index_id,digest,str(pdf_path),INDEX_VERSION,key_options,APP_VERSION,
                 notes_start,max([x["start_page"] for x in headings],default=notes_start),
                 build_ms,now))
            for h in headings:
                heading_id="FNH_"+uuid.uuid4().hex
                c.execute("""INSERT INTO financial_note_headings(
                    heading_id,index_id,section_id,section_type,raw_heading,normalized_heading,
                    heading_level,heading_parent_id,heading_order,note_ordinal,note_reference,
                    start_page,end_page_hint,heading_bbox_json,statement_scope_context,
                    report_year_context,unit_context,text_quality,producer_version)
                    VALUES(?,?,'FINANCIAL_NOTES','FINANCIAL_STATEMENT_NOTES',?,?,1,NULL,?,?,?,?,?,?,?,?,?,1.0,?)""",
                    (heading_id,index_id,h["raw_heading"],h["normalized_heading"],h["order"],
                     h["note_ordinal"],h["note_ordinal"],h["start_page"],None,_json(h["bbox"]),
                     h["scope"],"",h["unit"],APP_VERSION))
        return {"index_id":index_id,"source_pdf_sha256":digest,"source_pdf_id":str(pdf_path),
                "notes_start_page":notes_start,"heading_count":len(headings),
                "index_build_ms":build_ms,"cache_hit":False}

    def headings(self,index_id:str)->list[dict[str,Any]]:
        with self.registry.connect() as c:
            return [dict(x) for x in c.execute(
                """SELECT * FROM financial_note_headings WHERE index_id=?
                   AND section_type='FINANCIAL_STATEMENT_NOTES'
                   ORDER BY heading_order""",(index_id,)).fetchall()]

    def bounded_note_scope(
        self,candidate:dict[str,Any],*,page_count:int,
        unresolved_page_limit:int=4,
    )->dict[str,Any]:
        start_page=max(1,int(candidate.get("start_page") or 1))
        note_reference=str(candidate.get("note_reference") or "")
        note_identity=_leaf_note_ordinal(note_reference)
        with self.registry.connect() as c:
            index_row=c.execute(
                """SELECT * FROM financial_note_indexes
                   WHERE source_pdf_sha256=? AND index_version=?
                     AND producer_version=? AND status='READY'
                   ORDER BY created_at DESC LIMIT 1""",
                (
                    candidate.get("source_pdf_sha256") or "",
                    INDEX_VERSION,APP_VERSION,
                ),
            ).fetchone()
            heading_rows=[]
            if index_row:
                heading_rows=[dict(row) for row in c.execute(
                    """SELECT * FROM financial_note_headings
                       WHERE index_id=?
                         AND section_type='FINANCIAL_STATEMENT_NOTES'
                       ORDER BY heading_order""",
                    (index_row["index_id"],),
                ).fetchall()]
        current=None
        heading_id=str(candidate.get("heading_id") or "")
        if heading_id:
            current=next(
                (row for row in heading_rows if str(row["heading_id"])==heading_id),
                None,
            )
        if current is None and note_identity:
            matches=[
                row for row in heading_rows
                if _leaf_note_ordinal(
                    str(row.get("note_reference") or row.get("note_ordinal") or "")
                )==note_identity
            ]
            if matches:
                current=min(
                    matches,
                    key=lambda row:(
                        abs(int(row.get("start_page") or start_page)-start_page),
                        int(row.get("heading_order") or 0),
                    ),
                )
        current_order=int(current.get("heading_order") or -1) if current else -1
        boundary=_next_peer_heading(
            heading_rows,
            current_order=current_order,
            note_identity=note_identity,
        )
        if boundary:
            boundary_page=max(start_page,int(boundary.get("start_page") or start_page))
            boundary_bbox=json.loads(boundary.get("heading_bbox_json") or "{}")
            return {
                "note_identity":note_identity,
                "scan_start_page":start_page,
                "scan_end_page":min(int(page_count),boundary_page),
                "next_note_boundary_page":boundary_page,
                "next_note_boundary_bbox":boundary_bbox,
                "next_note_reference":str(
                    boundary.get("note_reference") or boundary.get("note_ordinal") or ""
                ),
                "next_note_title":str(boundary.get("raw_heading") or ""),
                "boundary_status":"CONFIRMED_PEER_HEADING",
                "terminal_boundary_confirmed":False,
            }
        unresolved_cap=start_page+max(1,int(unresolved_page_limit))-1
        fallback_hint=int(candidate.get("end_page_hint") or unresolved_cap)
        fallback_end=min(
            int(page_count),max(start_page,fallback_hint),unresolved_cap,
        )
        return {
            "note_identity":note_identity,
            "scan_start_page":start_page,"scan_end_page":fallback_end,
            "next_note_boundary_page":None,"next_note_boundary_bbox":{},
            "next_note_reference":"","next_note_title":"",
            "boundary_status":"UNRESOLVED",
            "terminal_boundary_confirmed":False,
        }


class HierarchicalChildTableDiscoveryService:
    def __init__(self,repository:ChildDiscoveryRepository,index_service:FinancialNoteIndexService,
                 limits:dict[str,int]|None=None):
        self.repo=repository;self.index=index_service
        self.limits={**DEFAULT_LIMITS,**dict(limits or {})}

    def _thin(self,run_id:str,child:dict[str,Any],heading:dict[str,Any],
              tier:str,method:str,priority:int,digest:str,warnings:list[str]|None=None)->dict[str,Any]:
        return {
            "candidate_id":"TCAND_"+uuid.uuid4().hex,"discovery_run_id":run_id,
            "anchor_child_id":child["anchor_child_id"],"retrieval_tier":tier,
            "retrieval_method":method,"retrieval_priority":priority,
            "source_pdf_id":heading.get("source_pdf_id") or "",
            "source_pdf_sha256":digest,"heading_id":heading["heading_id"],
            "raw_heading":heading["raw_heading"],"normalized_heading":heading["normalized_heading"],
            "section_id":heading.get("section_id"),"section_type":heading["section_type"],
            "start_page":heading["start_page"],"end_page_hint":heading.get("end_page_hint"),
            "heading_bbox":json.loads(heading.get("heading_bbox_json") or "{}"),
            "note_reference":heading.get("note_reference"),
            "statement_scope_hint":heading.get("statement_scope_context") or "UNKNOWN",
            "base_score":RETRIEVAL_PRIORS[method],"warning_codes":warnings or [],
            "hard_gate_summary":{"allowed_section":heading["section_type"]=="FINANCIAL_STATEMENT_NOTES"},
            "evidence_ref_ids":[],"created_at":now_iso(),"producer_version":APP_VERSION,
            "evidence":[{"type":"HEADING_MATCH","source":method,"text":heading["raw_heading"],
                         "page_ref":heading["start_page"],"confidence":1.0}],
        }

    def manual_add_candidate(self,pdf_path:Path,anchor:dict[str,Any],
                             child:dict[str,Any],member_contract:dict[str,Any],
                             requested_scope:str,*,page:int,title:str)->list[dict[str,Any]]:
        """Reject human-authored physical candidates on the production path."""
        raise PermissionError("MANUAL_CHILD_TABLE_CANDIDATE_FORBIDDEN")

    def discover(self,pdf_path:Path,anchor:dict[str,Any],child:dict[str,Any],
                 member_contract:dict[str,Any],requested_scope:str)->dict[str,Any]:
        if requested_scope not in {"CONSOLIDATED","PARENT_COMPANY"}:raise ValueError("SCOPE_LANE_REQUIRED")
        # Skip only members proven not to be in the current family boundary.
        # ``UNRESOLVED`` is a reviewable source state, not proof that a
        # statement row is comparative-only.  Rejecting it here contradicted
        # ``create_anchor_children`` and produced an empty Stage-B queue for
        # otherwise valid split-layout statements.
        period_status = str(child.get("member_period_status") or "")
        if period_status in {
            "COMPARATIVE_ONLY_LEGACY_MEMBER",
            "OUTSIDE_FAMILY",
            "NOT_A_FAMILY_MEMBER",
        }:
            return {
                "run": None, "candidates": [], "index": None,
                "early_stop_reason": f"NON_CURRENT_MEMBER_{period_status}",
            }
        idx=self.index.build(pdf_path)
        cached=self.repo.cached_discovery(
            source_pdf_sha256=idx["source_pdf_sha256"],
            anchor_child_id=child["anchor_child_id"],requested_scope=requested_scope,
        )
        if cached:return {**cached,"index":idx}
        headings=self.index.headings(idx["index_id"])
        for h in headings:h["source_pdf_id"]=str(pdf_path)
        run_id="CDRUN_"+uuid.uuid4().hex; executed=[];skipped=[];counts={};times={};candidates=[]
        reference=str(child.get("inline_note_reference") or "")
        reference_meta=_note_reference_key(reference)
        tier1_failure_reason=""
        # Tier 1
        t=time.perf_counter(); executed.append("TIER1")
        source_evidence=dict(child.get("inline_note_reference_evidence") or {})
        source_target_page=(
            child.get("candidate_note_pdf_page_index") or child.get("note_page")
            or source_evidence.get("candidate_note_pdf_page_index")
        )
        amount_source_page=(
            source_evidence.get("amount_source_page")
            or child.get("statement_pdf_page_index")
            or anchor.get("statement_pdf_page_index")
        )
        amount_source_page_number=(
            int(amount_source_page)
            if str(amount_source_page or "").strip().isdigit()
            else None
        )
        rejected_not_after_main_statement=[
            heading for heading in headings
            if amount_source_page_number is not None
            and int(heading.get("start_page") or 0)<=amount_source_page_number
        ]
        eligible_headings=[
            heading for heading in headings
            if amount_source_page_number is None
            or int(heading.get("start_page") or 0)>amount_source_page_number
        ]
        note_matches=[]
        if reference_meta["note_item_ordinal"]:
            for heading in eligible_headings:
                heading_meta=_note_reference_key(
                    heading.get("note_reference") or heading.get("note_ordinal")
                )
                if heading_meta["note_item_ordinal"] != reference_meta["note_item_ordinal"]:
                    continue
                title_class,title_score,_=_best_title_match(
                    member_contract,heading.get("raw_heading")
                )
                note_matches.append((title_score,title_class,heading))
        compatible=[item for item in note_matches if item[1] != "SEMANTIC_ONLY"]
        scope_compatible=[
            item for item in compatible
            if self._scope_ok(item[2],requested_scope)
        ]
        if scope_compatible:
            compatible=scope_compatible
        source_index_matches=[
            item for item in compatible
            if source_target_page
            and int(item[2].get("start_page") or 0)==int(source_target_page)
        ]
        notes_start_page=idx.get("notes_start_page")
        source_after_statement=bool(
            source_target_page
            and (
                amount_source_page_number is None
                or int(source_target_page)>amount_source_page_number
            )
        )
        if not source_after_statement:
            source_index_matches=[]
        source_target_fallback_allowed=bool(
            source_after_statement
            and not compatible
            and (
                notes_start_page in (None, "")
                or int(source_target_page)>=int(notes_start_page)
            )
        )
        if source_index_matches and reference_meta["note_item_ordinal"]:
            source_index_matches.sort(
                key=lambda item:(-item[0],int(item[2].get("heading_order") or 0))
            )
            source_heading=dict(source_index_matches[0][2])
            source_heading["source_pdf_id"]=idx["source_pdf_id"]
            candidate=self._thin(
                run_id,child,source_heading,"TIER1",
                "TIER1_SOURCE_RESOLVED_NOTE_TARGET",1,
                idx["source_pdf_sha256"],
            )
            candidate["note_reference_evidence"]={
                **reference_meta,"match":"SOURCE_TARGET_INDEX_VALIDATED",
                "source_locator_method":child.get("locator_method") or source_evidence.get("locator_method") or "",
                "source_target_page":int(source_target_page),
                "source_target_validation":"MATCHED_FINANCIAL_NOTE_INDEX",
            }
            candidate["title_match_class"]=source_index_matches[0][1]
            candidates=[candidate]
        elif compatible and reference_meta["note_item_ordinal"]:
            best_score=max(item[0] for item in compatible)
            selected=[item for item in compatible if item[0]==best_score]
            selected.sort(key=lambda item:int(item[2].get("heading_order") or 0))
            candidates=[]
            for title_score,title_class,heading in selected[:self.limits["TIER1"]]:
                candidate=self._thin(
                    run_id,child,heading,"TIER1","TIER1_EXPLICIT_REFERENCE",1,
                    idx["source_pdf_sha256"],
                    ["SOURCE_NOTE_TARGET_REJECTED_INDEX_MISMATCH"]
                    if source_target_page else [],
                )
                candidate["note_reference_evidence"]={
                    **reference_meta,
                    "heading_note_reference":heading.get("note_reference") or heading.get("note_ordinal"),
                    "match":"EXPLICIT_REFERENCE_MATCH",
                    "source_target_page":int(source_target_page) if source_target_page else None,
                    "source_target_validation":(
                        "REJECTED_NOT_AFTER_MAIN_STATEMENT"
                        if source_target_page and not source_after_statement
                        else "REJECTED_INDEX_MISMATCH" if source_target_page
                        else "NOT_PROVIDED"
                    ),
                }
                candidate["title_match_class"]=title_class
                candidates.append(candidate)
        elif source_target_fallback_allowed and reference_meta["note_item_ordinal"]:
            # Statement-guided discovery may already have resolved an explicit
            # note reference to a concrete PDF page.  Retain that immutable
            # source evidence as a Tier-1 candidate instead of discarding it
            # merely because a later native-text heading index cannot read a
            # scanned note page.
            source_heading={
                "heading_id":"SOURCE_NOTE_TARGET::"+str(child.get("source_discovery_id") or child["anchor_child_id"]),
                "raw_heading":child.get("raw_label") or member_contract.get("canonical_title") or "",
                "normalized_heading":_norm(child.get("raw_label") or member_contract.get("canonical_title") or ""),
                "section_id":"STATEMENT_GUIDED_SOURCE_TARGET",
                "section_type":"FINANCIAL_STATEMENT_NOTES",
                "start_page":int(source_target_page),"end_page_hint":int(source_target_page),
                "heading_bbox_json":_json(child.get("row_bbox") or {}),
                "source_pdf_id":idx["source_pdf_id"],"note_reference":reference,
                "scope":requested_scope,"unit":child.get("unit") or "",
            }
            candidate=self._thin(run_id,child,source_heading,"TIER1","TIER1_SOURCE_RESOLVED_NOTE_TARGET",1,
                                 idx["source_pdf_sha256"])
            candidate["note_reference_evidence"]={
                **reference_meta,"match":"SOURCE_RESOLVED_EXPLICIT_NOTE_TARGET",
                "source_locator_method":child.get("locator_method") or source_evidence.get("locator_method") or "",
                "source_target_page":int(source_target_page),
                "source_target_validation":"INDEX_UNAVAILABLE_NO_STATEMENT_PAGE_CONFLICT",
            }
            candidate["title_match_class"]="EXACT_SOURCE_MEMBER_TITLE"
            candidates=[candidate]
        elif reference_meta["note_item_ordinal"]:
            if not note_matches:
                tier1_failure_reason=(
                    "SOURCE_TARGET_REJECTED_AND_INDEX_TARGET_NOT_FOUND"
                    if source_target_page else
                    "NOTE_REFERENCE_PARSED_BUT_INDEX_TARGET_NOT_FOUND"
                )
            else:
                # A same-note continuation can create more than one index row.
                # Preserve only title-compatible headings as formal Tier 1
                # candidates; a reference match with a contradictory title is
                # explained, not silently sent to Tier 3.
                if not compatible:
                    tier1_failure_reason=(
                        "SOURCE_TARGET_REJECTED_NOTE_REFERENCE_TITLE_CONFLICT"
                        if source_target_page else "NOTE_REFERENCE_TITLE_CONFLICT"
                    )
        elif reference:
            tier1_failure_reason="NOTE_REFERENCE_PARSE_FAILED"
        else:
            tier1_failure_reason="INLINE_NOTE_REFERENCE_MISSING"
        counts["TIER1"]=len(candidates);times["TIER1"]=(time.perf_counter()-t)*1000
        reliable_t1=(
            len(candidates)==1 and self._scope_ok(candidates[0],requested_scope)
            and str(candidates[0].get("title_match_class") or "") != "SEMANTIC_ONLY"
        )
        early="EXPLICIT_REFERENCE_UNIQUE_MATCH" if reliable_t1 else None
        # Tier 2 is strictly lazy.
        if reliable_t1:
            skipped.extend(["TIER2","TIER3"])
        else:
            t=time.perf_counter();executed.append("TIER2")
            aliases=_contract_titles(member_contract) or [child["raw_label"]]
            certified=member_contract.get("certified_company_aliases") or []
            norm_aliases={_norm(x) for x in aliases if x}
            exact=[h for h in eligible_headings if h["raw_heading"].strip() in aliases]
            normalized=[h for h in eligible_headings if h["normalized_heading"] in norm_aliases and h not in exact]
            certified_hits=[h for h in eligible_headings if h["normalized_heading"] in {_norm(x) for x in certified}]
            selected=[];method=""
            if len(exact)==1:selected=exact;method="T2A_CANONICAL_EXACT"
            elif normalized:selected=normalized;method="T2B_NORMALIZED_EXACT"
            elif certified_hits:selected=certified_hits;method="T2C_CERTIFIED_ALIAS"
            else:
                tokens=set(_norm(aliases[0])) if aliases else set()
                scored=[]
                for h in eligible_headings:
                    target=set(h["normalized_heading"])
                    sim=len(tokens&target)/max(1,len(tokens|target))
                    if sim>=0.45:scored.append((sim,h))
                selected=[h for _,h in sorted(scored,key=lambda x:-x[0])];method="T2D_BOUNDED_SEMANTIC"
            selected=selected[:self.limits["TIER2"]]
            candidates=[self._thin(run_id,child,h,"TIER2",method,2,idx["source_pdf_sha256"],
                                   ["INLINE_NOTE_REFERENCE_MISSING"] if not reference else [])
                        for h in selected]
            counts["TIER2"]=len(candidates);times["TIER2"]=(time.perf_counter()-t)*1000
            reliable_t2=len(candidates)==1 and method in {"T2A_CANONICAL_EXACT","T2B_NORMALIZED_EXACT","T2C_CERTIFIED_ALIAS"}
            if reliable_t2:
                early=f"{method}_UNIQUE";skipped.append("TIER3")
            else:
                t=time.perf_counter();executed.append("TIER3")
                raw_forms={_norm(child.get("raw_label")),_norm(re.sub(r"[（(].*?[）)]","",str(child.get("raw_label") or "")))}
                fallback=[h for h in eligible_headings if any(x and x in h["normalized_heading"] for x in raw_forms)]
                candidates=[self._thin(run_id,child,h,"TIER3","TIER3_RAW_FALLBACK",3,
                                       idx["source_pdf_sha256"],
                                       ["RAW_LABEL_FALLBACK_USED","RULE_GAP_CANDIDATE"])
                            for h in fallback[:self.limits["TIER3"]]]
                counts["TIER3"]=len(candidates);times["TIER3"]=(time.perf_counter()-t)*1000
        candidates=self._dedup(candidates)
        run={
            "discovery_run_id":run_id,"source_pdf_id":str(pdf_path),
            "source_pdf_sha256":idx["source_pdf_sha256"],"anchor_id":child["anchor_id"],
            "anchor_child_id":child["anchor_child_id"],"requested_scope":requested_scope,
            "tiers_executed":executed,"tiers_skipped":skipped,"early_stop_reason":early,
            "candidate_count_by_tier":counts,"runtime_by_tier":times,
            "metrics":{"index_build_ms":idx["index_build_ms"],"index_cache_hit":idx["cache_hit"],
                       "dedup_count":sum(counts.values())-len(candidates),
                       "full_capture_count":0,"all_pdf_table_scan":False,
                       "all_pdf_amount_search":False,
                       "index_version":INDEX_VERSION,
                       "tier1_failure_reason":tier1_failure_reason,
                       "main_statement_page":amount_source_page_number,
                       "candidate_pages_rejected_not_after_main_statement":len(
                           rejected_not_after_main_statement
                       ),
                       "note_reference":reference_meta,
                       "discovery_version":DISCOVERY_VERSION},"status":"CANDIDATES_READY",
            "created_at":now_iso(),
        }
        self.repo.save_run(run,candidates)
        return {"run":run,"candidates":candidates,"index":idx}

    @staticmethod
    def _scope_ok(candidate:dict[str,Any],requested_scope:str)->bool:
        hint=(
            candidate.get("statement_scope_hint")
            or candidate.get("statement_scope_context")
            or "UNKNOWN"
        )
        return hint in {"UNKNOWN",requested_scope}

    @staticmethod
    def _automatic_identity_gates_resolved(link:dict[str,Any])->bool:
        hard_gates=dict(link.get("hard_gate_results") or {})
        failed={key for key,value in hard_gates.items() if not value}
        blocking={str(value) for value in (link.get("blocking_warnings") or [])}
        if not failed and not blocking:
            return True
        amount_only={
            "main_statement_amount_present",
            "MAIN_STATEMENT_MEMBER_AMOUNT_MISSING",
        }
        candidate=dict(link.get("candidate") or {})
        return bool(
            failed <= amount_only
            and blocking <= amount_only
            and hard_gates.get("note_reference_matches_anchor") is True
            and str(candidate.get("retrieval_tier") or "").upper()=="TIER1"
            and str(link.get("note_table_inventory_status") or "").upper()
            =="COMPLETE"
        )

    @staticmethod
    def _dedup(rows:list[dict[str,Any]])->list[dict[str,Any]]:
        out={}
        for row in rows:
            key=(row["source_pdf_sha256"],row["heading_id"],row["normalized_heading"],
                 row["start_page"],row.get("statement_scope_hint"))
            if key not in out:out[key]=row
            else:
                out[key].setdefault("contributing_methods",[]).append(row["retrieval_method"])
        return list(out.values())

    @staticmethod
    def _inventory_payload(
        candidate:dict[str,Any],scan_scope:dict[str,Any],
        structure:dict[str,Any],
    )->dict[str,Any]:
        segments_by_logical:dict[str,list[dict[str,Any]]]={}
        for segment in structure.get("segment_candidates") or []:
            segments_by_logical.setdefault(
                str(segment.get("logical_table_candidate_id") or ""),[]
            ).append(dict(segment))
        logical_tables=[]
        for logical in structure.get("logical_table_candidates") or []:
            logical_id=str(logical.get("logical_table_candidate_id") or "")
            logical_tables.append({
                **dict(logical),
                "segments":sorted(
                    segments_by_logical.get(logical_id,[]),
                    key=lambda item:int(
                        item.get("segment_order",item.get("order",0))
                    ),
                ),
            })
        return {
            "note_table_inventory_candidate_id":structure["inventory_id"],
            "candidate_id":candidate["candidate_id"],
            "source_pdf_id":candidate.get("source_pdf_id") or "",
            "source_pdf_sha256":candidate.get("source_pdf_sha256") or "",
            "note_reference":candidate.get("note_reference") or "",
            "note_title":candidate.get("raw_heading") or "",
            "scan_start_page":scan_scope["scan_start_page"],
            "scan_end_page":scan_scope["scan_end_page"],
            "next_note_boundary_page":scan_scope.get(
                "next_note_boundary_page"
            ),
            "scan_scope":{
                **scan_scope,
                "planner_version":structure.get("planner_version"),
                "planner_boundary_status":structure.get("boundary_status"),
            },
            "peer_table_count":int(bool(
                scan_scope.get("next_note_boundary_page")
                and structure.get("boundary_status")=="VERIFIED_PEER_BOUNDARY"
            )),
            "inventory_status":structure.get("inventory_status") or "INCOMPLETE",
            "evidence":{
                "source":"NATIVE_PDF_LINES",
                "issue_codes":list(structure.get("issue_codes") or []),
                "boundary_evidence":dict(
                    structure.get("boundary_evidence") or {}
                ),
                "header_arbitration":dict(
                    structure.get("header_arbitration") or {}
                ),
                "peer_table_boundary":({
                    "classification":"PEER_TABLE",
                    "note_reference":scan_scope.get("next_note_reference"),
                    "title":scan_scope.get("next_note_title"),
                    "page":scan_scope.get("next_note_boundary_page"),
                    "bbox":scan_scope.get("next_note_boundary_bbox") or {},
                    "method":"NEXT_PEER_HEADING",
                    "confidence":"HIGH",
                } if structure.get("boundary_status")=="VERIFIED_PEER_BOUNDARY"
                else {}),
            },
            "logical_tables":logical_tables,
        }

    def enrich_top_k(self,pdf_path:Path,child:dict[str,Any],
                     candidates:list[dict[str,Any]],
                     member_contract:dict[str,Any]|None=None)->list[dict[str,Any]]:
        member_contract=dict(member_contract or {})
        ranked=sorted(candidates,key=lambda x:(x["retrieval_priority"],-x["base_score"],x["start_page"]))
        output=[]
        from spatial_table_capture import (
            _page_lines,plan_table_structure_candidates,
        )
        with fitz.open(str(pdf_path)) as doc:
            for candidate in ranked[:self.limits["ENRICHMENT_TOP_K"]]:
                cached=self.repo.cached_enriched(candidate["candidate_id"])
                if cached:
                    output.append(cached)
                    continue
                started=time.perf_counter()
                scan_scope=self.index.bounded_note_scope(
                    candidate,page_count=doc.page_count,
                )
                scan_start=int(scan_scope["scan_start_page"])
                scan_end=int(scan_scope["scan_end_page"])
                lines_by_page={
                    page_number:_page_lines(doc,page_number)
                    for page_number in range(scan_start,scan_end+1)
                }
                page_widths={
                    page_number:float(doc[page_number-1].rect.width)
                    for page_number in range(scan_start,scan_end+1)
                }
                boundary_bbox=scan_scope.get("next_note_boundary_bbox") or {}
                if isinstance(boundary_bbox,dict):
                    boundary_y0=boundary_bbox.get("y0",boundary_bbox.get("top"))
                elif isinstance(boundary_bbox,(list,tuple)) and len(boundary_bbox)==4:
                    boundary_y0=boundary_bbox[1]
                else:
                    boundary_y0=None
                peer_verified=bool(
                    scan_scope.get("boundary_status")=="CONFIRMED_PEER_HEADING"
                    and boundary_y0 is not None
                )
                boundary={
                    "boundary_reason":(
                        "next_peer_heading" if peer_verified
                        else "peer_boundary_geometry_unresolved"
                    ),
                    "boundary_confidence":"HIGH" if peer_verified else "LOW",
                    "boundary_status":(
                        "VERIFIED_PEER_BOUNDARY" if peer_verified else "UNRESOLVED"
                    ),
                    "end_y":(
                        max(0.0,float(boundary_y0)-0.01)
                        if peer_verified else None
                    ),
                    "boundary_evidence":{
                        "method":"NEXT_PEER_HEADING" if peer_verified else "UNRESOLVED",
                        "next_note_verified":peer_verified,
                        "next_note_pdf_page_index":scan_scope.get(
                            "next_note_boundary_page"
                        ),
                        "next_note_y0":(
                            float(boundary_y0) if boundary_y0 is not None else None
                        ),
                        "next_note_bbox":boundary_bbox,
                        "next_note_reference":scan_scope.get("next_note_reference"),
                        "next_note_title":scan_scope.get("next_note_title"),
                    },
                }
                title_bbox=candidate.get("heading_bbox") or {}
                if str(candidate.get("heading_id") or "").startswith(
                    "SOURCE_NOTE_TARGET::"
                ):
                    title_bbox={}
                structure=plan_table_structure_candidates(
                    lines_by_page,page_widths,
                    start_page=scan_start,end_page=scan_end,
                    title_bbox=title_bbox,
                    note_identity=scan_scope.get("note_identity") or "",
                    table_identity=candidate.get("raw_heading") or child.get("raw_label") or "",
                    unit=child.get("unit") or "",
                    boundary=boundary,
                    candidate_namespace=candidate["candidate_id"],
                )
                inventory=self._inventory_payload(candidate,scan_scope,structure)
                text="\n".join(
                    str(line.get("text") or "")
                    for line in lines_by_page.get(scan_start,[])
                )
                numbers=_numbers(text)
                requested=child.get("statement_scope") or "UNKNOWN"; hint=_scope(text)
                scope_ok=hint in {"UNKNOWN",requested}
                has_table=len(numbers)>=4 and len(text.splitlines())>=4
                relation,status=self._reconcile(child,numbers)
                title_class,title_score,_=_best_title_match(member_contract,candidate.get("raw_heading"))
                role=_subtable_role(candidate.get("raw_heading"),member_contract)
                anchor_note=_note_reference_key(
                    child.get("inline_note_reference") or child.get("note_reference_normalized")
                )
                candidate_note=_note_reference_key(candidate.get("note_reference"))
                note_match=bool(
                    anchor_note["note_item_ordinal"]
                    and anchor_note["note_item_ordinal"] == candidate_note["note_item_ordinal"]
                )
                amount_present=bool(_numeric_amounts(
                    child.get("statement_amount_normalized") or child.get("statement_amount_raw")
                ))
                allow_no_direct=bool(member_contract.get("allow_no_direct_amount_relation"))
                hard={
                    "source_pdf_match":True,"scope_no_conflict":scope_ok,
                    "allowed_section":candidate["section_type"]=="FINANCIAL_STATEMENT_NOTES",
                    "heading_found":True,"table_or_disclosure_evidence":has_table,
                    "not_toc_or_header":not any(x in text[:300] for x in EXCLUDED_SECTION_MARKERS),
                    "main_statement_amount_present":amount_present or allow_no_direct,
                    "note_table_inventory_complete":(
                        structure.get("inventory_status")=="COMPLETE"
                    ),
                }
                role_score=0.12 if role=="PRIMARY_AMOUNT_DETAIL" else 0.04
                note_score=0.24 if note_match else 0.0
                section_score=0.16*(candidate["section_type"]=="FINANCIAL_STATEMENT_NOTES")
                scope_score=0.10*scope_ok
                table_score=0.08*has_table
                amount_score=0.20*(status.startswith("PASS"))
                evidence=title_score+role_score+note_score+section_score+scope_score+table_score+amount_score
                penalties=0.45*sum(not x for x in hard.values())
                score=max(0,min(1,0.04+evidence-penalties))
                positive=[k for k,v in hard.items() if v]
                if note_match:positive.append("NOTE_REFERENCE_MATCHES_ANCHOR")
                if status.startswith("PASS"):positive.append(relation)
                row={
                    **candidate,"container_page_range":[scan_start,scan_end],
                    "possible_subtable_roles":[role],"title_match_class":title_class,
                    "note_reference_match":note_match,
                    "scope_evidence":{"requested":requested,"page_hint":hint},
                    "period_evidence":{"years":sorted(set(re.findall(r"20\\d{2}",text)))},
                    "unit_evidence":{"unit":_unit(text),"inherited":not bool(_unit(text))},
                    "lightweight_table_presence":has_table,
                    "lightweight_header_signature":[x for x in text.splitlines()[:12] if x.strip()],
                    "lightweight_row_signature":[x for x in text.splitlines()[12:30] if x.strip()],
                    "amount_summary":{"number_count":len(numbers)},
                    "reconciliation_candidates":[{"relation":relation,"status":status,"anchor_amount_present":amount_present}],
                    "certification_score":score,
                    "score_breakdown":{"retrieval_prior":candidate["base_score"],
                                       "title_match_class":title_class,"title_score":title_score,
                                       "note_reference_score":note_score,"section_score":section_score,
                                       "scope_score":scope_score,"table_presence_score":table_score,
                                       "role_score":role_score,"amount_reconciliation_score":amount_score,
                                       "evidence_score":evidence,"penalties":penalties,
                                       "final_certification_score":score},
                    "hard_gate_results":hard,
                    "positive_evidence":positive,
                    "negative_evidence":[k for k,v in hard.items() if not v] + list(
                        structure.get("issue_codes") or []
                    ) + (
                        ["MAIN_STATEMENT_MEMBER_AMOUNT_MISSING"] if not amount_present and not allow_no_direct else []
                    ),
                    "enrichment_runtime_ms":(time.perf_counter()-started)*1000,
                    "enrichment_version":ENRICHMENT_VERSION,
                    "note_table_inventory":inventory,
                }
                self.repo.save_enriched(row,inventory=inventory);output.append(row)
        return output

    @staticmethod
    def _reconcile(child:dict[str,Any],numbers:list[float])->tuple[str,str]:
        values=child.get("statement_amount_normalized") or child.get("statement_amount_raw") or []
        anchors=_numeric_amounts(values)
        if not anchors:
            return "MAIN_STATEMENT_MEMBER_AMOUNT_MISSING","MISSING_MAIN_STATEMENT_AMOUNT"
        for anchor in anchors:
            if any(abs(x-anchor)<=max(0.5,abs(anchor)*1e-8) for x in numbers):
                return "EXACT_TOTAL","PASS_EXACT"
            for gross in numbers[:30]:
                for allowance in numbers[:30]:
                    if gross>=allowance and abs((gross-allowance)-anchor)<=max(0.5,abs(anchor)*1e-8):
                        return "GROSS_MINUS_ALLOWANCE_EQUALS_ANCHOR","PASS_EXACT"
        return "NO_DIRECT_AMOUNT_RELATION","NOT_TESTABLE"

    def link_candidates(self,anchor:dict[str,Any],child:dict[str,Any],
                        enriched:list[dict[str,Any]],member_contract:dict[str,Any])->list[dict[str,Any]]:
        rows=[]; expanded=[]
        for enriched_candidate in enriched:
            inventory=(
                enriched_candidate.get("effective_note_table_inventory")
                or enriched_candidate.get("note_table_inventory") or {}
            )
            logical_tables=[
                item for item in (inventory.get("logical_tables") or [])
                if str(
                    item.get("classification")
                    or item.get("proposed_classification") or ""
                ).upper() in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}
            ]
            if not logical_tables:
                continue
            for logical in logical_tables:
                classification=str(
                    logical.get("classification")
                    or logical.get("proposed_classification") or ""
                ).upper()
                expanded.append({
                    **enriched_candidate,
                    "raw_heading":logical.get("title")
                        or enriched_candidate.get("raw_heading") or "",
                    "logical_table_candidate_id":logical.get(
                        "logical_table_candidate_id"
                    ),
                    "logical_table_candidate":logical,
                    "table_classification":classification,
                    "note_table_inventory_candidate_id":inventory.get(
                        "note_table_inventory_candidate_id"
                    ),
                    "note_table_inventory_status":inventory.get(
                        "inventory_status"
                    ) or "INCOMPLETE",
                })
        ordered=sorted(
            expanded,
            key=lambda x:(
                str(x.get("table_classification") or "PRIMARY_TABLE")
                    != "PRIMARY_TABLE",
                -x["certification_score"],
            ),
        )
        for i,x in enumerate(ordered):
            relation=(x["reconciliation_candidates"] or [{}])[0]
            anchor_note_reference=str(
                child.get("note_reference_normalized")
                or child.get("note_reference")
                or child.get("inline_note_reference")
                or ""
            )
            candidate_note_reference=str(x.get("note_reference") or "")
            hard_gates=dict(x["hard_gate_results"])
            note_match=bool(
                anchor_note_reference and candidate_note_reference
                and _leaf_note_ordinal(anchor_note_reference)
                == _leaf_note_ordinal(candidate_note_reference)
            )
            if anchor_note_reference:
                hard_gates["note_reference_matches_anchor"] = note_match
            table_classification=str(
                x.get("table_classification") or "PRIMARY_TABLE"
            ).upper()
            role=(
                "PRIMARY_AMOUNT_DETAIL"
                if table_classification=="PRIMARY_TABLE"
                else _subtable_role(
                    x.get("raw_heading"),member_contract,
                    table_classification=table_classification,
                )
            )
            if table_classification=="SUPPLEMENTARY_TABLE":
                relation={
                    "relation":"SUPPLEMENTARY_DISCLOSURE",
                    "status":"NOT_TESTABLE",
                }
            inventory_status=str(
                x.get("note_table_inventory_status") or ""
            ).upper()
            if x.get("logical_table_candidate_id"):
                hard_gates["note_table_inventory_complete"]=(
                    inventory_status=="COMPLETE"
                )
                hard_gates["logical_table_resolved"]=(
                    table_classification in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}
                )
            positive_evidence=list(x.get("positive_evidence") or [])
            if note_match and "NOTE_REFERENCE_MATCHES_ANCHOR" not in positive_evidence:
                positive_evidence.append("NOTE_REFERENCE_MATCHES_ANCHOR")
            negatives=list(x.get("negative_evidence") or [])
            blocking=[k for k,v in hard_gates.items() if not v]
            if "MAIN_STATEMENT_MEMBER_AMOUNT_MISSING" in negatives:
                blocking.append("MAIN_STATEMENT_MEMBER_AMOUNT_MISSING")
            logical_table_candidate_id=str(
                x.get("logical_table_candidate_id") or ""
            )
            rows.append({
                "link_candidate_id":_stable_candidate_id(
                    "LKC",anchor["occurrence_id"],child["anchor_child_id"],
                    x["candidate_id"],logical_table_candidate_id or "LEGACY",
                ),"anchor_id":anchor["occurrence_id"],
                "anchor_child_id":child["anchor_child_id"],"candidate_id":x["candidate_id"],
                "logical_table_candidate_id":logical_table_candidate_id or None,
                "proposed_member_table_id":member_contract.get("member_table_id") or child["raw_label"],
                "proposed_subtable_role":role,
                "proposed_relation_type":relation.get("relation") or "UNRESOLVED_RELATION",
                "statement_scope":child["statement_scope"],"report_year":child.get("report_year"),
                "retrieval_prior":x["base_score"],
                "evidence_score":x["score_breakdown"]["evidence_score"],
                "penalty_score":x["score_breakdown"]["penalties"],
                "certification_score":x["certification_score"],
                "score_breakdown":x["score_breakdown"],"hard_gate_results":hard_gates,
                "reconciliation_relation":relation.get("relation"),
                "reconciliation_status":relation.get("status"),
                "confidence":min(
                    float(x["certification_score"]),
                    _confidence_value(
                        (x.get("logical_table_candidate") or {}).get("confidence")
                        or x["certification_score"]
                    ),
                ),
                "anchor_note_reference":anchor_note_reference,
                "table_classification":table_classification,
                "note_table_inventory_candidate_id":x.get(
                    "note_table_inventory_candidate_id"
                ),
                "note_table_inventory_status":inventory_status or None,
                "table_family_id":str(
                    anchor.get("table_family_id")
                    or anchor.get("table_family")
                    or member_contract.get("table_family_id") or ""
                ),
                "research_project_id":anchor.get("research_project_id"),
                "research_task_id":anchor.get("research_task_id"),
                "research_definition_id":child.get("research_definition_id"),
                "definition_version":child.get("definition_version"),
                "data_year":child.get("data_year"),
                "positive_evidence":positive_evidence,"negative_evidence":negatives,
                "blocking_warnings":blocking,
                "ranking_position":i+1,"is_recommended":False,"is_preselected":False,
                "is_supplementary_recommended":False,
                "candidate":x,
            })
        if rows:
            primary=[x for x in rows if x["proposed_subtable_role"]=="PRIMARY_AMOUNT_DETAIL"]
            supplementary=[x for x in rows if x["proposed_subtable_role"]!="PRIMARY_AMOUNT_DETAIL"]
            for role in sorted({x["proposed_subtable_role"] for x in supplementary}):
                role_rows=[x for x in supplementary if x["proposed_subtable_role"]==role]
                if role_rows:
                    role_rows[0]["is_supplementary_recommended"]=True
            if not primary:
                self.repo.save_link_candidates(rows)
                return rows
            primary[0]["is_recommended"]=True
            margin=primary[0]["certification_score"]-(primary[1]["certification_score"] if len(primary)>1 else 0)
            # A sole viable note table should be selected for the human review
            # form by default.  This is not automatic certification: the user
            # still clicks the explicit certification action.
            sole_viable=bool(
                len(primary)==1
                and self._automatic_identity_gates_resolved(primary[0])
            )
            primary[0]["is_preselected"]=bool(sole_viable or (
                primary[0]["certification_score"]>=0.85 and margin>=0.10
                and self._automatic_identity_gates_resolved(primary[0])
            ))
            if sole_viable:
                primary[0]["preselection_reason"]=(
                    "SOLE_VIABLE_PRIMARY_CANDIDATE"
                    if all(primary[0]["hard_gate_results"].values())
                    else "SOLE_VIABLE_NOTE_IDENTITY_WITHOUT_AMOUNT_RECONCILIATION"
                )
        self.repo.save_link_candidates(rows)
        return rows

    def _adopt_existing_container_links(
        self, inventory: dict[str, Any],
        inventory_links: list[dict[str, Any]],
        candidate_id: str,
    ) -> list[dict[str, Any]] | None:
        """Reuse certified links for an already-certified note container.

        Re-discovery/re-certification of the same PDF creates a fresh
        candidate/inventory tree with new candidate IDs.  When the same note
        container (source PDF + leaf note ordinal) already carries a CERTIFIED
        inventory with content-equivalent logical tables (same member tables
        and classifications) and the PDF identity has not drifted, adopting the
        existing certified links makes re-certification idempotent and avoids
        the ``NOTE_TABLE_INVENTORY_ID_MISMATCH`` dead end that would otherwise
        leave Stage B with zero certified plans.
        """
        source_pdf_id = str(inventory.get("source_pdf_id") or "").strip()
        note_reference = str(inventory.get("note_reference") or "").strip()
        note_ordinal = _leaf_note_ordinal(note_reference)
        if not source_pdf_id or note_ordinal is None:
            return None
        expected = {
            (
                str(link.get("proposed_member_table_id") or "").strip(),
                str(link.get("table_classification") or "").upper(),
            )
            for link in inventory_links
            if str(link.get("candidate_id") or "") == candidate_id
            and str(link.get("logical_table_candidate_id") or "")
        }
        if not expected:
            return None
        with self.repo.registry.connect() as conn:
            rows = conn.execute(
                """SELECT l.*, t.source_pdf_id AS candidate_pdf_id,
                          t.source_pdf_sha256 AS candidate_pdf_sha256,
                          t.note_reference AS candidate_note_reference
                   FROM certified_child_table_links l
                   JOIN thin_child_table_candidates t
                     ON t.candidate_id = l.candidate_id
                   WHERE t.source_pdf_id = ?
                     AND l.certification_status = 'CERTIFIED'
                     AND COALESCE(l.note_table_inventory_id,'') <> ''
                   ORDER BY l.certified_at DESC""",
                (source_pdf_id,),
            ).fetchall()
        existing = [
            dict(row) for row in rows
            if _leaf_note_ordinal(
                str(row["candidate_note_reference"] or "")
            ) == note_ordinal
        ]
        if not existing:
            return None
        container_inventory_ids = {
            str(link.get("note_table_inventory_id") or "").strip()
            for link in existing
        }
        if len(container_inventory_ids) != 1:
            return None
        existing_cover = {
            (
                str(link.get("member_table_id") or "").strip(),
                str(link.get("table_classification") or "").upper(),
            )
            for link in existing
        }
        if existing_cover != expected:
            return None
        existing_shas = {
            str(link.get("candidate_pdf_sha256") or "").strip()
            for link in existing
        }
        current_sha = str(inventory.get("source_pdf_sha256") or "").strip()
        if existing_shas and current_sha and existing_shas != {current_sha}:
            return None
        adopted: list[dict[str, Any]] = []
        for link in existing:
            persisted = dict(link)
            target = self.repo.certified_target(
                str(persisted["certified_link_id"])
            )
            if not target:
                return None
            persisted["certified_segments"] = (
                target.get("certified_segments") or []
            )
            adopted.append(persisted)
        return adopted

    def _auto_certify_inventory_links(
        self,chosen:dict[str,Any],links:list[dict[str,Any]],
    )->list[dict[str,Any]]:
        candidate_id=str(chosen.get("candidate_id") or "").strip()
        inventory_candidate_id=str(
            chosen.get("note_table_inventory_candidate_id") or ""
        ).strip()
        if not candidate_id or not inventory_candidate_id:
            raise PermissionError("UNRESOLVED_NOTE_TABLE_INVENTORY")
        inventory=(
            self.repo.effective_candidate_inventory(candidate_id)
            or self.repo.candidate_inventory(candidate_id)
        )
        if not inventory or str(
            inventory.get("note_table_inventory_candidate_id") or ""
        )!=inventory_candidate_id:
            raise PermissionError("UNRESOLVED_NOTE_TABLE_INVENTORY")
        if (
            str(inventory.get("inventory_status") or "").upper()!="COMPLETE"
            or int(inventory.get("unresolved_table_count") or 0)>0
        ):
            raise PermissionError("UNRESOLVED_NOTE_TABLE_INVENTORY")
        logical_tables=[
            item for item in (inventory.get("logical_tables") or [])
            if str(
                item.get("classification")
                or item.get("proposed_classification") or ""
            ).upper() in {"PRIMARY_TABLE","SUPPLEMENTARY_TABLE"}
        ]
        human_adjudicated=bool(
            str(inventory.get("source_adjudication_id") or "").strip()
        )
        for logical_table in logical_tables:
            for segment in logical_table.get("segments") or []:
                evidence=dict(segment.get("evidence") or {})
                coverage=dict(evidence.get("signature_coverage") or {})
                classification=str(
                    segment.get("classification")
                    or segment.get("proposed_classification") or ""
                ).upper()
                period_coverage_resolved=bool(
                    coverage.get("period") is True
                    or (
                        human_adjudicated
                        and classification=="SUPPLEMENTARY_TABLE"
                    )
                )
                coverage_complete=bool(
                    coverage.get("page_bbox") is True
                    and period_coverage_resolved
                    and coverage.get("header") is True
                    and coverage.get("amount_lanes") is True
                    and str(coverage.get("source") or "").upper()
                    =="BOUNDED_NATIVE_TEXT"
                )
                if not coverage_complete:
                    raise PermissionError(
                        "AUTOMATIC_SEGMENT_SIGNATURE_COVERAGE_REQUIRED"
                    )
                consistency=dict(evidence.get("consistency_audit") or {})
                false_fields={
                    key for key,value in consistency.items()
                    if value is False
                }
                if classification=="SUPPLEMENTARY_TABLE":
                    reasons={
                        str(code).upper()
                        for code in (evidence.get("reason_codes") or [])
                    }
                    axis_reset=bool(reasons&{
                        "AMOUNT_LANE_TOPOLOGY_RESET",
                        "MEASURE_AXIS_RESET",
                        "PERIOD_AXIS_RESET",
                    })
                    independent_reset=bool(
                        "INDEPENDENT_LOCAL_HEADER" in reasons
                        and (
                            axis_reset
                            or {
                                "PRECEDING_LOCAL_TOTAL",
                                "NARRATIVE_SEPARATOR",
                            }.issubset(reasons)
                        )
                    )
                    if not independent_reset:
                        raise PermissionError(
                            "AUTOMATIC_SUPPLEMENTARY_RESET_EVIDENCE_REQUIRED"
                        )
                elif false_fields:
                    raise PermissionError(
                        "AUTOMATIC_SEGMENT_CONSISTENCY_AUDIT_FAILED:"
                        +",".join(sorted(false_fields))
                    )
        expected_logical_ids={
            str(item.get("logical_table_candidate_id") or "")
            for item in logical_tables
            if str(item.get("logical_table_candidate_id") or "")
        }
        inventory_links=[
            item for item in links
            if str(item.get("candidate_id") or "")==candidate_id
            and str(item.get("note_table_inventory_candidate_id") or "")
            ==inventory_candidate_id
            and str(item.get("logical_table_candidate_id") or "")
        ]
        by_logical_id={
            str(item["logical_table_candidate_id"]):item
            for item in inventory_links
        }
        if not expected_logical_ids or set(by_logical_id)!=expected_logical_ids:
            raise PermissionError("UNRESOLVED_LOGICAL_TABLE_LINK_SET")
        primary_links=[
            item for item in inventory_links
            if str(item.get("table_classification") or "").upper()
            =="PRIMARY_TABLE"
        ]
        if len(primary_links)!=1 or primary_links[0]["link_candidate_id"]!=(
            chosen["link_candidate_id"]
        ):
            raise PermissionError("UNRESOLVED_PRIMARY_LOGICAL_TABLE")
        if not self._automatic_identity_gates_resolved(chosen):
            raise PermissionError("UNRESOLVED_AUTOMATIC_CERTIFICATION_GATES")
        adopted = self._adopt_existing_container_links(
            inventory, inventory_links, candidate_id,
        )
        if adopted is not None:
            return adopted
        certified_inventory=self.repo.certify_note_table_inventory(
            inventory_candidate_id,
            reviewer="SYSTEM_RULE_ENGINE",
            method="AUTO_COMPLETE_INVENTORY_V1",
            reason="完整候选清单无未决关系且主表候选唯一",
            source_adjudication_id=str(
                inventory.get("source_adjudication_id") or ""
            ),
            evidence={
                "policy":"AUTO_COMPLETE_INVENTORY_V1",
                "chosen_primary_link_candidate_id":chosen["link_candidate_id"],
                "hard_gate_results":dict(chosen.get("hard_gate_results") or {}),
                "amount_reconciliation_deferred":bool(
                    not (chosen.get("hard_gate_results") or {}).get(
                        "main_statement_amount_present",True
                    )
                ),
                "logical_table_candidate_ids":sorted(expected_logical_ids),
            },
        )
        alternative_candidate_ids=sorted({
            str(item.get("candidate_id") or "") for item in links
            if str(item.get("candidate_id") or "")
            and str(item.get("candidate_id") or "")!=candidate_id
        })
        certified_links=[]
        for logical_id in sorted(
            expected_logical_ids,
            key=lambda value:int(
                next(
                    item.get("table_order",0) for item in logical_tables
                    if str(item.get("logical_table_candidate_id") or "")==value
                )
            ),
        ):
            link=by_logical_id[logical_id]
            payload={
                **link,
                "table_family_id":str(link.get("table_family_id") or "UNKNOWN"),
                "member_table_id":link["proposed_member_table_id"],
                "subtable_role":link["proposed_subtable_role"],
                "relation_type":link["proposed_relation_type"],
                "selected_candidate_id":candidate_id,
                "recommended_candidate_id":candidate_id,
                "alternative_candidates":alternative_candidate_ids,
                "score_snapshot":{
                    "certification_score":link["certification_score"],
                    "breakdown":dict(link.get("score_breakdown") or {}),
                },
                "evidence_snapshot":{
                    "hard_gates":dict(link.get("hard_gate_results") or {}),
                    "positive_evidence":list(link.get("positive_evidence") or []),
                    "anchor_note_reference":str(
                        link.get("anchor_note_reference") or ""
                    ),
                    "automatic_certification_policy":(
                        "AUTO_COMPLETE_INVENTORY_V1"
                    ),
                },
                "reconciliation_result":{
                    "relation":link.get("reconciliation_relation"),
                    "status":link.get("reconciliation_status"),
                },
                "note_table_inventory_id":certified_inventory[
                    "note_table_inventory_id"
                ],
                "note_table_inventory_status":"COMPLETE",
            }
            certified_links.append(self.repo.certify(
                payload,
                reviewer="SYSTEM_RULE_ENGINE",
                method="AUTO_PROMOTE_CERTIFIED_LOGICAL_TABLE_V1",
                reason="从已认证 inventory 自动提升 logical link",
            ))
        return certified_links

    def assign_global(self,anchor_id:str,scope:str,links_by_child:dict[str,list[dict[str,Any]]])->dict[str,Any]:
        started=time.perf_counter();used=set();decisions=[];conflicts=[];rejected=[]
        certified_links=[]
        for child_id,links in links_by_child.items():
            chosen=None
            primary_links=[x for x in links if x.get("proposed_subtable_role")=="PRIMARY_AMOUNT_DETAIL"]
            for link in sorted(primary_links,key=lambda x:-x["certification_score"]):
                if link["statement_scope"]!=scope:continue
                key=link["candidate_id"]
                if key in used and link["proposed_subtable_role"].startswith("PRIMARY"):
                    conflicts.append({"anchor_child_id":child_id,"candidate_id":key,"reason":"PRIMARY_DOUBLE_ASSIGNMENT"})
                    rejected.append(link["link_candidate_id"]);continue
                chosen=link;used.add(key);break
            status=(
                "AUTO_CERTIFICATION_PENDING"
                if chosen and chosen.get("is_preselected")
                else "CHILD_TABLE_SELECTION_REQUIRED"
            )
            child_certified_links=[]
            auto_error=""
            if status=="AUTO_CERTIFICATION_PENDING":
                try:
                    child_certified_links=self._auto_certify_inventory_links(
                        chosen,links,
                    )
                    certified_links.extend(child_certified_links)
                    status="AUTO_CERTIFIED"
                except (PermissionError,ValueError) as exc:
                    auto_error=str(exc)
                    status="CHILD_TABLE_SELECTION_REQUIRED"
            if status=="CHILD_TABLE_SELECTION_REQUIRED":
                child=(links[0].get("candidate") or {}) if links else {}
                resolution_cases=self.repo.ensure_unresolved_inventory_cases(
                    anchor_child_id=child_id,
                    candidate_ids=[
                        str(link.get("candidate_id") or "") for link in links
                    ],
                )
                if resolution_cases:
                    resolution_case=resolution_cases[0]
                    status="UNRESOLVED_INVENTORY_REVIEW_REQUIRED"
                    self.repo.enqueue_child_review(
                        anchor_id=anchor_id,anchor_child_id=child_id,
                        logical_asset_id=str(child.get("logical_asset_id") or ""),
                        source_pdf_id=str(
                            resolution_case.get("source_pdf_id") or ""
                        ),
                        statement_scope=scope,
                        candidate_ids=[
                            case["candidate_id"] for case in resolution_cases
                        ],
                        resolution_case_id=resolution_case[
                            "resolution_case_id"
                        ],
                        reason="OPEN_UNRESOLVED_INVENTORY_CASE",
                        evidence={
                            "resolution_case_ids":[
                                case["resolution_case_id"]
                                for case in resolution_cases
                            ],
                            "scores":[
                                x["certification_score"] for x in links
                            ],
                            "conflicts":conflicts,
                        },
                    )
                    auto_error=(
                        auto_error or "OPEN_UNRESOLVED_INVENTORY_CASE"
                    )
                else:
                    status="AUTOMATION_REPAIR_REQUIRED"
                    auto_error=(
                        auto_error
                        or "NO_PERSISTED_UNRESOLVED_INVENTORY_CASE"
                    )
            decisions.append({
                "anchor_child_id":child_id,
                "link_candidate_id":chosen["link_candidate_id"] if chosen else None,
                "status":status,
                "certified_link_ids":[
                    item["certified_link_id"] for item in child_certified_links
                ],
                "unresolved_reason":auto_error or None,
            })
        assignment=self.repo.save_assignment({
            "assignment_id":"ASSIGN_"+uuid.uuid4().hex,"anchor_id":anchor_id,
            "statement_scope":scope,"decisions":decisions,"conflicts":conflicts,
            "rejected_links":rejected,"evidence":{
                "algorithm":"EXPLAINABLE_GREEDY_V2_AUTO_CERTIFY_COMPLETE_INVENTORY",
                "automatic_certification_count":len(certified_links),
            },
            "assignment_runtime_ms":(time.perf_counter()-started)*1000,
        })
        assignment["certified_links"]=certified_links
        return assignment

    def certified_capture_request(self,link:dict[str,Any],pdf_path:Path,*,
                                   research_batch_id:str="")->CaptureRequest:
        target=self.repo.certified_target(link["certified_link_id"])
        return CaptureRequest.new(
            capture_mode=CaptureMode.CERTIFIED_TARGET,source_pdf_path=str(pdf_path),
            source_pdf_id=target["source_pdf_id"],source_pdf_sha256=_sha(Path(pdf_path)),
            research_project_id=link.get("research_project_id") or "",
            research_task_id=link.get("research_task_id") or "",
            research_batch_id=research_batch_id,
            research_definition_id=link.get("research_definition_id") or "",
            definition_version=link.get("definition_version") or "",
            table_family_id=link["table_family_id"],
            member_table_id=link["member_table_id"],
            statement_anchor_id=link["anchor_id"],
            certified_target_id=link["certified_link_id"],
            request_metadata={
                "certified_target":target,
                "statement_scope":link["statement_scope"],
                "member_table_role":(
                    "DIRECT_MAIN_STATEMENT_TABLE"
                    if str(link.get("relation_type") or "")
                    == "DIRECT_MAIN_STATEMENT_WHOLE_TABLE"
                    else "NOTE_DETAIL"
                ),
                "note_number":target.get("note_reference") or None,
                "note_reference":target.get("note_reference") or None,
                "table_query":target.get("capture_query_title") or target.get("target_heading"),
            },
        )
