from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "app.py").read_text(encoding="utf-8")

assert 'key="table_capture_batch_id"' in app
assert 'def _generate_table_capture_batch_id()' in app
assert 'on_click=_generate_table_capture_batch_id' in app
assert 'st.session_state.table_capture_batch_id = new_batch_id()' not in app

# The callback assignment must occur before widget declaration in source order.
callback_pos = app.index('def _generate_table_capture_batch_id()')
widget_pos = app.index('key="table_capture_batch_id"', callback_pos)
button_callback_pos = app.index('on_click=_generate_table_capture_batch_id', widget_pos)
assert callback_pos < widget_pos < button_callback_pos

print("V601_BATCH_ID_CALLBACK_CONTRACT_PASS")
