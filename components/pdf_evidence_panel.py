from __future__ import annotations

import json
from pathlib import Path


def render_pdf_evidence_panel(st, detail: dict, result: dict, block: dict | None = None) -> None:
    pdf=Path(str(detail.get("pdf_path") or ""))
    if not pdf.is_file():
        st.warning("源 PDF 不可用；Capture 证据仍保留，但无法渲染页面。")
        return
    start=(block or {}).get("start_pdf_page") or result.get("start_page") or 1
    page_key=f"inspection_pdf_page_{detail['capture_id']}"
    if page_key not in st.session_state: st.session_state[page_key]=int(start)
    prev_col,next_col,zoom_col=st.columns([1,1,3])
    if prev_col.button("上一页",key=f"prev_{detail['capture_id']}"):
        st.session_state[page_key]=max(1,int(st.session_state[page_key])-1)
    if next_col.button("下一页",key=f"next_{detail['capture_id']}"):
        st.session_state[page_key]=int(st.session_state[page_key])+1
    zoom=zoom_col.slider("缩放",70,160,100,key=f"zoom_{detail['capture_id']}")
    from pdf_evidence import page_preview
    keywords=[str(detail.get("member_table_id") or ""),str(detail.get("table_family_id") or "")]
    preview=page_preview(pdf,int(st.session_state[page_key])-1,keywords)
    if preview.get("png"):
        st.image(preview["png"],caption=f"PDF {preview['pdf_page_index']}页（印刷页 {preview.get('printed_page') or '-'}）· 缩放 {zoom}%",use_container_width=True)
    evidence={
        "Note Container":result.get("stats",{}).get("boundary_evidence"),
        "Block bbox":(block or {}).get("bbox_json"),
        "row bboxes":[row.get("bbox") for row in result.get("rows",[]) if row.get("bbox")][:30],
        "context_source_page":(result.get("document_context") or {}).get("context_source_page"),
        "confidence":result.get("stats",{}).get("boundary_confidence"),
    }
    with st.expander("边界与高亮证据"):
        st.json(evidence)
