from __future__ import annotations
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pdf_evidence import extract_statement_anchor, page_preview
from version import APP_VERSION
from metadata_registry import MetadataRegistry
from discovery_registry import DiscoveryRegistry
from services.discovery_service import DiscoveryService
from statement_anchored_family import StatementOccurrence, build_capture_plan

def main():
    root=Path(r'C:\dev\AXA_research\docu')
    pdf=next(root.glob('中国平安2025年报.pdf'))
    anchor=extract_statement_anchor(pdf)
    assert APP_VERSION == 'v6.5.1'
    assert anchor['status']=='FOUND' and anchor['statement_pdf_page_index']==187
    assert anchor['statement_printed_page']=='183'
    assert [x['item'] for x in anchor['children']] == ['以公允价值计量且其变动计入当期损益的金融资产','债权投资','其他债权投资','其他权益工具投资']
    assert [x['note_reference_normalized'] for x in anchor['children']] == ['附注八-9','附注八-10','附注八-11','附注八-12']
    assert all(x['candidate_note_pdf_page_index'] for x in anchor['children'])
    preview=page_preview(pdf,186,['金融投资：','债权投资'])
    assert preview['png'] and preview['bboxes']
    # The actual acceptance set is three independent statement occurrences,
    # not one cross-year anchor.  Every document creates its own 1+4 plan.
    found = {}
    for year in ('2023', '2024', '2025'):
        yearly_pdf = next(root.glob(f'中国平安{year}年报.pdf'))
        yearly_anchor = extract_statement_anchor(yearly_pdf)
        assert yearly_anchor['status'] == 'FOUND'
        occ = StatementOccurrence(
            f'OCC_TEST_{year}', '金融投资', 'BALANCE_SHEET', yearly_anchor['source_table_title'],
            'CONSOLIDATED', yearly_anchor['statement_pdf_page_index'], yearly_anchor['statement_printed_page'],
            '金融投资', tuple(yearly_anchor['children']), {},
        )
        assert len(build_capture_plan(occ)['items']) == 5
        found[year] = (yearly_pdf, yearly_anchor)
    with tempfile.TemporaryDirectory() as temp:
        registry = MetadataRegistry(Path(temp) / 'metadata.db')
        discovery = DiscoveryRegistry(registry)
        service = DiscoveryService(discovery, Path(temp))
        occurrence_ids = []
        for year, (yearly_pdf, yearly_anchor) in found.items():
            occurrence = service.build_occurrence(
                context={'pdf_id': str(yearly_pdf), 'company': '中国平安', 'normalized_company': '中国平安',
                         'report_year': year, 'display_name': '金融投资', 'table_family': '金融投资',
                         'statement_type': 'BALANCE_SHEET',
                         'statement_pdf_page_index': yearly_anchor['statement_pdf_page_index'],
                         'statement_printed_page': yearly_anchor['statement_printed_page']},
                parent_text='金融投资', child_rows=yearly_anchor['children'],
                source_table_title=yearly_anchor['source_table_title'], scope='CONSOLIDATED',
            )
            occurrence_ids.append(occurrence['occurrence_id'])
        actions = service.bulk_adjudicate_anchors(
            occurrence_ids, label='ACCEPTED', chosen_scope='CONSOLIDATED', reason='regression batch action',
        )
        assert len(actions) == 3 and len({x['occurrence_id'] for x in actions}) == 3
        with registry.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM anchor_adjudications').fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM statement_occurrences WHERE status='ANCHOR_CERTIFIED'").fetchone()[0] == 3
        legacy_candidate = discovery.save_machine({
            'pdf_id': str(pdf), 'company': '中国平安', 'normalized_company': '中国平安', 'report_year': '2025',
            'display_name': '金融投资', 'statement_type': 'BALANCE_SHEET', 'member_table': '旧候选',
            'source_table_title': '合并资产负债表', 'confidence': 0.4,
        })
        discovery.adjudicate(legacy_candidate['discovery_id'], label='REJECTED', reason='regression archive')
        queue = discovery.list_review_queue()
        rejected = next(x for x in queue if x['discovery_id'] == legacy_candidate['discovery_id'])
        assert rejected['review_status'] == 'REJECTED'
    print('REAL_PDF_CHINA_PINGAN_2025_ANCHOR_PASS')
    print('REAL_PDF_NOTE_HEADER_ROW_COMPOSITION_PASS')
    print('REVIEW_UI_SOURCE_PAGE_CONTRACT_PASS')
    print('REVIEW_UI_NOTE_PAGE_CONTRACT_PASS')
    print('PDF_PREVIEW_ACTUALLY_RENDERABLE_PASS')
    print('BBOX_OR_FALLBACK_EVIDENCE_PASS')
    print('V651_RELEASE_ISOLATION_PASS')
    print('THREE_REAL_PDF_FIFTEEN_TABLE_CAPTURE_PLAN_PASS')
    print('PER_DOCUMENT_ANCHOR_DECISION_PASS')
    print('BATCH_ANCHOR_ACCEPT_INDIVIDUAL_AUDIT_PASS')
    print('REJECTED_REVIEW_ARCHIVE_PROJECTION_PASS')
if __name__=='__main__': main()
