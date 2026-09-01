"""Permanent v6.11 regression for ambiguous post-total content."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from capture_library import derive_boundary_status


def _base_result():
    return {
        "boundary_status":"REVIEW_REQUIRED",
        "warnings":[
            "BOUNDARY_REVIEW_REQUIRED：未发现可信的下一同级附注标题，请人工核对末尾。"
        ],
        "stats":{
            "boundary_reason":"boundary_unresolved",
            "boundary_evidence":{"method":"NO_PEER_HEADING_FOUND"},
            "roi":{"end_y":800},
            "post_total_disclosure_not_merged":False,
            "v69_header_topology":{"consistent":True},
            "v69_reconciliation":{"status":"PASS"},
        },
        "rows":[
            {
                "row_order":1,"raw_item":"政府债","row_role":"DETAIL",
                "bbox":{"y1":520},
            },
            {
                "row_order":2,"raw_item":"合计","row_role":"TOTAL",
                "bbox":{"y1":600},
            },
            {
                "row_order":3,"raw_item":"其中：",
                "row_role":"SECTION_HEADER","bbox":{"y1":640},
            },
            {
                "row_order":4,"raw_item":"累计公允价值变动",
                "row_role":"DETAIL","bbox":{"y1":690},
            },
        ],
    }


def test_mid_page_or_ambiguous_post_total_content_stays_review_required():
    mid=_base_result()
    mid["rows"][-1]["bbox"]["y1"]=500
    assert derive_boundary_status(mid)=="REVIEW_REQUIRED"

    prose=_base_result()
    prose["rows"][-1]["row_role"]="NOTE_TEXT"
    assert derive_boundary_status(prose)=="REVIEW_REQUIRED"

