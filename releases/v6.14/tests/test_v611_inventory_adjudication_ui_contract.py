from __future__ import annotations

import sys
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from components.child_mapping_review import render_inventory_resolution_case


class _SemanticOnlyStreamlit:
    def __init__(self):
        self.input_labels=[]
        self.button_disabled=None

    def caption(self,*args,**kwargs):
        return None

    def dataframe(self,*args,**kwargs):
        return None

    def error(self,*args,**kwargs):
        raise AssertionError(args[0] if args else "unexpected error")

    def selectbox(self,label,options,*,index,key):
        self.input_labels.append(label)
        return options[index]

    def text_input(self,label,*,key):
        self.input_labels.append(label)
        return ""

    def button(self,label,*,disabled,key):
        self.input_labels.append(label)
        self.button_disabled=disabled
        return False


class _Backend:
    child_discovery_repository=None


def test_unresolved_case_ui_only_collects_semantic_candidate_decisions():
    st=_SemanticOnlyStreamlit()
    case={
        "resolution_case_id":"ICASE_FIXTURE",
        "candidate_id":"CANDIDATE_FIXTURE",
        "note_table_inventory_candidate_id":"NTINV_FIXTURE",
        "machine_snapshot_sha256":"a"*64,
        "machine_snapshot":{
            "logical_tables":[{
                "logical_table_candidate_id":"LTABLE_FIXTURE",
                "classification":"UNRESOLVED",
                "title":"债权投资",
                "start_page":195,"end_page":195,
                "segments":[{
                    "segment_candidate_id":"SEGMENT_FIXTURE",
                    "logical_table_candidate_id":"LTABLE_FIXTURE",
                    "classification":"UNRESOLVED",
                    "start_page":195,"end_page":195,
                }],
            }],
        },
    }

    assert render_inventory_resolution_case(
        st,_Backend(),case,key_prefix="fixture",
    ) is None
    assert st.button_disabled is True
    assert any("逻辑表身份" in label for label in st.input_labels)
    assert any("所属 logical candidate" in label for label in st.input_labels)
    assert any("人工校正依据" in label for label in st.input_labels)
    assert not any("PDF 路径" in label for label in st.input_labels)
    assert not any("页码" in label for label in st.input_labels)
    assert not any("bbox" in label.lower() for label in st.input_labels)
    assert not any("manifest" in label.lower() for label in st.input_labels)


def test_production_ui_has_no_manual_candidate_creation_controls():
    component=(ROOT/"components"/"child_mapping_review.py").read_text(
        encoding="utf-8"
    )
    guided=(ROOT/"guided_workflow_ui.py").read_text(encoding="utf-8")
    assert "manual_add_candidate" not in component
    assert "number_input(" not in component
    assert "手动候选 PDF 路径" not in component
    assert "手动搜索并添加候选" not in component
    assert "认证所选子表关系" not in guided
    assert "unresolved_inventory_cases" in component
    assert "unresolved_inventory_cases" in guided
