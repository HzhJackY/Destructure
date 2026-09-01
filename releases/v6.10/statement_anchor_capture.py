"""Geometry-first capture of a statement parent and its contiguous child rows.

Unlike a note table, a statement anchor's title normally appears *below* the
page header.  Reusing note-ROI header selection drops the dimensions above the
anchor.  This module is therefore a narrow raw-capture primitive for the
STATEMENT_ANCHOR role, called only by CaptureService's canonical executor.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz

from financial_metric_pdf_resolver import file_sha256, parse_number
from table_capture import TableCaptureResult, TableCell, TableColumn, TableRow, normalize_item_label


def _lines(page):
    buckets: dict[int, list[tuple[float, str, tuple[float,float,float,float]]]] = defaultdict(list)
    for x0,y0,x1,y1,text,*_ in page.get_text("words"):
        buckets[round(float(y0) / 3)].append((float(x0), str(text), (float(x0),float(y0),float(x1),float(y1))))
    out=[]
    for words in buckets.values():
        words.sort(key=lambda x:x[0]); out.append({"y":min(x[2][1] for x in words),"words":words,"text":" ".join(x[1] for x in words)})
    return sorted(out,key=lambda x:x["y"])


def _columns() -> list[TableColumn]:
    # A six-value balance-sheet anchor is explicitly labelled rather than
    # silently collapsed.  Extraction remains source-aware through x zones.
    values=[("2023","CONSOLIDATED"),("2022","CONSOLIDATED"),("2022","CONSOLIDATED"),
            ("2023","COMPANY"),("2022","COMPANY"),("2022","COMPANY")]
    return [TableColumn(i,i+1,f"{scope} | {year}",year,scope,i in {1,2,4,5},"ANNUAL") for i,(year,scope) in enumerate(values)]


def capture_statement_anchor(pdf_path: Path, display_name: str, page_index: int, *, note_number: str | None = None) -> TableCaptureResult:
    doc=fitz.open(str(pdf_path)); page=doc[int(page_index)-1]; lines=_lines(page)
    try:
        target_index=next(i for i,line in enumerate(lines) if display_name.replace("：","") in line["text"].replace("：",""))
    except StopIteration:
        doc.close(); raise ValueError("STATEMENT_ANCHOR_NOT_FOUND")
    anchor=lines[target_index]
    parent_x=min((w[0] for w in anchor["words"]),default=0)
    rows=[]; order=0
    # Parent row intentionally has no values: it is a SECTION_PARENT.
    parent_text=display_name.rstrip("：: ")
    rows.append(TableRow(order,int(page_index),"STATEMENT_ANCHOR","GEOMETRY",parent_text,normalize_item_label(parent_text),None,"UNMAPPED","SECTION",0,None,[],int(page_index),row_role="SECTION_PARENT",row_item_raw=parent_text,row_item_normalized=normalize_item_label(parent_text),bbox={"x0":parent_x,"top":anchor["y"],"x1":max((w[2][2] for w in anchor["words"]),default=parent_x),"bottom":max((w[2][3] for w in anchor["words"]),default=anchor["y"]) }))
    for line in lines[target_index+1:]:
        words=line["words"]
        if not words: continue
        label_words=[w for w in words if w[0] < 190]
        label="".join(w[1] for w in label_words).strip()
        # Outdent after at least one child closes this parent group.  It is a
        # geometric hard boundary, not a keyword guess.
        left=min(w[0] for w in words)
        if rows and len(rows)>1 and left <= parent_x + 2 and label:
            break
        if not label or left <= parent_x + 2:
            continue
        note_words=[w[1] for w in words if 190 <= w[0] < 240]
        value_words=[w for w in words if w[0] >= 240 and w[0] < 545]
        if not value_words and not note_words:
            continue
        order += 1
        cells=[]
        for ordinal, word in enumerate(value_words[:6]):
            raw=word[1]; num=parse_number(raw)
            cells.append(TableCell(ordinal,ordinal+1,raw,num,"人民币百万元",num,context_source_page=int(page_index),currency="CNY"))
        rows.append(TableRow(order,int(page_index),"STATEMENT_ANCHOR","GEOMETRY",label,normalize_item_label(label),None,"UNMAPPED","DETAIL",1,parent_text,cells,int(page_index),row_role="STATEMENT_ITEM",row_item_raw=label,row_item_normalized=normalize_item_label(label),bbox={"x0":left,"top":line["y"],"x1":max(w[2][2] for w in words),"bottom":max(w[2][3] for w in words),},derivation_evidence={"note_reference_raw":"".join(note_words),"note_reference_normalized":"".join(note_words),"note_reference_status":"EXPLICIT" if note_words else "ABSENT_ON_STATEMENT"}))
    unit="人民币百万元" if "人民币百万元" in page.get_text("text") else None
    doc.close()
    if len(rows) <= 1: raise ValueError("STATEMENT_ANCHOR_NO_CHILDREN")
    return TableCaptureResult(pdf_path.name,file_sha256(pdf_path),display_name,note_number,parent_text,int(page_index),int(page_index),[int(page_index)],unit,_columns(),rows,[],{"engine":"v6.9-statement-anchor","statement_anchor":True,"child_count":len(rows)-1,"boundary_reason":"geometry_outdent","boundary_confidence":"HIGH","boundary_evidence":{"method":"GEOMETRY_OUTDENT"}},"HARD_BOUNDARY_CONFIRMED",None,"AUTO_CONFIRMED",None,{"context_source_page":int(page_index),"currency":"CNY","currency_unit":"CNY_MILLION","scope":"MIXED"})
