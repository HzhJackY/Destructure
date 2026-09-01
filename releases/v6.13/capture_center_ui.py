"""Streamlit Capture Center backed only by CaptureService."""
from __future__ import annotations

from pathlib import Path

from capture_models import CaptureMode, CaptureRequest


def render_capture_center(st, backend, pdf_paths: list[Path]) -> None:
    st.title("抓取中心")
    st.caption("所有入口统一生成 CaptureRequest；发现、认证与执行相互分离。")
    if not pdf_paths:
        st.info("请先在 PDF 选择区载入文件。")
        return
    pdf = st.selectbox("来源 PDF", pdf_paths, format_func=lambda p: Path(p).name)
    query = st.text_input("目标表名称")
    mode = st.selectbox(
        "抓取模式",
        [CaptureMode.DIRECT_DISCLOSURE.value, CaptureMode.MANUAL_ROI.value],
        format_func=lambda x: {"DIRECT_DISCLOSURE": "自动定位整表", "MANUAL_ROI": "已认证页码/区域"}[x],
    )
    page = st.number_input("认证 PDF 页（手工模式）", min_value=1, value=1,
                           disabled=mode != CaptureMode.MANUAL_ROI.value)
    if st.button("提交抓取请求", type="primary", disabled=not query.strip()):
        request = CaptureRequest.new(
            capture_mode=mode, source_pdf_path=str(Path(pdf).resolve()),
            member_table_id=query.strip(),
            manual_page_range=(int(page), int(page)) if mode == CaptureMode.MANUAL_ROI.value else None,
            request_metadata={"table_query": query.strip()},
        )
        result = backend.capture_service.submit(request, asynchronous=False)
        st.success(f"请求状态：{result.get('status')}")
        st.json({key: result.get(key) for key in
                 ("request_id", "capture_id", "logical_asset_id", "status")})

    st.subheader("运行批次")
    rows = backend.job_service.batch_summaries(job_type="TABLE_CAPTURE", limit=100)
    st.dataframe(rows, use_container_width=True, hide_index=True)
