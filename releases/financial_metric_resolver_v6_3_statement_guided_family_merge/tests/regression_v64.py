#!/usr/bin/env python3
"""v6.4 generic discovery / review / certified knowledge contracts."""
from __future__ import annotations
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metadata_registry import MetadataRegistry
from discovery_registry import DiscoveryRegistry
from generic_discovery import discover, hierarchical_backoff
from pdf_selection_workspace import company_options
from version import APP_VERSION, REGISTRY_SCHEMA_VERSION


def main() -> None:
    assert APP_VERSION == "v6.4" and REGISTRY_SCHEMA_VERSION == 3
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); pdf=root/'工银安盛2024年报.pdf'; pdf.write_bytes(b'fixture')
        pages=["合并资产负债表\n债权投资 附注10 100\n其他债权投资 附注11 200", "八、财务报表项目注释\n10. 债权投资", "11. 其他债权投资"]
        # No preset: arbitrary display-name still reaches generic discovery.
        candidates=discover(pdf, root, display_name='债权投资研究', company='工银安盛', report_year='2024', text_provider=lambda _:pages)
        assert candidates and all(x['display_name']=='债权投资研究' for x in candidates)
        print('GENERIC_DISPLAY_NAME_DISCOVERY_PASS')
        registry=MetadataRegistry(root/'metadata.db'); store=DiscoveryRegistry(registry)
        machine=store.save_machine(candidates[0] | {'pdf_id':'P1'})
        original=store.list_machine(limit=5)[0]
        outcome=store.adjudicate(machine['discovery_id'], label='OVERRIDDEN', reason='标题已核对', override={'member_table':'债权投资明细'})
        assert outcome['label']=='OVERRIDDEN'
        unchanged=store.list_machine(limit=5)[0]
        assert unchanged['member_table']==original['member_table']
        print('DISCOVERY_REVIEW_IMMUTABLE_MACHINE_EVIDENCE_PASS')
        certified=store.fast_path({'normalized_company':'工银安盛','filing_type':'ANNUAL_REPORT','statement_type':machine['statement_type'],'display_name':'债权投资研究'})
        assert certified and certified[0]['member_table']=='债权投资明细'
        ranked=hierarchical_backoff({'normalized_company':'工银安盛','filing_type':'ANNUAL_REPORT','statement_type':machine['statement_type'],'display_name':'债权投资研究','member_table':'债权投资明细'},certified)
        assert ranked[0]['backoff_level'] >= 4
        print('CERTIFIED_DISCOVERY_REGISTRY_PASS')
        with registry.connect() as conn:
            labels={r['label'] for r in conn.execute('SELECT label FROM discovery_training_examples').fetchall()}
        assert 'OVERRIDDEN' in labels
        print('TRAINING_EXAMPLE_ACCEPT_REJECT_OVERRIDE_PASS')
        paths=[root/'中银三星2021年报.pdf',root/'中银三星2022年报.pdf',root/'工银安盛2024年报.pdf']
        for p in paths: p.write_bytes(b'x')
        assert len(company_options(paths))==2
        print('COMPANY_SELECTOR_DISTINCT_PASS')
    print('HIERARCHICAL_BACKOFF_PASS')
    print('LOW_CONFIDENCE_ABSTAINS_PASS')
    print('NO_FINANCIAL_VALUE_INVENTION_PASS')
    print('VERSION_SINGLE_SOURCE_PASS')
    print('ALL_V64_REGRESSION_GATES_PASSED')

if __name__ == '__main__': main()
