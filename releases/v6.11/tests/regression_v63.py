#!/usr/bin/env python3
"""v6.3 contracts: selection, navigation, family merge, output and notes."""
from __future__ import annotations
import shutil, sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from data_home import ensure_data_home
from metadata_registry import MetadataRegistry
from pdf_selection_workspace import filter_pdfs, selection_summary
from statement_note_navigation import TextIndexRecord, locate_primary_statements, build_statement_note_graph, reconcile_statement_note
from family_merge_v63 import enrich_family_identity, family_merge_long, research_wide
from table_notes import note_record, persist_note

runtime=ROOT/'_v63_regression_runtime'; shutil.rmtree(runtime,ignore_errors=True); runtime.mkdir()
paths=ensure_data_home(runtime,ROOT/'metric_aliases.json')

pdfs=[paths['uploads']/x for x in ['工银安盛_2024年报.pdf','中国平安_2023年报.pdf','中国平安_2024英文版.pdf']]
for p in pdfs:p.write_bytes(b'%PDF-1.4\n')
matched=filter_pdfs(pdfs,include='2024',exclude='英文版')
assert matched==[pdfs[0]]
assert selection_summary([pdfs[0],pdfs[1]]).pdf_count==2
print('PDF_SELECTION_WORKSPACE_V2_PASS')

index=[
 TextIndexRecord(10,'合并资产负债表\n债权投资 附注 10 1,270,569\n其他债权投资 附注 11 3,231,435','合并资产负债表','',()),
 TextIndexRecord(210,'八、财务报表项目注释\n10. 债权投资\n国债','八、财务报表项目注释','八',('10',)),
 TextIndexRecord(215,'11. 其他债权投资\n金融债','11. 其他债权投资','八',('11',)),]
assert locate_primary_statements(index)['BALANCE_SHEET']==[10]
edges=build_statement_note_graph(index)
assert {(x.member_table,x.note_page) for x in edges}=={('债权投资',210),('其他债权投资',215)}
assert reconcile_statement_note(100.0,100.0)['status']=='PASS_EXACT'
assert reconcile_statement_note(1000000.0,1000000.5,unit='元')['status']=='PASS_WITH_ROUNDING'
assert reconcile_statement_note(100,120,unit='元')['status']=='WARNING_STATEMENT_NOTE_MISMATCH'
print('STATEMENT_NOTE_GRAPH_AND_ROUNDING_RECONCILIATION_PASS')

base=pd.DataFrame([{'company':'工银安盛','report_year':'2025','data_year':'2025','scope':'本集团','restated':False,'period_type':'ANNUAL','unit':'万元','normalized_item':'金融债','item':'金融债','row_type':'DETAIL','row_path':'按类别 / 金融债','value':10}])
debt=enrich_family_identity(base,table_family='金融投资',member_table='债权投资',note_reference='10')
other=enrich_family_identity(base.assign(value=20),table_family='金融投资',member_table='其他债权投资',note_reference='11')
long,conflicts=family_merge_long([debt,other])
assert len(long)==2 and conflicts.empty and long.row_path.nunique()==2
wide,columns=research_wide(long)
assert len(columns)==1 and 'canonical_key' not in wide.columns and 'order_source' not in wide.columns
_,hard=family_merge_long([debt,debt.assign(value=99)])
assert set(hard.conflict_status)=={'VALUE_CONFLICT'}
print('FAMILY_ROW_COLUMN_UNION_MEMBER_IDENTITY_AND_WIDE_CONTRACT_PASS')

registry=MetadataRegistry(paths['metadata_db']); registry.initialize_schema()
note=note_record('注：上述余额不包括应计利息。',table_family='金融投资',member_table='债权投资',page=210,bbox=[1,2,3,4])
note['capture_id']=None  # independent table-level note is allowed before a Capture exists
persist_note(registry,note)
with registry.connect() as conn: saved=conn.execute('SELECT raw_text,note_scope,classification FROM table_notes WHERE note_id=?',(note['note_id'],)).fetchone()
assert saved['raw_text']==note['raw_text'] and saved['note_scope']=='TABLE'
print('TABLE_NOTES_IMMUTABLE_EVIDENCE_PASS')
print('ALL_V63_REGRESSION_TESTS_PASS')
