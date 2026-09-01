"""Auditable ranking and conservative preselection for statement anchors."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass,asdict
import hashlib
import json
import re
from typing import Any,Iterable

from statement_anchored_family import normalize_text


RANKING_VERSION="ANCHOR_SCORE_V2"
DEFAULT_POLICY={"min_score":0.85,"margin":0.10,"max_per_scope":1}
FORMAL_STATEMENTS=("资产负债表","利润表","现金流量表","所有者权益变动表","财务状况表")
NEGATIVE_TITLES=("摘要","目录","管理层讨论","经营情况讨论","主要会计数据")


def _children(candidate:dict[str,Any])->list[dict[str,Any]]:
    return list(candidate.get("child_rows") or [])


def _periods(candidate:dict[str,Any])->list[str]:
    evidence=candidate.get("evidence") or {}
    values=evidence.get("period_headers") or evidence.get("periods") or candidate.get("period_headers") or []
    if isinstance(values,str): values=[values]
    if not values:
        for row in _children(candidate):
            for key in ("data_year","report_year","year"):
                if row.get(key): values.append(str(row[key]))
    return sorted(set(map(str,values)))


def _bbox_signature(candidate:dict[str,Any])->str:
    evidence=candidate.get("evidence") or {}
    bbox=evidence.get("target_row_bbox") or candidate.get("target_row_bbox") or candidate.get("bbox") or {}
    if isinstance(bbox,dict):
        values=[bbox.get(x) for x in ("x0","y0","x1","y1")]
    else:
        values=list(bbox) if isinstance(bbox,(list,tuple)) else []
    return ",".join("" if x is None else str(round(float(x),1)) for x in values)


def _note_signature(candidate:dict[str,Any])->str:
    refs=[]
    for row in _children(candidate):
        ref=row.get("note_reference_normalized") or row.get("note_reference")
        if ref: refs.append(str(ref))
    return "|".join(sorted(set(refs)))


def candidate_identity(candidate:dict[str,Any])->tuple:
    """Identity is deliberately source-aware and geometry-aware."""
    source=(candidate.get("source_pdf_sha256") or
            (candidate.get("evidence") or {}).get("source_pdf_sha256") or
            candidate.get("pdf_id"))
    return (
        str(source or ""),str(candidate.get("scope") or "UNKNOWN"),
        int(candidate.get("statement_pdf_page_index") or candidate.get("statement_page") or 0),
        normalize_text(candidate.get("parent_text") or candidate.get("display_name")),
        _bbox_signature(candidate),tuple(_periods(candidate)),_note_signature(candidate),
    )


def deduplicate_anchor_candidates(candidates:Iterable[dict[str,Any]])->list[dict[str,Any]]:
    groups:dict[tuple,list[dict[str,Any]]]=defaultdict(list)
    for row in candidates: groups[candidate_identity(row)].append(dict(row))
    out=[]
    for identity,members in groups.items():
        representative=max(members,key=lambda x:len(_children(x)))
        strategies=sorted(set(filter(None,(
            x.get("strategy_id") or (x.get("evidence") or {}).get("strategy_id")
            for x in members
        ))))
        original_ids=[str(x.get("occurrence_id") or x.get("candidate_id") or "") for x in members]
        payload={**representative,
                 "contributing_strategy_ids":strategies,
                 "original_candidate_ids":original_ids,
                 "duplicate_count":len(members),
                 "dedupe_evidence":[x.get("evidence") or {} for x in members]}
        if not payload.get("occurrence_id"):
            digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False,default=str).encode()).hexdigest()[:20]
            payload["occurrence_id"]="OCC_DEDUP_"+digest
        out.append(payload)
    return out


def score_anchor_candidate(candidate:dict[str,Any],context:dict[str,Any]|None=None)->dict[str,Any]:
    context=dict(context or {})
    evidence=dict(candidate.get("evidence") or {})
    children=_children(candidate); title=str(candidate.get("source_table_title") or "")
    parent=normalize_text(candidate.get("parent_text")); target=normalize_text(candidate.get("display_name"))
    note_rows=sum(bool(x.get("note_reference_normalized") or x.get("note_reference")) for x in children)
    valid_notes=sum(bool(re.match(r"^附注(?:[一二三四五六七八九十百\d]+-)?[一二三四五六七八九十百\d]+$",str(
        x.get("note_reference_normalized") or x.get("note_reference") or ""))) for x in children)
    value_rows=sum(any(x.get(k) is not None for k in ("value","current_value","prior_value","values")) for x in children)
    periods=_periods(candidate)
    scope=str(candidate.get("scope") or "UNKNOWN")
    expected_scope=str(context.get("scope_preference") or context.get("statement_scope") or "")
    formal=any(token in title for token in FORMAL_STATEMENTS) or bool(evidence.get("formal_statement_region"))
    negative_title=any(token in title for token in NEGATIVE_TITLES) or bool(evidence.get("summary_or_toc"))
    components={
        "exact_parent_match":0.14 if parent and parent==target else 0.0,
        "normalized_parent_match":0.08 if parent and target and (target in parent or parent in target) else 0.0,
        "formal_statement_region":0.13 if formal else 0.0,
        "statement_type_match":0.06 if str(candidate.get("statement_type") or "").upper() not in {"","UNKNOWN","NOTE_SECTION"} else 0.0,
        "scope_match":0.05 if expected_scope and scope==expected_scope else (0.03 if scope!="UNKNOWN" else 0.0),
        "continuous_children":0.10*min(len(children)/4,1.0),
        "inline_note_references":0.12*(note_rows/len(children) if children else 0.0),
        "valid_note_format":0.05*(valid_notes/len(children) if children else 0.0),
        "amount_completeness":0.09*(value_rows/len(children) if children else 0.0),
        "period_completeness":0.07 if len(periods)>=2 or evidence.get("period_header_complete") else 0.0,
        "unit_context":0.04 if evidence.get("unit") or candidate.get("unit") else 0.0,
        "scope_context":0.03 if scope!="UNKNOWN" else 0.0,
        "column_alignment":0.04 if evidence.get("amount_columns_aligned") else 0.0,
        "historical_support":0.03 if evidence.get("historical_certified_support") else 0.0,
        "definition_structure_match":0.02 if evidence.get("research_definition_match") else 0.0,
        "summary_or_toc_penalty":-0.28 if negative_title else 0.0,
        "note_section_penalty":-0.22 if str(candidate.get("statement_type") or "").upper()=="NOTE_SECTION" else 0.0,
        "keyword_only_penalty":-0.18 if not children else 0.0,
        "scope_conflict_penalty":-0.18 if expected_scope and scope not in {expected_scope,"UNKNOWN"} else 0.0,
        "image_or_ocr_penalty":-0.12 if evidence.get("ocr_only") and not evidence.get("bbox_verified") else 0.0,
    }
    hard_gates={
        "source_pdf_identity":bool(candidate.get("pdf_id") or candidate.get("source_pdf_sha256") or evidence.get("source_pdf_sha256")),
        "scope_compatible":not expected_scope or scope in {expected_scope,"UNKNOWN"},
        "target_parent_exists":bool(parent),
        "amount_columns_present":bool(value_rows or evidence.get("amount_columns_present")),
        "period_recognized":bool(periods or evidence.get("period_header_complete")),
        "formal_statement_not_note":str(candidate.get("statement_type") or "").upper()!="NOTE_SECTION" and not negative_title,
        "bbox_intersects_statement":bool(evidence.get("bbox_verified",True)),
        "not_toc_or_summary":not negative_title,
        "ocr_evidence_sufficient":not evidence.get("ocr_only") or bool(evidence.get("bbox_verified")),
    }
    total=max(0.0,min(1.0,round(sum(components.values()),4)))
    passed=all(hard_gates.values())
    positive=[k for k,v in components.items() if v>0]
    negative=[k for k,v in components.items() if v<0]
    return {
        **candidate,"total_score":total,"anchor_score":total,
        "score_components":components,"positive_evidence":positive,
        "negative_evidence":negative,"hard_gate_results":hard_gates,
        "hard_gates_passed":passed,
        "qualification_tier":"QUALIFIED" if passed and total>=0.70 else "LOW_CONFIDENCE",
        "ranking_version":RANKING_VERSION,
    }


def rank_and_preselect(candidates:Iterable[dict[str,Any]],context:dict[str,Any]|None=None,
                       policy:dict[str,Any]|None=None)->dict[str,Any]:
    context=dict(context or {}); cfg={**DEFAULT_POLICY,**dict(policy or {})}
    scored=[score_anchor_candidate(x,context) for x in deduplicate_anchor_candidates(candidates)]
    scope_order={str(x):i for i,x in enumerate(context.get("scope_order") or ["CONSOLIDATED","PARENT_COMPANY","COMPANY","UNKNOWN"])}
    scored.sort(key=lambda x:(
        scope_order.get(str(x.get("scope") or "UNKNOWN"),99),
        0 if x["qualification_tier"]=="QUALIFIED" else 1,
        -float(x["total_score"]),
        int(x.get("statement_pdf_page_index") or 10**9),
    ))
    by_scope=defaultdict(list)
    for row in scored:
        source=str(row.get("pdf_id") or row.get("source_pdf_sha256") or "")
        by_scope[(source,str(row.get("scope") or "UNKNOWN"))].append(row)
    selected=[]; decisions={}
    allowed=set(context.get("required_scopes") or [scope for _,scope in by_scope])
    for (source,scope),rows in by_scope.items():
        qualified=[x for x in rows if x["hard_gates_passed"] and x["qualification_tier"]=="QUALIFIED"]
        top=qualified[0] if qualified else None
        second=qualified[1] if len(qualified)>1 else None
        margin=(float(top["total_score"])-float(second["total_score"])) if top and second else 1.0
        # A uniquely perfect, gate-passing candidate is decisive evidence.
        # Do not force a human to arbitrate merely because a second, weaker
        # candidate is also strong (for example 1.00 versus 0.97).  Exact ties
        # at the maximum remain deliberately reviewable.
        unique_perfect=bool(
            top and top["hard_gates_passed"]
            # Scores are rendered to two decimals in the review UI, so a
            # 0.995 candidate is a visible 1.00 and receives the same rule.
            and float(top["total_score"]) >= 0.995
            and (second is None or float(second["total_score"]) < 0.995)
        )
        choose=bool(scope in allowed and top and (
            unique_perfect or (
                top["total_score"]>=float(cfg["min_score"])
                and margin>=float(cfg["margin"])
            )
        ))
        if choose and int(cfg["max_per_scope"])>0:
            selected.append(top["occurrence_id"])
            top["selection_state"]="PRESELECTED"
            top["recommendation_state"]="RECOMMENDED"
            decisions[f"{source}::{scope}"]={
                "status":"SINGLE_PRESELECTED_EXACT_MAXIMUM" if unique_perfect else "SINGLE_PRESELECTED",
                "candidate_id":top["occurrence_id"],"margin":margin,
            }
        else:
            decisions[f"{source}::{scope}"]={"status":"ANCHOR_SELECTION_REQUIRED","candidate_id":None,"margin":margin,
                                            "reason":"LOW_SCORE_OR_AMBIGUOUS"}
        for row in rows:
            row.setdefault("selection_state","DISCOVERED")
            row.setdefault("recommendation_state","QUALIFIED" if row["hard_gates_passed"] else "HARD_GATE_FAILED")
    return {"candidates":scored,"preselected_ids":selected,"scope_decisions":decisions,
            "policy":cfg,"ranking_version":RANKING_VERSION}


def candidate_label(candidate:dict[str,Any])->str:
    recommended="推荐｜" if candidate.get("recommendation_state")=="RECOMMENDED" else ""
    children=_children(candidate); notes=sum(bool(x.get("note_reference_normalized") or x.get("note_reference")) for x in children)
    periods="/".join(_periods(candidate)) or "期间不完整"
    gates="门禁通过" if candidate.get("hard_gates_passed") else "门禁失败"
    return (
        f"{recommended}{float(candidate.get('total_score') or 0):.2f}｜PDF {candidate.get('statement_pdf_page_index') or '?'}｜"
        f"{candidate.get('source_table_title') or '未知主表'}｜{candidate.get('scope') or 'UNKNOWN'}｜"
        f"{candidate.get('parent_text') or candidate.get('display_name')}｜{len(children)}个子项/{notes}个附注｜"
        f"{periods}｜{gates}"
    )
