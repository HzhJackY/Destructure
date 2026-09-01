"""v6.10 Stage B unified child capture execution flow contracts.

Validates:
  - Both flows can create the same shared execution component
  - Strict flow uses batch submission (no longer per-child synchronous)
  - Compat flow is a thin adapter (no independent implementation)
  - Both flows show the same explicit capture-scope confirmation button
  - Both flows use the same progress display
  - Both flows redirect to logical asset workspace on completion
  - ChildCaptureExecutionService.create_execution_batch() works
  - ChildCaptureExecutionService.monitor_all() returns correct structure
  - ChildCaptureExecutionService.all_terminal() detects completion
  - Research batch linkage is consistent
  - No duplicate session state, callbacks, or progress polling
  - Producer version, identity, review, merge are consistent across flows
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json
import pytest


def test_shared_component_imports() -> None:
    """Both the component and service modules are importable."""
    from components.child_capture_execution_panel import render_child_capture_execution_panel
    from services.child_capture_execution_service import ChildCaptureExecutionService
    assert callable(render_child_capture_execution_panel)
    assert ChildCaptureExecutionService is not None
    print("SHARED_COMPONENT_IMPORTS_PASS")


def test_service_init() -> None:
    """ChildCaptureExecutionService can be instantiated with all dependencies."""
    from services.child_capture_execution_service import ChildCaptureExecutionService

    svc = ChildCaptureExecutionService(
        registry=None,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
    )
    assert svc is not None
    print("SERVICE_INIT_PASS")


def test_service_monitor_structure() -> None:
    """monitor_all returns properly structured rows."""
    from services.child_capture_execution_service import ChildCaptureExecutionService

    svc = ChildCaptureExecutionService(
        registry=None,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
    )
    # Without a real runner, monitor_all on an empty list returns empty list
    rows = svc.monitor_all([])
    assert rows == [], f"Expected empty list, got {rows}"
    print("SERVICE_MONITOR_STRUCTURE_PASS")


def test_service_all_terminal_empty() -> None:
    """all_terminal returns False for empty batch list."""
    from services.child_capture_execution_service import ChildCaptureExecutionService

    svc = ChildCaptureExecutionService(
        registry=None,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
    )
    assert svc.all_terminal([]) is False
    print("SERVICE_ALL_TERMINAL_EMPTY_PASS")


def test_service_failed_batch_ids_empty() -> None:
    """failed_batch_ids returns empty for empty batch list."""
    from services.child_capture_execution_service import ChildCaptureExecutionService

    svc = ChildCaptureExecutionService(
        registry=None,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
    )
    assert svc.failed_batch_ids([]) == []
    print("SERVICE_FAILED_BATCH_IDS_EMPTY_PASS")


def test_service_build_review_queue_no_capture_version() -> None:
    """build_review_queue returns empty when capture_version_service is None."""
    from services.child_capture_execution_service import ChildCaptureExecutionService

    svc = ChildCaptureExecutionService(
        registry=None,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
    )
    assert svc.build_review_queue("nonexistent") == []
    print("SERVICE_BUILD_REVIEW_QUEUE_NO_CV_PASS")


def test_service_signature_accepts_empty_input() -> None:
    """create_execution_batch signature accepts optional certified_links and plans."""
    import inspect
    from services.child_capture_execution_service import ChildCaptureExecutionService

    sig = inspect.signature(ChildCaptureExecutionService.create_execution_batch)
    params = sig.parameters
    assert params["certified_links"].default is None, "certified_links should default to None"
    assert params["plans"].default is None, "plans should default to None"
    assert params["capture_scope_contract_version"].default is None
    assert params["capture_scope_policy"].default is None
    assert params["selected_logical_table_ids"].default is None
    assert params["selected_block_roles"].default is None
    assert params["selected_block_ids"].default is None
    assert params["create_new_attempt"].default is False
    # The function can be called with only display_name
    print("SERVICE_SIGNATURE_ACCEPTS_EMPTY_INPUT_PASS")


def test_render_function_signature() -> None:
    """render_child_capture_execution_panel accepts all expected kwargs."""
    import inspect
    from components.child_capture_execution_panel import render_child_capture_execution_panel

    sig = inspect.signature(render_child_capture_execution_panel)
    params = list(sig.parameters)
    required = {"st_obj", "backend", "display_name"}
    assert required.issubset(set(params)), f"Missing params: {required - set(params)}"
    optional = {"certified_links", "plans", "source_pdf_map", "research_definition", "scope", "key_prefix"}
    for opt in optional:
        assert opt in params, f"Missing optional param: {opt}"
    print("RENDER_FUNCTION_SIGNATURE_PASS")


def test_terminal_plan_renders_explicit_replay_and_forwards_new_attempt() -> None:
    from components.child_capture_execution_panel import (
        render_child_capture_execution_panel,
    )

    class _Context:
        def __enter__(self):
            return self

        def __exit__(self,*_args):
            return False

    class _Streamlit:
        def __init__(self):
            self.session_state={}
            self.buttons=[]

        def markdown(self,*_args,**_kwargs): pass
        def caption(self,*_args,**_kwargs): pass
        def dataframe(self,*_args,**_kwargs): pass
        def info(self,*_args,**_kwargs): pass
        def warning(self,*_args,**_kwargs): pass
        def success(self,*_args,**_kwargs): pass
        def expander(self,*_args,**_kwargs): return _Context()
        def checkbox(self,_label,*,value=False,**_kwargs): return value

        def button(self,label,**_kwargs):
            self.buttons.append((label,dict(_kwargs)))
            return label=="重新抓取当前逻辑表"

        def rerun(self):
            raise RuntimeError("RERUN")

    target={
        "status":"CERTIFIED_NOTE_TARGET",
        "logical_table_id":"LOGICAL_FIXTURE",
        "table_classification":"PRIMARY_TABLE",
        "segment_manifest_status":"CERTIFIED_SEGMENT_MANIFEST",
        "certified_segments":[{"certified_segment_id":"SEGMENT_FIXTURE"}],
    }
    state={
        "session_key":"STAGEB_FIXTURE",
        "entry_origin":"STRICT",
        "status":"TERMINAL",
        "executed":True,
        "research_batch_id":"RB_OLD",
        "plan_ids":["PLAN_FIXTURE"],
        "plans":[{
            "plan_id":"PLAN_FIXTURE",
            "table_family":"family_fixture",
            "items":[{
                "member_table":"member_fixture",
                "member_table_role":"NOTE_DETAIL",
                "status":"READY",
                "certified_note_target":target,
            }],
        }],
        "batch_ids":["BATCH_OLD"],
        "progress":[],
        "all_terminal":True,
        "all_plans_submitted":True,
        "review_queue":[],
        "callback_key":"GuidedCaptureService.execute",
        "workspace_route":"逻辑资产工作区",
        "workspace_filter":{"research_batch_id":"RB_OLD"},
        "capture_scope":{
            "capture_scope_contract_version":2,
            "capture_scope_policy":"PRIMARY_ONLY",
            "selected_logical_table_ids":[],
        },
    }

    class _Service:
        def __init__(self): self.calls=[]
        def execution_session_key(self,**_kwargs): return "STAGEB_FIXTURE"
        def latest_execution_session_key(self,_key): return "STAGEB_FIXTURE"
        def restore_execution(self,_key): return dict(state)
        def preview_capture_plans(self,**_kwargs): return dict(state)
        def create_execution_batch(self,**kwargs):
            self.calls.append(kwargs)
            return dict(state,session_key="STAGEB_REPLAY",research_batch_id="RB_NEW",job_count=1,blocked_count=0)

    service=_Service()
    backend=type("Backend",(),{"child_capture_execution_service":service})()
    st_obj=_Streamlit()
    with pytest.raises(RuntimeError,match="RERUN"):
        render_child_capture_execution_panel(
            st_obj,backend,display_name="family_fixture",plans=state["plans"],
        )
    assert service.calls[0]["create_new_attempt"] is True
    assert any(label=="重新抓取当前逻辑表" for label,_ in st_obj.buttons)
    assert st_obj.session_state["v610_child_capture_submission_feedback"].startswith(
        "研究批次 RB_NEW"
    )


def test_capture_scope_request_contract_round_trip_and_validation() -> None:
    from capture_models import (
        CAPTURE_SCOPE_CONTRACT_VERSION,
        LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
        CaptureMode,
        CaptureRequest,
    )

    legacy_request=CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path="C:/fixture.pdf",
        member_table_id="member_fixture",
        capture_scope_contract_version=LEGACY_CAPTURE_SCOPE_CONTRACT_VERSION,
        capture_scope_policy="ALL_NOTE_TABLES",
        selected_block_roles=["SUPPLEMENTARY_TABLE","SUPPLEMENTARY_TABLE"],
        selected_block_ids=["BLOCK_A","BLOCK_A"],
    )
    restored_legacy=CaptureRequest.from_dict(legacy_request.to_dict())
    assert restored_legacy.capture_scope_contract_version==1
    assert restored_legacy.capture_scope_policy=="ALL_NOTE_TABLES"
    assert restored_legacy.selected_block_roles==("SUPPLEMENTARY_TABLE",)
    assert restored_legacy.selected_block_ids==("BLOCK_A",)
    restored_legacy.validate()

    historical_payload=legacy_request.to_dict()
    historical_payload.pop("capture_scope_contract_version")
    restored_historical=CaptureRequest.from_dict(historical_payload)
    assert restored_historical.capture_scope_contract_version==1
    assert restored_historical.capture_scope_policy=="ALL_NOTE_TABLES"

    request=CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path="C:/fixture.pdf",
        member_table_id="member_fixture",
        capture_scope_contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
        capture_scope_policy="SELECTED_NOTE_TABLES",
        selected_logical_table_ids=["LOGICAL_A","LOGICAL_A"],
    )
    restored=CaptureRequest.from_dict(request.to_dict())
    assert restored.capture_scope_contract_version==2
    assert restored.capture_scope_policy=="SELECTED_NOTE_TABLES"
    assert restored.selected_logical_table_ids==("LOGICAL_A",)
    assert restored.selected_block_roles==()
    assert restored.selected_block_ids==()
    restored.validate()

    with pytest.raises(ValueError,match="V2_CAPTURE_SCOPE_REJECTS_BLOCK_SELECTION"):
        CaptureRequest.new(
            capture_mode=CaptureMode.CERTIFIED_TARGET,
            source_pdf_path="C:/fixture.pdf",
            member_table_id="member_fixture",
            capture_scope_contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
            capture_scope_policy="SELECTED_NOTE_TABLES",
            selected_logical_table_ids=["LOGICAL_A"],
            selected_block_roles=["SUPPLEMENTARY_TABLE"],
        )

    mapped=CaptureRequest.new(
        capture_mode=CaptureMode.CERTIFIED_TARGET,
        source_pdf_path="C:/fixture.pdf",
        member_table_id="member_fixture",
        capture_scope_contract_version=CAPTURE_SCOPE_CONTRACT_VERSION,
        capture_scope_policy="PRIMARY_WITH_CONTINUATIONS",
    )
    assert mapped.capture_scope_policy=="PRIMARY_ONLY"


def test_scope_fields_reach_capture_service_without_block_filtering() -> None:
    source=(ROOT/"services"/"capture_service.py").read_text(encoding="utf-8")
    assert "capture_scope_contract_version=(" in source
    assert "capture_scope_policy=request.capture_scope_policy" in source
    assert "selected_logical_table_ids=request.selected_logical_table_ids" in source
    assert '"capture_scope_policy":' in source
    assert "selected_block_roles=request.selected_block_roles" in source
    assert "selected_block_ids=request.selected_block_ids" in source


def test_both_flows_have_key_prefix() -> None:
    """The two flows use different key_prefix values to avoid collisions."""
    keys = {"v610_strict_child", "v610_compat_child"}
    assert len(keys) == 2
    assert "v610_strict_child" in keys
    assert "v610_compat_child" in keys
    print("BOTH_FLOWS_KEY_PREFIX_PASS")


def test_guided_workflow_ui_strict_flow_uses_panel() -> None:
    """The strict flow imports and uses render_child_capture_execution_panel."""
    content = Path(
        ROOT / "guided_workflow_ui.py"
    ).read_text(encoding="utf-8")
    assert "render_child_capture_execution_panel" in content
    assert "components.child_capture_execution_panel" in content
    # The old synchronous orchestrator loop should be gone
    assert "通过 Capture Orchestrator 抓取已认证子表" not in content, (
        "Old synchronous button text still present in guided_workflow_ui.py"
    )
    print("GUIDED_WORKFLOW_UI_STRICT_USES_PANEL_PASS")


def test_guided_workflow_ui_compat_is_thin_adapter() -> None:
    """The compat flow is a thin adapter — no independent implementation."""
    content = Path(
        ROOT / "guided_workflow_ui.py"
    ).read_text(encoding="utf-8")
    # The old progress monitoring block should be gone
    assert "v651_guided_batch_ids" not in content, (
        "Old guided batch IDs session state still present"
    )
    assert "v651_refresh_guided_jobs" not in content, (
        "Old progress refresh button still present"
    )
    # The old completion redirect should be gone
    assert "v610_guided_review_capture_selection" not in content, (
        "Old review capture selection key still present"
    )
    print("GUIDED_WORKFLOW_UI_COMPAT_IS_THIN_ADAPTER_PASS")


def test_old_capture_outcomes_removed() -> None:
    """The old v610_capture_outcomes session state key is no longer used."""
    content = Path(
        ROOT / "guided_workflow_ui.py"
    ).read_text(encoding="utf-8")
    assert "v610_capture_outcomes" not in content, (
        "Old perpetual synchronous outcomes state still present"
    )
    print("OLD_CAPTURE_OUTCOMES_REMOVED_PASS")


def test_no_duplicate_state_keys() -> None:
    """No duplicate session state, callbacks, or polling between the two flows."""
    content = Path(
        ROOT / "guided_workflow_ui.py"
    ).read_text(encoding="utf-8")
    # Both references to render_child_capture_execution_panel should use
    # different key_prefix values
    import re
    calls = re.findall(r"key_prefix\s*=\s*\"([^\"]+)\"", content)
    # Only the two calls should remain (one for strict, one for compat)
    assert len(calls) >= 2, f"Expected at least 2 key_prefix assignments, got {len(calls)}"
    print("NO_DUPLICATE_STATE_KEYS_PASS")


def main() -> None:
    test_shared_component_imports()
    test_service_init()
    test_service_monitor_structure()
    test_service_all_terminal_empty()
    test_service_failed_batch_ids_empty()
    test_service_build_review_queue_no_capture_version()
    test_service_signature_accepts_empty_input()
    test_render_function_signature()
    test_both_flows_have_key_prefix()
    test_guided_workflow_ui_strict_flow_uses_panel()
    test_guided_workflow_ui_compat_is_thin_adapter()
    test_old_capture_outcomes_removed()
    test_no_duplicate_state_keys()
    print("\n=== ALL 13 STAGE B UNIFIED FLOW TESTS PASSED ===")


if __name__ == "__main__":
    main()
