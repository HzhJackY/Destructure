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
from capture_models import CaptureMode, CaptureRequest
from version import APP_VERSION


INDEX_VERSION="FIN_NOTE_INDEX_V3_STRICT_HEADING_GATE"
DISCOVERY_VERSION="HIERARCHICAL_CHILD_V2"
ENRICHMENT_VERSION="LOCAL_TOPK_V2_CHILD_AMOUNT_AND_ROLE"
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
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    value = re.sub(
        r"^\s*(?:附注\s*)?[（(]?[一二三四五六七八九十百\d]+[）)、.．]\s*",
        "",
        value,
    ).strip()
    return value.rstrip("。；;：:").strip() or str(text or "").strip()


def _sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


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


def _subtable_role(heading: Any, member_contract: dict[str, Any]) -> str:
    normalized=_norm(heading)
    # A canonical table heading wins over disclosure-keyword heuristics:
    # FVTPL contains “公允价值…变动” and held-to-maturity contains “到期”,
    # but both are primary balance-sheet member tables, not supplementary
    # movement/maturity disclosures.
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
                # v6.10: only ACTIVE_CURRENT_PERIOD members are child-discovery
                # targets.  COMPARATIVE_ONLY_LEGACY_MEMBER, OUTSIDE_FAMILY, and
                # unresolved rows must not generate sub-table discovery jobs.
                period_status = str(child.get("member_period_status") or "")
                if period_status and period_status != "ACTIVE_CURRENT_PERIOD":
                    continue
                raw=str(child.get("item") or child.get("member_table") or "")
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
                    "normalized_label":_norm(raw),"canonical_concept_id":child.get("canonical_concept_id") or _norm(raw),
                    "concept_aliases":child.get("concept_aliases") or [],"row_order":order,
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
                        "amount_source_row_id":child.get("source_row_id") or child.get("statement_family_member_id") or "",
                        "amount_source_page":child.get("statement_pdf_page_index") or anchor.get("statement_pdf_page_index"),
                        "amount_source_bbox":child.get("bbox") or {},
                        "candidate_note_pdf_page_index":child.get("candidate_note_pdf_page_index") or child.get("note_page"),
                        "candidate_note_printed_page":child.get("candidate_note_printed_page"),
                        "locator_method":child.get("locator_method") or "",
                    },
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

    def cached_enriched(self,candidate_id:str)->dict[str,Any]|None:
        with self.registry.connect() as c:
            row=c.execute(
                """SELECT e.*,t.*
                   FROM enriched_child_table_candidates e
                   JOIN thin_child_table_candidates t ON t.candidate_id=e.candidate_id
                   WHERE e.candidate_id=? AND e.enrichment_version=?
                   AND e.producer_version=?""",
                (candidate_id,ENRICHMENT_VERSION,APP_VERSION)).fetchone()
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
        p["enrichment_cache_hit"]=True
        return p

    def save_enriched(self,row:dict[str,Any])->None:
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
                 row["enrichment_runtime_ms"],ENRICHMENT_VERSION,APP_VERSION,now_iso()))

    def save_link_candidates(self,rows:list[dict[str,Any]])->None:
        with self.registry.connect() as c:
            for p in rows:
                c.execute("""INSERT OR REPLACE INTO child_table_link_candidates(
                    link_candidate_id,anchor_id,anchor_child_id,candidate_id,
                    proposed_member_table_id,proposed_subtable_role,proposed_relation_type,
                    statement_scope,report_year,retrieval_prior,evidence_score,penalty_score,
                    certification_score,score_breakdown_json,hard_gate_results_json,
                    reconciliation_relation,reconciliation_status,confidence,
                    blocking_warnings_json,ranking_position,is_recommended,is_preselected,
                    producer_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["link_candidate_id"],p["anchor_id"],p["anchor_child_id"],
                     p["candidate_id"],p["proposed_member_table_id"],
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
                             reason:str,evidence:dict[str,Any])->dict[str,Any]:
        now=now_iso(); queue_id="CMRQ_"+uuid.uuid4().hex
        with self.registry.connect() as c:
            existing=c.execute(
                """SELECT queue_id FROM child_mapping_review_queue
                   WHERE anchor_child_id=? AND statement_scope=?""",
                (anchor_child_id,statement_scope)).fetchone()
            if existing:queue_id=existing["queue_id"]
            c.execute(
                """INSERT INTO child_mapping_review_queue(
                   queue_id,anchor_id,anchor_child_id,logical_asset_id,source_pdf_id,
                   statement_scope,status,primary_review_reason,candidate_ids_json,
                   evidence_json,producer_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,'PENDING',?,?,?,?,?,?)
                   ON CONFLICT(anchor_child_id,statement_scope) DO UPDATE SET
                   status='PENDING',primary_review_reason=excluded.primary_review_reason,
                   candidate_ids_json=excluded.candidate_ids_json,
                   evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                (queue_id,anchor_id,anchor_child_id,logical_asset_id,source_pdf_id,
                 statement_scope,reason,_json(candidate_ids),_json(evidence),
                 APP_VERSION,now,now))
        return {"queue_id":queue_id,"status":"PENDING","reason":reason}

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

    def certify(self,link:dict[str,Any],*,reviewer:str,method:str,reason:str="")->dict[str,Any]:
        certified_id="CLINK_"+uuid.uuid4().hex; now=now_iso()
        p={**link,"certified_link_id":certified_id,"certification_method":method,
           "certification_status":"CERTIFIED","reviewer":reviewer,"certified_at":now}
        with self.registry.connect() as c:
            c.execute("""INSERT INTO certified_child_table_links(
                certified_link_id,research_project_id,research_task_id,anchor_id,
                anchor_child_id,candidate_id,link_candidate_id,table_family_id,
                member_table_id,subtable_role,relation_type,statement_scope,report_year,
                data_year,certification_method,certification_status,score_snapshot_json,
                evidence_snapshot_json,reconciliation_result_json,recommended_candidate_id,
                selected_candidate_id,alternative_candidates_json,reviewer,certified_at,
                research_definition_id,definition_version,producer_version)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (certified_id,p.get("research_project_id"),p.get("research_task_id"),
                 p["anchor_id"],p["anchor_child_id"],p["candidate_id"],
                 p["link_candidate_id"],p["table_family_id"],p["member_table_id"],
                 p["subtable_role"],p["relation_type"],p["statement_scope"],
                 p.get("report_year"),p.get("data_year"),method,"CERTIFIED",
                 _json(p.get("score_snapshot") or {}),_json(p.get("evidence_snapshot") or {}),
                 _json(p.get("reconciliation_result") or {}),
                 p.get("recommended_candidate_id"),p["selected_candidate_id"],
                 _json(p.get("alternative_candidates") or []),reviewer,now,
                 p.get("research_definition_id"),p.get("definition_version"),APP_VERSION))
            c.execute("""INSERT INTO child_mapping_review_records(
                review_record_id,anchor_child_id,action,selected_candidate_id,
                rejected_candidates_json,reason,reviewer,evidence_json,producer_version,
                created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("CMREV_"+uuid.uuid4().hex,p["anchor_child_id"],method,p["candidate_id"],
                 _json(p.get("alternative_candidates") or []),reason,reviewer,
                 _json({"link_candidate_id":p["link_candidate_id"]}),APP_VERSION,now))
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
        record={"review_record_id":"CMREV_"+uuid.uuid4().hex,
                "anchor_child_id":anchor_child_id,"action":action,
                "selected_candidate_id":selected_candidate_id,
                "rejected_candidates":rejected_candidates or [],"reason":reason,
                "reviewer":reviewer,"evidence":evidence or {},
                "producer_version":APP_VERSION,"created_at":now_iso()}
        with self.registry.connect() as c:
            c.execute("""INSERT INTO child_mapping_review_records(
                review_record_id,anchor_child_id,action,selected_candidate_id,
                rejected_candidates_json,reason,reviewer,evidence_json,producer_version,
                created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (record["review_record_id"],anchor_child_id,action,selected_candidate_id,
                 _json(record["rejected_candidates"]),reason,reviewer,
                 _json(record["evidence"]),APP_VERSION,record["created_at"]))
            terminal_status="RESOLVED" if action in {
                "NO_CORRESPONDING_CHILD_TABLE","REJECT_LINK","ABSTAIN",
                "SELECT_ALTERNATIVE_LINK","MANUAL_ADD_LINK",
            } else "PENDING"
            c.execute(
                """UPDATE child_mapping_review_queue SET status=?,updated_at=?
                   WHERE anchor_child_id=?""",
                (terminal_status,record["created_at"],anchor_child_id))
        return record

    def certified_target(self,certified_link_id:str)->dict[str,Any]:
        with self.registry.connect() as c:
            row=c.execute("""SELECT l.*,t.start_page,t.end_page_hint,t.raw_heading,
                t.note_reference,t.source_pdf_id,t.heading_bbox_json,
                a.inline_note_reference AS anchor_inline_note_reference
                FROM certified_child_table_links l
                JOIN thin_child_table_candidates t ON t.candidate_id=l.candidate_id
                LEFT JOIN anchor_child_concepts a
                  ON a.anchor_child_id=l.anchor_child_id
                WHERE l.certified_link_id=? AND l.certification_status='CERTIFIED'""",
                (certified_link_id,)).fetchone()
        if not row:raise PermissionError("CERTIFIED_CHILD_TABLE_LINK_REQUIRED")
        p=dict(row)
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
        capture_query=_capture_query_heading(p["raw_heading"])
        return {
            "certified_link_id":certified_link_id,"source_pdf_id":p["source_pdf_id"],
            "confirmed_note_pdf_page_index":p["start_page"],
            "end_page":p["end_page_hint"] or p["start_page"],
            # The Registry member id is an internal, stable research identity;
            # it is often not the literal PDF heading.  Spatial capture must
            # receive the reviewed source heading, otherwise strict identity
            # can target a valid page with an unmatchable query and later
            # report a misleading header/boundary failure.
            "target_heading":p["raw_heading"],"capture_query_title":capture_query,
            "member_table_id":p["member_table_id"],
            "note_reference":anchor_note_reference or candidate_note_reference,"statement_scope":p["statement_scope"],
            "confidence":json.loads(p["score_snapshot_json"] or "{}").get("certification_score",1),
            "status":"CERTIFIED_NOTE_TARGET",
            "evidence":{"certified_child_table_link":certified_link_id,
                        "anchor_note_reference":anchor_note_reference},
        }


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
                blocks=page.get_text("blocks")
                scope=_scope(text); unit=_unit(text)
                pending_ordinal=None
                for block in blocks:
                    x0,y0,x1,y1,raw,*_=block
                    for line in str(raw).splitlines():
                        label=line.strip()
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
        """Add a human-located heading, while retaining the normal evidence pipeline."""
        idx=self.index.build(pdf_path)
        matches=[
            h for h in self.index.headings(idx["index_id"])
            if int(h["start_page"])==int(page)
            and (_norm(title)==h["normalized_heading"] or _norm(title) in h["normalized_heading"])
        ]
        if not matches:raise ValueError("MANUAL_HEADING_NOT_FOUND_IN_FINANCIAL_NOTE_INDEX")
        heading=matches[0];heading["source_pdf_id"]=str(pdf_path)
        run_id="CDRUN_"+uuid.uuid4().hex
        candidate=self._thin(
            run_id,child,heading,"MANUAL","T2C_CERTIFIED_ALIAS",0,
            idx["source_pdf_sha256"],["HUMAN_MANUAL_ADD"],
        )
        run={
            "discovery_run_id":run_id,"source_pdf_id":str(pdf_path),
            "source_pdf_sha256":idx["source_pdf_sha256"],"anchor_id":child["anchor_id"],
            "anchor_child_id":child["anchor_child_id"],"requested_scope":requested_scope,
            "tiers_executed":["MANUAL"],"tiers_skipped":["TIER1","TIER2","TIER3"],
            "early_stop_reason":"HUMAN_MANUAL_ADD",
            "candidate_count_by_tier":{"MANUAL":1},"runtime_by_tier":{"MANUAL":0},
            "metrics":{"index_cache_hit":idx["cache_hit"],"full_capture_count":0,
                       "all_pdf_table_scan":False,"all_pdf_amount_search":False},
            "status":"CANDIDATES_READY","created_at":now_iso(),
        }
        self.repo.save_run(run,[candidate])
        enriched=self.enrich_top_k(pdf_path,child,[candidate],member_contract)
        return self.link_candidates(anchor,child,enriched,member_contract)

    def discover(self,pdf_path:Path,anchor:dict[str,Any],child:dict[str,Any],
                 member_contract:dict[str,Any],requested_scope:str)->dict[str,Any]:
        if requested_scope not in {"CONSOLIDATED","PARENT_COMPANY"}:raise ValueError("SCOPE_LANE_REQUIRED")
        # v6.10: skip non-current-period members before any discovery work.
        period_status = str(child.get("member_period_status") or "")
        if period_status and period_status != "ACTIVE_CURRENT_PERIOD":
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
        if source_target_page and reference_meta["note_item_ordinal"]:
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
            }
            candidate["title_match_class"]="EXACT_SOURCE_MEMBER_TITLE"
            candidates=[candidate]
        elif reference_meta["note_item_ordinal"]:
            note_matches=[]
            for heading in headings:
                heading_meta=_note_reference_key(
                    heading.get("note_reference") or heading.get("note_ordinal")
                )
                if heading_meta["note_item_ordinal"] != reference_meta["note_item_ordinal"]:
                    continue
                title_class,title_score,_=_best_title_match(member_contract,heading.get("raw_heading"))
                note_matches.append((title_score,title_class,heading))
            if not note_matches:
                tier1_failure_reason="NOTE_REFERENCE_PARSED_BUT_INDEX_TARGET_NOT_FOUND"
            else:
                # A same-note continuation can create more than one index row.
                # Preserve only title-compatible headings as formal Tier 1
                # candidates; a reference match with a contradictory title is
                # explained, not silently sent to Tier 3.
                compatible=[item for item in note_matches if item[1] != "SEMANTIC_ONLY"]
                if not compatible:
                    tier1_failure_reason="NOTE_REFERENCE_TITLE_CONFLICT"
                else:
                    compatible.sort(key=lambda item:(-item[0], item[2]["start_page"]))
                    candidates=[]
                    for title_score,title_class,heading in compatible[:self.limits["TIER1"]]:
                        candidate=self._thin(run_id,child,heading,"TIER1","TIER1_EXPLICIT_REFERENCE",1,
                                             idx["source_pdf_sha256"])
                        candidate["note_reference_evidence"]={
                            **reference_meta,
                            "heading_note_reference":heading.get("note_reference") or heading.get("note_ordinal"),
                            "match":"EXPLICIT_REFERENCE_MATCH",
                        }
                        candidate["title_match_class"]=title_class
                        candidates.append(candidate)
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
            exact=[h for h in headings if h["raw_heading"].strip() in aliases]
            normalized=[h for h in headings if h["normalized_heading"] in norm_aliases and h not in exact]
            certified_hits=[h for h in headings if h["normalized_heading"] in {_norm(x) for x in certified}]
            selected=[];method=""
            if len(exact)==1:selected=exact;method="T2A_CANONICAL_EXACT"
            elif normalized:selected=normalized;method="T2B_NORMALIZED_EXACT"
            elif certified_hits:selected=certified_hits;method="T2C_CERTIFIED_ALIAS"
            else:
                tokens=set(_norm(aliases[0])) if aliases else set()
                scored=[]
                for h in headings:
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
                fallback=[h for h in headings if any(x and x in h["normalized_heading"] for x in raw_forms)]
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
                       "note_reference":reference_meta,
                       "discovery_version":DISCOVERY_VERSION},"status":"CANDIDATES_READY",
            "created_at":now_iso(),
        }
        self.repo.save_run(run,candidates)
        return {"run":run,"candidates":candidates,"index":idx}

    @staticmethod
    def _scope_ok(candidate:dict[str,Any],requested_scope:str)->bool:
        hint=candidate.get("statement_scope_hint") or "UNKNOWN"
        return hint in {"UNKNOWN",requested_scope}

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

    def enrich_top_k(self,pdf_path:Path,child:dict[str,Any],
                     candidates:list[dict[str,Any]],
                     member_contract:dict[str,Any]|None=None)->list[dict[str,Any]]:
        member_contract=dict(member_contract or {})
        ranked=sorted(candidates,key=lambda x:(x["retrieval_priority"],-x["base_score"],x["start_page"]))
        output=[]
        with fitz.open(str(pdf_path)) as doc:
            for candidate in ranked[:self.limits["ENRICHMENT_TOP_K"]]:
                cached=self.repo.cached_enriched(candidate["candidate_id"])
                if cached:
                    output.append(cached)
                    continue
                started=time.perf_counter();page=doc[candidate["start_page"]-1]
                text=page.get_text("text"); numbers=_numbers(text)
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
                    **candidate,"container_page_range":[candidate["start_page"],candidate.get("end_page_hint") or candidate["start_page"]],
                    "possible_subtable_roles":[role],"title_match_class":title_class,
                    "note_reference_match":note_match,
                    "scope_evidence":{"requested":requested,"page_hint":hint},
                    "period_evidence":{"years":sorted(set(re.findall(r"20\\d{2}",text)))},
                    "unit_evidence":{"unit":_unit(text),"inherited":not bool(_unit(text))},
                    "lightweight_table_presence":has_table,
                    "lightweight_header_signature":[x for x in text.splitlines()[:12] if x.strip()],
                    "lightweight_row_signature":[x for x in text.splitlines()[12:30] if x.strip()],
                    "amount_summary":{"number_count":len(numbers),"sample":numbers[:20]},
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
                    "negative_evidence":[k for k,v in hard.items() if not v] + (
                        ["MAIN_STATEMENT_MEMBER_AMOUNT_MISSING"] if not amount_present and not allow_no_direct else []
                    ),
                    "enrichment_runtime_ms":(time.perf_counter()-started)*1000,
                    "enrichment_version":ENRICHMENT_VERSION,
                }
                self.repo.save_enriched(row);output.append(row)
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
        rows=[]
        ordered=sorted(
            enriched,
            key=lambda x:(
                _subtable_role(x.get("raw_heading"),member_contract) != "PRIMARY_AMOUNT_DETAIL",
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
            role=_subtable_role(x.get("raw_heading"),member_contract)
            positive_evidence=list(x.get("positive_evidence") or [])
            if note_match and "NOTE_REFERENCE_MATCHES_ANCHOR" not in positive_evidence:
                positive_evidence.append("NOTE_REFERENCE_MATCHES_ANCHOR")
            negatives=list(x.get("negative_evidence") or [])
            blocking=[k for k,v in hard_gates.items() if not v]
            if "MAIN_STATEMENT_MEMBER_AMOUNT_MISSING" in negatives:
                blocking.append("MAIN_STATEMENT_MEMBER_AMOUNT_MISSING")
            rows.append({
                "link_candidate_id":"LKC_"+uuid.uuid4().hex,"anchor_id":anchor["occurrence_id"],
                "anchor_child_id":child["anchor_child_id"],"candidate_id":x["candidate_id"],
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
                "reconciliation_status":relation.get("status"),"confidence":x["certification_score"],
                "anchor_note_reference":anchor_note_reference,
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
                and primary[0]["certification_score"]>=0.60
                and all(primary[0]["hard_gate_results"].values())
            )
            primary[0]["is_preselected"]=bool(sole_viable or (
                primary[0]["certification_score"]>=0.85 and margin>=0.10
                and all(primary[0]["hard_gate_results"].values())
            ))
            if sole_viable:
                primary[0]["preselection_reason"]="SOLE_VIABLE_PRIMARY_CANDIDATE"
        self.repo.save_link_candidates(rows)
        return rows

    def assign_global(self,anchor_id:str,scope:str,links_by_child:dict[str,list[dict[str,Any]]])->dict[str,Any]:
        started=time.perf_counter();used=set();decisions=[];conflicts=[];rejected=[]
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
            status="RECOMMENDED" if chosen and chosen.get("is_preselected") else "CHILD_TABLE_SELECTION_REQUIRED"
            decisions.append({"anchor_child_id":child_id,"link_candidate_id":chosen["link_candidate_id"] if chosen else None,
                              "status":status})
            if status=="CHILD_TABLE_SELECTION_REQUIRED":
                child=(links[0].get("candidate") or {}) if links else {}
                self.repo.enqueue_child_review(
                    anchor_id=anchor_id,anchor_child_id=child_id,
                    logical_asset_id=str(child.get("logical_asset_id") or ""),
                    source_pdf_id=str(child.get("source_pdf_id") or ""),
                    statement_scope=scope,
                    candidate_ids=[x["candidate_id"] for x in links],
                    reason="NO_UNIQUE_HIGH_CONFIDENCE_CHILD_TABLE",
                    evidence={"scores":[x["certification_score"] for x in links],
                              "conflicts":conflicts})
        return self.repo.save_assignment({
            "assignment_id":"ASSIGN_"+uuid.uuid4().hex,"anchor_id":anchor_id,
            "statement_scope":scope,"decisions":decisions,"conflicts":conflicts,
            "rejected_links":rejected,"evidence":{"algorithm":"EXPLAINABLE_GREEDY_V1"},
            "assignment_runtime_ms":(time.perf_counter()-started)*1000,
        })

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
                "member_table_role":"NOTE_DETAIL",
                "note_number":target.get("note_reference") or None,
                "note_reference":target.get("note_reference") or None,
                "table_query":target.get("capture_query_title") or target.get("target_heading"),
            },
        )
