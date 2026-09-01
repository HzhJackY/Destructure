from pathlib import Path
import json, shutil, sys, os
import pandas as pd

PROJECT_ROOT=Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from asset_management import (
    ensure_asset_metadata,set_capture_batch,list_capture_assets,batch_summaries,
    invalidate_captures,reactivate_captures,trash_captures,restore_trashed_captures,
    dependency_impact,refresh_merge_dependency_statuses,LIFECYCLE_ACTIVE,LIFECYCLE_INVALIDATED,
)
from table_merge import load_capture_long
from launcher import pid_alive,is_our_streamlit

root=PROJECT_ROOT/'_v60_regression_runtime'
shutil.rmtree(root,ignore_errors=True)
cap_root=root/'table_captures';trash=cap_root/'_trash';merge_root=root/'table_merges'
cap_root.mkdir(parents=True);trash.mkdir();merge_root.mkdir()

def make_capture(name,batch,pdf='保险公司2024年度报告.pdf'):
    d=cap_root/name;d.mkdir()
    result={
        'pdf_name':pdf,'producer_version':'v6.0','table_query':'业务及管理费','note_number':'34',
        'start_page':1,'end_page':1,'boundary_status':'HARD_BOUNDARY_CONFIRMED',
        'header_dimension_status':'AUTO_CONFIRMED',
        'columns':[{'ordinal':0,'source_column_index':1,'year':'2024','scope':'本集团','restated':False}],
        'rows':[], 'stats':{'boundary_reason':'next_note_35','header_parser':'ABSOLUTE_YEAR_CLASSIC','capture_batch_id':batch},
    }
    (d/'table_capture_result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    pd.DataFrame([{
        'row_order':1,'row_type':'TOTAL','row_level':0,'parent_section':'','raw_item':'合计','normalized_item':'合计',
        'year':'2024','scope':'本集团','restated':False,'column_ordinal':0,'column_dimension_key':'2024|本集团|ORIGINAL',
        'value':100.0,'unit':'元'
    }]).to_csv(d/'table_raw_long.csv',index=False)
    meta=ensure_asset_metadata(d,batch_id=batch)
    set_capture_batch(d,batch)
    return d

c1=make_capture('cap_a','BATCH_BAD')
c2=make_capture('cap_b','BATCH_BAD')
c3=make_capture('cap_c','BATCH_GOOD')

# Merge depends on cap_a + cap_c
m=merge_root/'merge_1';m.mkdir()
(m/'merge_manifest.json').write_text(json.dumps({'table_id':'业务及管理费','sources':[{'capture_run_id':'cap_a'},{'capture_run_id':'cap_c'}]},ensure_ascii=False),encoding='utf-8')
(m/'merge_metadata.json').write_text(json.dumps({'run_id':'merge_1','dependency_status':'CURRENT'},ensure_ascii=False),encoding='utf-8')

records=list_capture_assets(cap_root)
assert len(records)==3
summ=batch_summaries(records)
bad=[x for x in summ if x['batch_id']=='BATCH_BAD'][0]
assert bad['capture_count']==2 and bad['active']==2
print('BATCH_GROUPING_PASS')

impact=dependency_impact({'cap_a','cap_b'},merge_root)
assert impact['dependent_merge_count']==1
print('DEPENDENCY_IMPACT_PASS')

out=invalidate_captures([c1,c2],reason_code='HEADER_TOPOLOGY_ERROR',note='4->8 duplicate columns',merge_root=merge_root)
assert len(out['invalidated'])==2 and out['stale_merges']==['merge_1']
meta1=json.loads((c1/'capture_metadata.json').read_text(encoding='utf-8'))
assert meta1['lifecycle_status']==LIFECYCLE_INVALIDATED
mmeta=json.loads((m/'merge_metadata.json').read_text(encoding='utf-8'))
assert mmeta['dependency_status']=='STALE_SOURCE_INVALIDATED' and 'cap_a' in mmeta['stale_capture_run_ids']
print('BULK_INVALIDATE_AND_STALE_MERGE_PASS')

# Invalidated capture is blocked from canonical merge load.
try:
    load_capture_long(c1,{'capture_run_id':'cap_a','company':'保险公司','document_year':'2024','pdf_name':'保险公司2024年度报告.pdf'},'业务及管理费')
    raise AssertionError('expected lifecycle gate')
except ValueError as exc:
    assert 'CAPTURE_LIFECYCLE_BLOCKED' in str(exc)
print('INVALIDATED_MERGE_GATE_PASS')

# Reactivate cap_a but cap_b irrelevant to merge; refresh should return merge current.
reactivate_captures([c1])
refresh_merge_dependency_statuses(cap_root,merge_root)
mmeta=json.loads((m/'merge_metadata.json').read_text(encoding='utf-8'))
assert mmeta['dependency_status']=='CURRENT'
print('REACTIVATE_DEPENDENCY_REFRESH_PASS')

# Trash/restore preserves prior invalidated state.
invalidate_captures([c2],reason_code='PARSER_ERROR',note='bad parser',merge_root=merge_root)
out=trash_captures([c2],trash,merge_root=merge_root)
trashed=Path(out['trashed'][0]);assert trashed.exists() and not c2.exists()
rest=restore_trashed_captures([trashed],cap_root)
restored=Path(rest['restored'][0]);assert restored.exists()
meta2=json.loads((restored/'capture_metadata.json').read_text(encoding='utf-8'))
assert meta2['lifecycle_status']==LIFECYCLE_INVALIDATED
print('TRASH_RESTORE_LIFECYCLE_PASS')

# Launcher safety: current test process is alive but not eligible as app Streamlit.
assert pid_alive(os.getpid())
assert not is_our_streamlit(os.getpid(),str(PROJECT_ROOT))
print('SINGLE_INSTANCE_PID_VALIDATION_PASS')

print('ALL_V60_ASSET_TESTS_PASS')
shutil.rmtree(root,ignore_errors=True)
