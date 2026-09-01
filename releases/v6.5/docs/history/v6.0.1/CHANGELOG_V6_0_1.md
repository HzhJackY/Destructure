# CHANGELOG v6.0.1

## Streamlit Batch-ID Hotfix

- Fixed `StreamlitAPIException` when clicking `生成新批次ID`.
- Removed direct mutation of `st.session_state.table_capture_batch_id` after `st.text_input` instantiation.
- Added `_generate_table_capture_batch_id()` callback.
- `st.button(..., on_click=...)` now updates the widget-bound key safely before rerun.
- Removed unnecessary explicit `st.rerun()` from the button path.
- DATA_HOME schema remains 6.0; no migration required.
