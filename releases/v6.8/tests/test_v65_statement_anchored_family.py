from __future__ import annotations

import hashlib
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metadata_registry import MetadataRegistry
from discovery_registry import DiscoveryRegistry
from pdf_selection_workspace import company_options, filter_pdfs
from statement_anchored_family import (
    StatementOccurrence, arbitrate_anchors, build_capture_plan,
    build_statement_anchor_table, cluster_evidence, compose_note_reference,
)
from generic_discovery import hierarchical_backoff
from services.guided_capture_service import GuidedCaptureService


def finance_occurrence(scope="CONSOLIDATED", refs=True, occurrence_id="OCC_A"):
    children = []
    for i, name in enumerate(["交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资"], 9):
        children.append({"item": name, "member_table": name, "value": i * 100,
                         "note_reference_normalized": f"附注八-{i}" if refs else "",
                         "candidate_note_pdf_page_index": 120 + i if refs else None})
    return StatementOccurrence(occurrence_id, "金融投资", "BALANCE_SHEET", "合并资产负债表", scope,
                               76, "70", "金融投资", tuple(children), {"source": "synthetic"})

def certified_plan(occurrence):
    children=[]
    for child in occurrence.child_rows:
        child=dict(child)
        if child.get('candidate_note_pdf_page_index'):
            child['certified_note_target']={'status':'CERTIFIED_NOTE_TARGET','confirmed_note_pdf_page_index':child['candidate_note_pdf_page_index'],'target_heading':child['member_table']}
        children.append(child)
    occurrence=StatementOccurrence(**{**occurrence.__dict__,'child_rows':tuple(children)})
    return build_capture_plan(occurrence, selected_anchor=True)


class V65StatementAnchoredFamilyTests(unittest.TestCase):
    def test_RELEASE_ISOLATION_PASS(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root.parent / "v6.4" / "BUILD_INFO.json").exists())
        self.assertEqual(hashlib.sha256((root.parent / "v6.4" / "version.py").read_bytes()).hexdigest(),
                         "5e252d732d3bb256ba8861afa759f8d998549fed902fae8e40b9373a5446a0d9")

    def test_COMPANY_SELECTOR_TRUE_AGGREGATION_PASS(self):
        paths = [Path("0df8aa7b0dc8_工银安盛年报2022.pdf"), Path("276dd1294a1b_工银安盛年报2024.pdf"),
                 Path("291cbffd2e67_工银安盛年报2025.pdf"), Path("abcd1234abcd_交银人寿年报2024.pdf")]
        opts = company_options(paths)
        self.assertEqual(len(opts), 2)
        self.assertEqual(opts[0][0], "交银人寿")
        self.assertIn("工银安盛（3份，2022–2025）", dict(opts).values())
        self.assertFalse(any("0df8" in label for _, label in opts))
        self.assertEqual(len(filter_pdfs(paths, companies={"工银安盛"})), 3)

    def test_DUPLICATE_DISPLAY_NAME_ANCHOR_ARBITRATION_PASS(self):
        strong, weak = finance_occurrence(), finance_occurrence("COMPANY", refs=False, occurrence_id="OCC_B")
        result = arbitrate_anchors([strong, weak])
        self.assertEqual(result["status"], "SINGLE_STRONG_ANCHOR")
        self.assertEqual(result["selected"]["occurrence"]["occurrence_id"], "OCC_A")
        equal = arbitrate_anchors([finance_occurrence("CONSOLIDATED"), finance_occurrence("COMPANY", occurrence_id="OCC_C")])
        self.assertEqual(equal["status"], "MULTIPLE_VALID_ANCHORS")

    def test_STATEMENT_ANCHOR_PARENT_CHILD_CAPTURE_PASS(self):
        anchor = build_statement_anchor_table(finance_occurrence())
        self.assertEqual(anchor["member_table_role"], "STATEMENT_ANCHOR")
        self.assertEqual(anchor["rows"][0]["row_type"], "SECTION_PARENT")
        self.assertIsNone(anchor["rows"][0]["value"])
        self.assertEqual(len(anchor["rows"]), 5)

    def test_NOTE_REFERENCE_HEADER_ROW_COMPOSITION_PASS(self):
        note = compose_note_reference("附注八", "9")
        self.assertEqual(note["note_reference_normalized"], "附注八-9")
        self.assertEqual(note["note_reference_status"], "COMPOSED_FROM_HEADER_AND_ROW")

    def test_NOTE_REFERENCE_NULL_LOCATOR_FALLBACK_PASS(self):
        note = compose_note_reference("附注八", "")
        self.assertEqual(note["note_reference_status"], "ABSENT_ON_STATEMENT")
        plan = build_capture_plan(finance_occurrence(refs=False), selected_anchor=True)
        self.assertEqual(plan["plan_status"], "REVIEW_REQUIRED")
        self.assertTrue(all(x.get("status") == "REVIEW_REQUIRED" for x in plan["items"][1:]))

    def test_STATEMENT_TO_NOTE_GRAPH_CAPTURE_PLAN_PASS(self):
        plan = certified_plan(finance_occurrence())
        self.assertEqual(len(plan["items"]), 5)
        self.assertEqual(plan["items"][0]["member_table_role"], "STATEMENT_ANCHOR")
        self.assertEqual([x["member_table_role"] for x in plan["items"][1:]], ["NOTE_DETAIL"] * 4)

    def test_GUIDED_CAPTURE_NO_REDUNDANT_TARGET_SELECTION_PASS(self):
        class Runner:
            def __init__(self): self.enqueued = []; self.started = []
            def enqueue(self, **kwargs):
                self.enqueued.append(kwargs)
                return [{"job_id": f"J{len(self.enqueued)}"}]
            def start(self, **kwargs): self.started.append(kwargs)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); registry = MetadataRegistry(root / "metadata.db"); runner = Runner()
            plan = certified_plan(finance_occurrence()); plan["plan_id"] = "PLAN_TEST"
            result = GuidedCaptureService(registry=registry, runner=runner, audit_dir=root).execute(plan, pdf_path=root / "input.pdf")
            self.assertEqual(len(runner.enqueued), 4)
            self.assertTrue(Path(result["anchor_artifact"]).exists())

    def test_DISCOVERY_EVIDENCE_CLUSTERING_PASS(self):
        base = {"company": "工银安盛", "normalized_company": "工银安盛", "report_year": "2025",
                "display_name": "金融投资", "statement_type": "BALANCE_SHEET", "scope": "CONSOLIDATED",
                "member_table": "债权投资", "candidate_note_pdf_page_index": 181}
        clusters = cluster_evidence([base | {"confidence": .8, "locator_method": "TOC"}, base | {"confidence": .96, "locator_method": "HEADING"}])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["evidence_count"], 2)

    def test_BULK_REVIEW_AUDIT_PASS(self):
        with tempfile.TemporaryDirectory() as td:
            registry = DiscoveryRegistry(MetadataRegistry(Path(td) / "metadata.db"))
            ids = [registry.save_machine({"company": "工银安盛", "display_name": "金融投资", "statement_item": f"项目{i}", "member_table": f"项目{i}", "evidence": {}})["discovery_id"] for i in range(2)]
            result = registry.bulk_adjudicate(ids, label="ACCEPTED", reason="批量审核", scope="REPORT_ONLY")
            self.assertEqual(len(result), 2)
            with registry.registry.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM discovery_adjudications").fetchone()[0], 2)

    def test_REVIEW_UI_PAGE_EVIDENCE_CONTRACT_PASS(self):
        plan = certified_plan(finance_occurrence())
        self.assertIn("statement_pdf_page_index", plan["anchor"])
        self.assertIn("candidate_note_pdf_page_index", plan["items"][1])

    def test_PDF_PAGE_VS_PRINTED_PAGE_PASS(self):
        anchor = build_statement_anchor_table(finance_occurrence())
        self.assertEqual(anchor["statement_pdf_page_index"], 76)
        self.assertEqual(anchor["statement_printed_page"], "70")

    def test_HIERARCHICAL_ML_SCOPE_LEVEL_PASS(self):
        query = {"normalized_company": "工银安盛", "filing_type": "ANNUAL_REPORT", "statement_type": "BALANCE_SHEET", "scope": "CONSOLIDATED", "display_name": "金融投资", "member_table": "债权投资"}
        ranked = hierarchical_backoff(query, [query | {"success_count": 1}, query | {"scope": "COMPANY", "success_count": 100}])
        self.assertEqual(ranked[0]["scope"], "CONSOLIDATED")

    def test_NO_FINANCIAL_VALUE_INVENTION_PASS(self):
        self.assertNotIn("value", certified_plan(finance_occurrence())["items"][1])

    def test_STATEMENT_NOTE_RECONCILIATION_ROUNDING_PASS(self):
        # Existing reconciliation stays evidence-only; this test protects the
        # plan from changing an extracted child value.
        occurrence = finance_occurrence()
        self.assertEqual(certified_plan(occurrence)["anchor"]["rows"][1]["value"], 900)

    def test_VERSION_SINGLE_SOURCE_V66_PASS(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('APP_VERSION = "v6.6"', (root / "version.py").read_text(encoding="utf-8"))
        self.assertIn("from version import APP_VERSION", (root / "run_gui.bat").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
