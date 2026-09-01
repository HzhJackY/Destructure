# Financial Metric Resolver v6.0.1 Hotfix

This hotfix fixes the Streamlit Session State exception raised by the **“生成新批次ID”** button.

## Fixed

Old v6.0 flow:

```python
batch_label = st.text_input(..., key="table_capture_batch_id")
if st.button("生成新批次ID"):
    st.session_state.table_capture_batch_id = new_batch_id()
```

After the `text_input` widget was instantiated, Streamlit rejected mutating the same widget-bound Session State key and raised `StreamlitAPIException`.

v6.0.1 now uses an `on_click` callback:

```python
def _generate_table_capture_batch_id():
    st.session_state["table_capture_batch_id"] = new_batch_id()

st.text_input(..., key="table_capture_batch_id")
st.button(..., on_click=_generate_table_capture_batch_id)
```

The callback executes before the next top-to-bottom rerun, so the new ID is safely written and immediately appears in the text input. No manual refresh is required.

## Compatibility

- DATA_HOME schema remains `6.0`; no data migration is required.
- v5.9 parser regression corpus remains unchanged.
- v6.0 asset lifecycle and single-instance launcher behavior remain unchanged.

## Validation

Passed:

```text
ALL_V59_REGRESSION_CORPUS_PASS
ALL_V60_ASSET_TESTS_PASS
V601_BATCH_ID_CALLBACK_CONTRACT_PASS
```
