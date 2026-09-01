"""Generic Statement-Guided Discovery for v6.5.

Presets only supply optional vocabulary. The extractor retains all occurrences;
anchor arbitration is deliberately a later, reviewable step.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from statement_note_navigation import (
    TextIndexRecord,
    build_text_index,
    fast_index_to_text_index,
    locate_primary_statements,
    locate_note,
)
from statement_anchored_family import compose_note_reference, normalize_text
from statement_anchor_evidence_v2 import scope_from_statement_text
from conditional_statement_ocr import (
    conditional_ocr_primary_statements,
    directory_statement_hints,
)

# Migration/import vocabulary only. Production runtime receives immutable
# Registry-derived context through ``discovery_context``.
LEGACY_PRESET_IMPORT_SOURCE = {
    "金融投资": {
        "preferred_statement_type": "BALANCE_SHEET",
        "core_candidates": [
            "交易性金融资产", "交易性金融資產",
            "债权投资", "債權投資",
            "其他债权投资", "其他債權投資",
            "其他权益工具投资", "其他權益工具投資",
            "以公允价值计量且其变动计入当期损益的金融资产", "以公允價值計量且其變動計入當期損益的金融資產",
            "以摊余成本计量的金融资产", "以攤餘成本計量的金融資產",
            "以公允价值计量且其变动计入其他综合收益的金融资产", "以公允價值計量且其變動計入其他全面收益的金融資產",
            "以公允價值計量且其變動計入其他綜合收益的金融資產",
            "按攤銷成本", "按摊销成本",
            "按公平值計入其他全面收入", "按公平值计入其他全面收入",
            "按公平值計入損益", "按公平值计入损益",
            "按公平值計入其他綜合收益", "按公平值计入其他综合收益",
            "金融投资", "金融投資",
        ],
        "historical_variants": ["以公允价值计量且其变动计入当期损益的金融资产", "可供出售金融资产", "持有至到期投资"],
        "expansion_candidates": ["定期存款", "买入返售金融资产", "长期股权投资", "存出资本保证金", "投資物業", "投资物业"],
        "definition_version": "FINANCIAL_INVESTMENT_V1",
    }
}


def normalize_company(value: str) -> str:
    value = re.sub(r"^[0-9a-fA-F]{12,64}_", "", value or "")
    return re.sub(r"\s+", "", value).replace("年报", "").replace("年度报告", "")


def _tokens(display_name: str, prior: dict[str, Any]) -> list[str]:
    normalized = display_name
    for suffix in ("研究", "明细", "表族", "项目", "分析"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return list(dict.fromkeys([x for x in [display_name, normalized, *prior.get("core_candidates", []), *prior.get("historical_variants", [])] if x]))


def _extract_tail_reference(line: str, label: str, note_header: str, next_line: str = "") -> dict[str, str]:
    tail = line.split(label, 1)[-1]
    explicit = re.search(r"((?:附注|注)\s*[一二三四五六七八九十百\d]+\s*[-、.]?\s*[一二三四五六七八九十百\d]*)", tail)
    if explicit:
        return compose_note_reference("", explicit.group(1))
    # In a recognised note column, a standalone trailing cell is a row item.
    # Do not accept a prefix of a monetary token (for example ``380,239``)
    # as a note ordinal.  A table-cell ordinal is a complete 1--3 digit token
    # and must not be immediately followed by a digit, decimal point, or
    # thousands separator.
    item = re.search(r"(?:^|\s)([0-9]{1,3})(?![0-9,，.．])(?=\s|$)", tail)
    if item:
        return compose_note_reference(note_header, item.group(1))
    # PDF text extraction commonly emits a statement label and its “附注” cell
    # as two adjacent lines.  Treat the next line as a note cell only when it
    # is a standalone ordinal; values such as 380,239 are deliberately rejected.
    adjacent = str(next_line or "").strip()
    if re.fullmatch(r"[0-9]{1,3}", adjacent):
        return compose_note_reference(note_header, adjacent)
    return compose_note_reference(note_header, "")


def _standalone_note_ordinal(value: str) -> str:
    """Return a conservative statement-note cell ordinal, never an amount.

    OCR and native PDF extraction both flatten a table row into text.  This
    helper recognises only an isolated 1--3 digit cell; it deliberately
    rejects commas, decimal punctuation, and longer numeric strings.
    """
    match = re.search(r"(?:^|\s)([0-9]{1,3})(?![0-9,，.．])(?=\s|$)", str(value or ""))
    return match.group(1) if match else ""


def _statement_amount_observations(raw_line: str, label: str) -> list[str]:
    """Extract only displayed statement amounts following a matched member.

    The note ordinal is deliberately excluded: a 1--3 digit standalone token
    is a reference cell, whereas an amount must carry a thousands separator,
    four or more digits, or an explicit non-applicable marker.  The function
    retains raw tokens and never derives values from the downstream note.
    """
    tail = _tail_after_label(str(raw_line or ""), label) if label else str(raw_line or "")
    observations: list[str] = []
    for token in re.findall(r"(?<!\d)(?:\(?-?\d[\d,]*(?:\.\d+)?\)?|不适用|-)(?!\d)", tail):
        cleaned = token.strip()
        numeric = cleaned.strip("()").lstrip("-").replace(",", "")
        if cleaned in {"-", "不适用"} or "," in cleaned or len(numeric.split(".", 1)[0]) >= 4:
            observations.append(cleaned)
    return observations


def _nearby_statement_amount_observations(lines: list[str], line_index: int, label: str) -> list[str]:
    """Recover vertically emitted statement cells without crossing into next row.

    Native PDF extraction sometimes emits ``项目名`` / ``附注号`` / three
    year values on separate lines.  We only consume immediately following
    numeric-only cells and stop before the next Chinese-text label.
    """
    values = _statement_amount_observations(lines[line_index], label)
    if values:
        return values
    for offset in range(1, 7):
        if line_index + offset >= len(lines):
            break
        cell = str(lines[line_index + offset] or "").strip()
        if not cell:
            continue
        if re.search(r"[\u4e00-\u9fff]", cell):
            break
        values.extend(_statement_amount_observations(" " + cell, ""))
    return values


def _page_note_header(lines: list[str]) -> tuple[str, int | None]:
    """Find the statement note-column header and retain its source line."""
    for index, line in enumerate(lines):
        match = re.search(r"(?:附注|注)\s*[一二三四五六七八九十百\d]+", str(line or ""))
        if match:
            return match.group(0), index
        if re.fullmatch(r"\s*(?:附注|注)\s*", str(line or "")):
            return match.group(0) if match else "附注", index
    return "", None


def _logical_statement_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Produce bounded OCR-tolerant label continuations with source indexes.

    A long Chinese statement label may wrap across two OCR lines.  Join only
    immediately adjacent, non-numeric lines; this is evidence for locating a
    label, not a value-extraction transformation.
    """
    logical: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        cleaned = " ".join(str(line or "").split())
        if not cleaned:
            continue
        logical.append((index, cleaned))
        if index + 1 >= len(lines):
            continue
        following = " ".join(str(lines[index + 1] or "").split())
        if not following or re.fullmatch(r"[0-9]{1,3}", following):
            continue
        if re.search(r"\d{1,3}(?:[,.，．]\d|\s*$)", cleaned):
            continue
        logical.append((index, f"{cleaned} {following}"))
    return logical


def _tail_after_label(raw_line: str, label: str) -> str:
    """Return the raw suffix after a label while tolerating OCR whitespace."""
    if label in raw_line:
        return raw_line.split(label, 1)[-1]
    pattern = r"\s*".join(re.escape(char) for char in label)
    match = re.search(pattern + r"(?P<tail>.*)$", raw_line)
    return match.group("tail") if match else ""


def _is_target_line(line: str, display_name: str) -> bool:
    compact = normalize_text(line)
    target = normalize_text(display_name)
    if not target:
        return False
    variants = [target]
    if target == "金融投资":
        variants.append("金融投資")
    elif target == "金融投資":
        variants.append("金融投资")

    matched_target = next((v for v in variants if v in compact), "")
    if not matched_target:
        return False
    # Permit a numbered heading ("35. 投资收益") and a statement row followed
    # by amounts, but reject narrative mentions such as "...预期投资收益率...".
    stripped = re.sub(r"^[（(]?\d{1,3}[.)、）]?", "", compact)
    # A zero-value section parent is commonly printed as ``金融投资：``.
    # Preserve the semantic parent even though it has no same-line amount.
    terminal = stripped[len(matched_target):].strip("：:;-—－") if stripped.startswith(matched_target) else ""
    return stripped.startswith(matched_target) and (
        not terminal
        or bool(re.search(r"[-(（]?\d[\d,，.]*", stripped[len(matched_target):]))
    )


def _infer_statement_scope(text: str, statement_type: str, page_number: int = 0, statement_pages: list[int] | None = None) -> str:
    # ``page_number``/``statement_pages`` remain in the compatibility
    # signature, but page order is intentionally not evidence of scope.
    return scope_from_statement_text(text)[0]


def _qualified_target_pages(index, statements: dict[str, list[int]], statement_types: list[str],
                            display_name: str, preferred_scope: str | None = None,
                            require_note_reference: bool = False,
                            core_candidates: list[str] | None = None) -> tuple[set[int], dict[int, str]]:
    formal_pages = {page for kind in statement_types for page in statements.get(kind, [])}
    core = [normalize_text(item) for item in (core_candidates or []) if item]

    def target_quality(rec) -> tuple[str, dict[str, Any]]:
        lines = rec.text.splitlines()
        note_header, header_line_index = _page_note_header(lines)
        ocr_header_recovered = False
        # Restrained OCR fallback: only normalise a numeral-shaped glyph in
        # the *note-column header* after the same statement region contains a
        # multi-member financial family with standalone row ordinals.  This is
        # deliberately not a global text replacement (e.g. “到” elsewhere in
        # the report remains untouched).
        if not note_header and require_note_reference and core:
            for candidate_index, candidate_line in enumerate(lines):
                if not re.search(r"附注\s*到", str(candidate_line or "")):
                    continue
                recovered_hits = 0
                for logical_index, logical_line in _logical_statement_lines(lines):
                    compact = normalize_text(logical_line)
                    matched_member=next((member for member in core if member and compact.startswith(member)), "")
                    if not matched_member:
                        continue
                    following = lines[logical_index + 1].strip() if logical_index + 1 < len(lines) else ""
                    ordinal=_standalone_note_ordinal(_tail_after_label(logical_line, matched_member)) or (
                        following if re.fullmatch(r"\d{1,3}", following) else ""
                    )
                    if ordinal:
                        recovered_hits += 1
                if recovered_hits >= 2:
                    note_header, header_line_index = "附注六", candidate_index
                    ocr_header_recovered = True
                    break
        # Retain an actual source-parent line even when the group heading has
        # no note cell of its own.  Financial-statement group rows commonly
        # read ``金融投资：`` and route the references through their children.
        # The distinction matters for the family resolver: an OCR scan that
        # really saw the parent is evidence for EXPLICIT_PARENT, whereas a
        # scan that only saw child labels must never silently claim the same.
        visible_parent: dict[str, Any] | None = None
        for line_index, line in enumerate(lines):
            if not _is_target_line(line, display_name):
                continue
            visible_parent = {
                "parent_line_index": line_index,
                "parent_raw_line": line,
                "parent_recovery_status": "SOURCE_PARENT_RECOVERED",
            }
            if not require_note_reference:
                return "EXACT_PARENT", {
                    **visible_parent,
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                }
            compact_page = normalize_text(rec.text)
            tail = line.split(display_name, 1)[-1]
            if not note_header and _standalone_note_ordinal(tail):
                note_header = "附注"
            if not note_header:
                continue

            # Verify that note references actually exist on child rows or parent row
            child_note_hits: list[dict[str, Any]] = []
            if core:
                for l_idx, l_str in _logical_statement_lines(lines):
                    compact_l = normalize_text(l_str)
                    matched_m = next((m for m in core if m and compact_l.startswith(m)), "")
                    if matched_m:
                        t_str = _tail_after_label(l_str, matched_m)
                        f_str = lines[l_idx + 1].strip() if l_idx + 1 < len(lines) else ""
                        ord_str = _standalone_note_ordinal(t_str) or (f_str if re.fullmatch(r"\d{1,3}", f_str) else "")
                        if ord_str:
                            child_note_hits.append({
                                "member_table": matched_m,
                                "line_index": l_idx,
                                "raw_line": l_str,
                                "note_ordinal": ord_str,
                                "note_reference": compose_note_reference(
                                    note_header, ord_str
                                ).get("note_reference_normalized", ""),
                            })

            if len(child_note_hits) >= 2:
                return "EXPLICIT_PARENT_WITH_CHILD_NOTE_CLUSTER", {
                    **visible_parent,
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                    "core_member_hits": child_note_hits,
                    "core_member_hit_count": len(child_note_hits),
                }
            if _standalone_note_ordinal(tail) or child_note_hits:
                return "EXACT_PARENT_WITH_NOTE", {
                    **visible_parent,
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                }
            if line_index + 1 < len(lines) and re.fullmatch(r"\s*\d{1,3}\s*", lines[line_index + 1]):
                return "EXACT_PARENT_WITH_NOTE", {
                    **visible_parent,
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                }
        # Some stamped/scanned statements lose a zero-value section parent
        # (for example “金融投资：”) while retaining several child rows and
        # their inline note ordinals.  A multi-child cluster is sufficient to
        # propose an *inferred* parent, never a financial amount or a silent
        # auto-certification.
        if require_note_reference and note_header and core:
            hits: dict[str, dict[str, Any]] = {}
            for line_index, line in _logical_statement_lines(lines):
                compact = normalize_text(line)
                for candidate in core:
                    if candidate and (compact.startswith(candidate) or candidate in compact or (len(candidate) >= 5 and candidate[:2] in compact and candidate[-3:] in compact)):
                        tail = _tail_after_label(line, candidate)
                        # Text extraction often emits a statement label and
                        # the note-column ordinal as two adjacent lines.  The
                        # ordinal is evidence only when it is a standalone
                        # 1–3 digit token, never a monetary amount.
                        next_line = lines[line_index + 1].strip() if line_index + 1 < len(lines) else ""
                        ordinal = _standalone_note_ordinal(tail) or (
                            next_line if re.fullmatch(r"\d{1,3}", next_line) else ""
                        )
                        if ordinal:
                            hits.setdefault(candidate, {
                                "member_table": candidate,
                                "line_index": line_index,
                                "raw_line": line,
                                "note_ordinal": ordinal,
                                "note_reference": compose_note_reference(note_header, ordinal).get("note_reference_normalized", ""),
                            })
            if len(hits) >= 2:
                if visible_parent:
                    return "EXPLICIT_PARENT_WITH_CHILD_NOTE_CLUSTER", {
                    **visible_parent,
                    "parent_inferred": False,
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                    "core_member_hits": list(hits.values()),
                    "core_member_hit_count": len(hits),
                }
                return "INFERRED_PARENT_FROM_CHILD_CLUSTER", {
                    "parent_inferred": True,
                    # A child cluster can locate a page, but it cannot prove
                    # that a source parent exists.  Downstream family
                    # resolution must keep this review-required rather than
                    # auto-certifying an implicit family.
                    "parent_recovery_status": "REVIEW_REQUIRED_OCR_PARENT_UNREADABLE",
                    "note_header": note_header,
                    "note_header_line_index": header_line_index,
                    "ocr_note_header_normalized": ocr_header_recovered,
                    "core_member_hits": list(hits.values()),
                    "core_member_hit_count": len(hits),
                }
        return "", {}

    quality: dict[int, str] = {}
    quality_evidence: dict[int, dict[str, Any]] = {}
    for rec in index:
        if rec.page_number not in formal_pages:
            continue
        if not (
            not preferred_scope
            or preferred_scope in {"BOTH", "UNKNOWN"}
            or any(
                _infer_statement_scope(rec.text, kind) == preferred_scope
                for kind in statement_types if rec.page_number in statements.get(kind, [])
            )
        ):
            continue
        reason, evidence = target_quality(rec)
        if reason:
            quality[rec.page_number] = reason
            quality_evidence[rec.page_number] = evidence
    # Keep the existing public two-value contract.  The audit-facing evidence
    # is attached by the caller from this function attribute for compatibility
    # with existing discovery service integrations.
    _qualified_target_pages.last_evidence = quality_evidence
    return set(quality), quality


def _locate_without_reference(index, item: str, section_context: str, *,
                              exclude_pages: set[int] | None = None):
    """Fallback locator: heading/context first, then semantic/full-text proxy.

    It returns REVIEW_REQUIRED-level confidence instead of inventing a target.
    """
    candidates = []
    excluded = exclude_pages or set()
    target = normalize_text(item)
    for rec in index:
        if rec.page_number in excluded:
            continue
        text = normalize_text(rec.text)
        if target in text:
            lines = [line.strip() for line in rec.text.splitlines() if line.strip()]
            heading_match = any(
                re.match(r"^\s*(?:[（(]?\d{1,3}[.)、）]\s*)?" + re.escape(item) + r"\s*$", line)
                for line in lines
            )
            score = .88 if heading_match else (.58 if target == text else .48)
            if section_context and normalize_text(section_context) in text:
                score += .05
            candidates.append((rec.page_number, "HEADING_OR_CONTEXT_MATCH", round(score, 2)))
    if not candidates:
        return None, "FULL_TEXT_FALLBACK_UNRESOLVED", .0, []
    candidates.sort(key=lambda x: x[2], reverse=True)
    page, method, score = candidates[0]
    return page, method, score, [x[0] for x in candidates[:5]]


def _infer_note_section_from_target_page(index, page_number: int | None,
                                         statement_scope: str) -> str:
    if not page_number:
        return ""
    candidates = [
        rec for rec in index
        if max(1, page_number - 1) <= rec.page_number <= page_number
    ]
    wanted = "公司" if statement_scope == "PARENT_COMPANY" else "合并"
    for rec in reversed(candidates):
        compact = normalize_text(rec.text)
        match = re.search(
            r"([一二三四五六七八九十百]+)、" + wanted + r"财务报表主要项目注释",
            compact,
        )
        if match:
            return match.group(1)
    return ""


def discover(pdf_path, cache_root, *, display_name: str, company: str = "", report_year: str = "",
             filing_type: str = "ANNUAL_REPORT", preset_name: str | None = None,
             discovery_context: dict[str, Any] | None = None, text_provider=None,
             ocr_provider=None, ocr_config: dict[str, Any] | None = None,
             prebuilt_index: list[TextIndexRecord] | None = None,
             resolved_index_sink: list[TextIndexRecord] | None = None,
             audit_sink: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return immutable raw evidence for any display name, never financial guesses."""
    # ``preset_name`` remains import compatibility only; production callers
    # pass a Registry snapshot in discovery_context and never mutate globals.
    prior = dict(discovery_context or {})
    if not prior and preset_name:
        prior = dict(LEGACY_PRESET_IMPORT_SOURCE.get(preset_name, {}))
    reused_prebuilt_index = prebuilt_index is not None
    index = (
        list(prebuilt_index)
        if prebuilt_index is not None
        else build_text_index(pdf_path, cache_root, text_provider=text_provider)
    )
    statements = locate_primary_statements(index)
    preferred = prior.get("preferred_statement_type")
    preferred_scope = prior.get("preferred_scope")
    require_note_reference = bool(prior.get("require_note_reference"))
    wanted_types = [preferred] if preferred else [kind for kind, pages in statements.items() if pages]
    qualified_pages, qualified_page_reasons = _qualified_target_pages(
        index, statements, wanted_types, display_name, preferred_scope,
        require_note_reference, prior.get("core_candidates"),
    )
    qualified_page_evidence = dict(getattr(_qualified_target_pages, "last_evidence", {}))
    text_has_target = bool(qualified_pages)
    native_qualified_pages = set(qualified_pages)
    native_qualified_page_reasons = dict(qualified_page_reasons)
    native_qualified_page_evidence = dict(qualified_page_evidence)
    ocr_audit: dict[str, Any] = {"ocr_triggered": False, "final_status": "FOUND_HIGH_CONFIDENCE_TEXT"}
    page_modes: dict[int, str] = {}
    # OCR is a strictly conditional page-discovery fallback.  Existing text
    # candidates are untouched when the text path already found the target.
    primary_pages = {p for kind in wanted_types for p in statements.get(kind, [])}
    native_pages = [record.text for record in index]
    directory_hint_pages = {
        page
        for kind in wanted_types
        for page in directory_statement_hints(
            native_pages,
            kind,
            preferred_scope,
        )
    }
    has_unparsed_scanned_statement = any(
        len((next((r.text for r in index if r.page_number == p), "") or "").strip()) < 100
        for p in primary_pages | directory_hint_pages
    )
    if not text_has_target or has_unparsed_scanned_statement:
        forced_config = dict(ocr_config or {})
        forced_config.setdefault("preferred_scope", preferred_scope)
        if any(statements.get(kind) for kind in wanted_types):
            forced_config["force_ocr_due_unqualified_target"] = True
        conditional_fast_records: list[Any] = []
        ocr_texts, ocr_audit = conditional_ocr_primary_statements(
            Path(pdf_path), native_pages=native_pages, preferred_statement_type=preferred,
            cache_root=Path(cache_root), config=forced_config, ocr_provider=ocr_provider,
            record_sink=conditional_fast_records,
        )
        if ocr_texts:
            merged = []
            fast_record_by_page = {
                int(getattr(record, "page", getattr(record, "page_number", 0)) or 0): record
                for record in conditional_fast_records
                if getattr(record, "ocr_used", False)
            }
            for record in index:
                ocr_text = ocr_texts.get(str(record.page_number), "")
                directory_hint = (ocr_audit.get("directory_statement_hints") or {}).get(
                    str(record.page_number), {}
                )
                if ocr_text and directory_hint.get("statement_title"):
                    ocr_text = f"{directory_hint['statement_title']}\n{ocr_text}"
                fast_record = fast_record_by_page.get(record.page_number)
                if ocr_text and fast_record is not None:
                    merged_record = fast_index_to_text_index([fast_record])[0]
                    object.__setattr__(
                        merged_record,
                        "text",
                        (record.text + "\n" + ocr_text).strip(),
                    )
                    object.__setattr__(
                        merged_record,
                        "heading",
                        record.heading
                        or (ocr_text.splitlines()[0] if ocr_text.splitlines() else ""),
                    )
                    merged.append(merged_record)
                elif ocr_text:
                    merged.append(TextIndexRecord(
                        record.page_number, (record.text + "\n" + ocr_text).strip(),
                        record.heading or (ocr_text.splitlines()[0] if ocr_text.splitlines() else ""),
                        record.section, record.note_numbers,
                    ))
                else:
                    merged.append(record)
                if ocr_text:
                    page_modes[record.page_number] = "OCR_FALLBACK" if not record.text.strip() else "HYBRID_TEXT_OCR"
            index = merged
            statements = locate_primary_statements(index)
            wanted_types = [preferred] if preferred else [kind for kind, pages in statements.items() if pages]
            qualified_pages, qualified_page_reasons = _qualified_target_pages(
                index, statements, wanted_types, display_name, preferred_scope,
                require_note_reference, prior.get("core_candidates"),
            )
            qualified_page_evidence = dict(getattr(_qualified_target_pages, "last_evidence", {}))
        if not qualified_pages and text_has_target and not ocr_audit.get("ocr_triggered"):
            # OCR was not executed, so the conditional policy outcome cannot
            # invalidate native evidence already accepted by the formal gate.
            qualified_pages = native_qualified_pages
            qualified_page_reasons = native_qualified_page_reasons
            qualified_page_evidence = native_qualified_page_evidence
        if not qualified_pages:
            if (
                ocr_audit.get("ocr_errors")
                or ocr_audit.get("final_status")
                == "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
            ):
                ocr_audit["final_status"] = "NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE"
            else:
                ocr_audit["final_status"] = (
                    "OCR_COMPLETED_NO_QUALIFIED_CANDIDATE"
                    if ocr_audit.get("ocr_triggered")
                    else ocr_audit.get("final_status", "NO_QUALIFIED_TARGET")
                )
    else:
        ocr_audit["target_quality_gate"] = "QUALIFIED_TARGET_ON_FORMAL_STATEMENT"
        ocr_audit["qualified_target_pages"] = sorted(qualified_pages)
        ocr_audit["qualified_target_page_reasons"] = qualified_page_reasons
        # A fallback considered for a separate low-text page must not replace
        # an already-qualified native-text result with a policy-only failure.
        if not ocr_audit.get("ocr_triggered"):
            ocr_audit["final_status"] = "FOUND_HIGH_CONFIDENCE_TEXT"
    if audit_sink is not None:
        ocr_audit["native_index_reused"] = reused_prebuilt_index
        audit_sink.update(ocr_audit)
    candidate_types = [preferred] if preferred else [kind for kind, pages in statements.items() if pages]
    strategy = str(prior.get("discovery_strategy") or "")
    tokens = (
        [display_name]
        if strategy in {"STATEMENT_ITEM_TO_NOTE_FAMILY", "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE"}
        else _tokens(display_name, prior)
    )
    rows: list[dict[str, Any]] = []
    for statement_type in candidate_types:
        pages = set(statements.get(statement_type, []))
        for rec in index:
            if rec.page_number not in pages or rec.page_number not in qualified_pages:
                continue
            note_header = ""
            page_lines = rec.text.splitlines()
            for line_index, raw_line in enumerate(page_lines):
                text = " ".join(raw_line.split())
                # The statement note column can either expose a section
                # (附注八) or merely say 附注. Both are valid grammars.
                note_header_match = re.search(
                    r"(?:附注|注)\s*[一二三四五六七八九十百\d]+", text
                )
                if note_header_match:
                    note_header = note_header_match.group(0)
                elif re.fullmatch(r"(?:附注|注)", text):
                    note_header = text
                matched = next((t for t in sorted(tokens, key=len, reverse=True) if t in text), None)
                if not matched:
                    continue
                if strategy in {
                    "STATEMENT_ITEM_TO_NOTE_FAMILY",
                    "STATEMENT_ITEM_TO_SINGLE_NOTE_COMPLEX_TABLE",
                } and not _is_target_line(text, display_name):
                    continue
                next_line = page_lines[line_index + 1] if line_index + 1 < len(page_lines) else ""
                note = _extract_tail_reference(text, matched, note_header, next_line)
                statement_amount_tokens = _nearby_statement_amount_observations(
                    page_lines, line_index, matched
                )
                ocr_used = rec.page_number in page_modes
                # OCR tokens are retained only as source evidence.  The OCR
                # fallback has no native PDF cell geometry, so it cannot emit
                # statement or canonical amounts.
                statement_amounts = [] if ocr_used else statement_amount_tokens
                note_ref = note["note_reference_normalized"]
                if note_ref:
                    page, method, confidence = locate_note(
                        index,
                        note_reference=note_ref,
                        item=matched,
                        section_context=rec.section,
                        authoritative_main_statement_page=rec.page_number,
                    )
                    candidates = [page] if page else []
                else:
                    page, method, confidence, candidates = _locate_without_reference(
                        index, matched, rec.section, exclude_pages=pages
                    )
                    if note.get("note_reference_item"):
                        inferred_section = _infer_note_section_from_target_page(
                            index, page, _infer_statement_scope(rec.text, statement_type, page_number=rec.page_number, statement_pages=list(pages))
                        )
                        if inferred_section:
                            note = compose_note_reference(
                                f"附注{inferred_section}", note["note_reference_item"]
                            )
                            note["note_reference_status"] = "INFERRED"
                            note_ref = note["note_reference_normalized"]
                            method = "HEADING_MATCH_WITH_SECTION_INFERENCE"
                rows.append({
                    "company": company, "normalized_company": normalize_company(company), "report_year": str(report_year),
                    "filing_type": filing_type, "statement_type": statement_type,
                    "scope": _infer_statement_scope(rec.text, statement_type, page_number=rec.page_number, statement_pages=list(pages)),
                    "source_statement_scope": _infer_statement_scope(rec.text, statement_type, page_number=rec.page_number, statement_pages=list(pages)),
                    "display_name": display_name, "table_family": display_name, "statement_item": matched,
                    "member_table": matched, "source_table_title": rec.section or statement_type,
                    "statement_amount_raw": statement_amounts,
                    "statement_amount_normalized": statement_amounts,
                    "statement_amounts": statement_amounts,
                    "amount_source_present": bool(statement_amounts),
                    "section_context": rec.section, "statement_pdf_page_index": rec.page_number,
                    "statement_page": rec.page_number, "statement_printed_page": None,
                    "candidate_note_pdf_page_index": page, "note_page": page, "candidate_note_pages": candidates,
                    "confirmed_note_pdf_page_index": None, "locator_method": method, "confidence": confidence,
                    "status": "REVIEW_REQUIRED" if not note_ref or confidence < .80 else "NEEDS_REVIEW",
                    "discovery_mode": page_modes.get(rec.page_number, "TEXT_LAYER"),
                    "ocr_used": ocr_used,
                    "native_value_geometry_present": False,
                    "value_evidence_status": (
                        "REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY"
                        if ocr_used
                        else (
                            "REVIEW_REQUIRED_MISSING_NATIVE_GEOMETRY"
                            if statement_amounts
                            else "NO_VALUE_EVIDENCE"
                        )
                    ),
                    "ocr_engine": ocr_audit.get("ocr_engine") if ocr_used else "",
                    "ocr_confidence": ocr_audit.get("max_ocr_candidate_score") if ocr_used else None,
                    "page_modality": next((x.get("page_modality") for x in ocr_audit.get("page_modalities", []) if x.get("page")==rec.page_number), "TEXT_DOMINANT"),
                    "text_layer_char_count": len(re.sub(r"\s+", "", rec.text)),
                    "ocr_trigger_reason": ocr_audit.get("ocr_trigger_reason", ""),
                    "main_statement_discovery_status": ocr_audit.get("final_status", "FOUND_HIGH_CONFIDENCE_TEXT"),
                    # This is a source-recovery fact, not a financial or
                    # semantic conclusion.  It lets the family-resolution
                    # layer distinguish an OCR-visible section parent from a
                    # page where a stamp/scan defect left only child rows.
                    "family_parent_recovery_status": (
                        qualified_page_evidence.get(rec.page_number, {}).get("parent_recovery_status")
                        or ("SOURCE_PARENT_RECOVERED" if _is_target_line(text, display_name)
                            else "NOT_APPLICABLE")
                    ),
                    **note,
                    "note_reference": note_ref,
                    "evidence": {"raw_line": text, "note_header": note_header, "prior": prior,
                                 "statement_pages": sorted(pages), "locator_candidates": candidates,
                                 "qualified_target_page": rec.page_number in qualified_pages,
                                 "qualified_target_reason": qualified_page_reasons.get(rec.page_number, ""),
                                 "qualified_target_evidence": qualified_page_evidence.get(rec.page_number, {}),
                                 "ocr_token_provenance": ({
                                     "source": "OCR_PAGE_TEXT",
                                     "page": rec.page_number,
                                     "engine": ocr_audit.get("ocr_engine"),
                                     "confidence": ocr_audit.get("max_ocr_candidate_score"),
                                     "raw_numeric_tokens": statement_amount_tokens,
                                     "usable_as_amount": False,
                                     "native_geometry_present": False,
                                 } if ocr_used else {}),
                                 "ocr_audit": {key: ocr_audit.get(key) for key in (
                                     "ocr_triggered", "ocr_trigger_reason", "final_status", "ocr_page_count",
                                 )}},
                })
    # Preserve different statement occurrence/scope contexts. Only exact same
    # source line is deduplicated here; later clustering preserves all evidence.
    unique: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = (row["statement_type"], row["source_table_title"], row["statement_item"],
               row["statement_pdf_page_index"])
        existing = unique.get(key)
        if not existing:
            row["evidence"]["raw_lines"] = [row["evidence"]["raw_line"]]
            unique[key] = row
            continue
        # One page/type/item is one logical candidate.  OCR adds corroborating
        # evidence; it must never create a duplicate candidate beside a text
        # layer hit on the same page.
        existing["evidence"].setdefault("raw_lines", [existing["evidence"]["raw_line"]]).append(row["evidence"]["raw_line"])
        if (
            not existing.get("note_reference_normalized")
            and row.get("note_reference_normalized")
        ):
            for field in (
                "note_reference_section", "note_reference_item",
                "note_reference_raw", "note_reference_normalized",
                "note_reference_status", "note_reference",
                "candidate_note_pdf_page_index", "note_page",
                "candidate_note_pages", "locator_method", "confidence",
            ):
                existing[field] = row.get(field)
        modes={existing.get("discovery_mode"), row.get("discovery_mode")}
        if "OCR_FALLBACK" in modes or "HYBRID_TEXT_OCR" in modes:
            existing["discovery_mode"] = "HYBRID_TEXT_OCR"
            existing["ocr_used"] = True
            existing["evidence"]["ocr_evidence_merged"] = True
    if qualified_pages and ocr_audit.get("ocr_triggered"):
        ocr_audit["qualified_target_pages"] = sorted(qualified_pages)
        ocr_audit["qualified_target_page_reasons"] = qualified_page_reasons
        ocr_audit["final_status"] = "FOUND_QUALIFIED_TARGET_AFTER_OCR"
    elif unique and not ocr_audit.get("ocr_triggered"):
        # The returned rows are native-text statement candidates.  A policy
        # decision not to OCR an image-only companion page is not a discovery
        # failure and must not mask this successful result in the final audit.
        ocr_audit["final_status"] = "FOUND_HIGH_CONFIDENCE_TEXT"
    if audit_sink is not None:
        audit_sink.update(ocr_audit)
    if resolved_index_sink is not None:
        resolved_index_sink.extend(index)
    return list(unique.values())


def assemble_statement_occurrences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build proposed parent + contiguous candidate children per statement page.

    This is deliberately conservative: it uses only candidates found on the
    same primary-statement page and retains the raw rows as evidence.  A later
    anchor review is required to decide scope and to add/remove members.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        key = (row.get("pdf_id"), row.get("display_name"), row.get("statement_type"),
               row.get("statement_pdf_page_index") or row.get("statement_page"), row.get("source_table_title"))
        groups.setdefault(key, []).append(row)
    occurrences = []
    for key, members in groups.items():
        first = members[0]
        children = []
        for item in members:
            # display_name itself may be a section heading and has no number.
            if normalize_text(item.get("statement_item")) == normalize_text(item.get("display_name")):
                continue
            children.append({
                "item": item.get("statement_item"), "member_table": item.get("member_table"),
                "value": item.get("statement_value"),
                "statement_amount_raw": item.get("statement_amount_raw"),
                "statement_amount_normalized": item.get("statement_amount_normalized"),
                "statement_amounts": item.get("statement_amounts"),
                "amount_source_present": bool(item.get("amount_source_present")),
                # OCR spatial observations are review-only Anchor evidence;
                # preserve them through occurrence assembly without treating
                # them as certified financial values.
                "anchor_amount_observations": list(item.get("anchor_amount_observations") or []),
                "anchor_period_observations": list(item.get("anchor_period_observations") or []),
                "ocr_spatial_geometry_verified": bool(item.get("ocr_spatial_geometry_verified")),
                "value_evidence_status": item.get("value_evidence_status"),
                "note_reference_normalized": item.get("note_reference_normalized") or item.get("note_reference") or "",
                "note_reference_status": item.get("note_reference_status"),
                "candidate_note_pdf_page_index": item.get("candidate_note_pdf_page_index") or item.get("note_page"),
                "candidate_note_printed_page": item.get("candidate_note_printed_page"),
                "locator_method": item.get("locator_method"), "confidence": item.get("confidence"),
                "source_discovery_id": item.get("discovery_id"),
            })
        if children:
            prior_evidence = dict(first.get("evidence") or {})
            prior_evidence.update({
                "raw_discovery_ids": [x.get("discovery_id") for x in members],
                "assembly": "SAME_STATEMENT_PAGE",
            })
            occurrences.append({
                **first, "parent_text": first.get("display_name"), "child_rows": children,
                "scope": first.get("scope", "UNKNOWN"), "source_table_title": first.get("source_table_title") or first.get("statement_type"),
                "evidence": prior_evidence,
            })
    return occurrences


def hierarchical_backoff(query: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ML-ready deterministic backoff; no numeric field participates."""
    levels = ("normalized_company", "filing_type", "statement_type", "scope", "display_name", "member_table")
    ranked = []
    for candidate in candidates:
        matched = sum(1 for field in levels if query.get(field) and query.get(field) == candidate.get(field))
        ranked.append(dict(candidate) | {"backoff_score": round(matched / len(levels), 3), "backoff_level": matched})
    return sorted(ranked, key=lambda x: (x["backoff_score"], x.get("success_count", 0)), reverse=True)
