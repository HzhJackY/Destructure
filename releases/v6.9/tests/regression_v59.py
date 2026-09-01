
from pathlib import Path
import shutil, json, sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import fitz
import pandas as pd

from spatial_table_capture import (
    _classic_absolute_year_words,
    _period_words_generalized,
    _candidate_arbitration_metrics,
)
from table_capture import (
    capture_named_table, write_capture_artifacts,
    TableColumn, TableCell, TableRow, TableCaptureResult,
)
from column_topology_review import apply_column_topology_review
from table_merge import create_merge_project

root=PROJECT_ROOT/"_v59_regression_runtime"
shutil.rmtree(root,ignore_errors=True);root.mkdir()

# ------------------------------------------------------------------
# CASE A: fragment-level 2024 + 年度 must be ONE header, not two.
# ------------------------------------------------------------------
def w(x0,x1,text,y=100):
    return {"x0":x0,"x1":x1,"xc":(x0+x1)/2,"y0":y,"y1":y+10,"yc":y+5,"text":text}
line={"words":[
    w(300,330,"2025"),w(331,355,"年度"),
    w(440,470,"2024"),w(471,495,"年度"),
    w(620,650,"2025"),w(651,675,"年度"),
    w(760,790,"2024"),w(791,815,"年度"),
],"text":"2025 年度 2024 年度 2025 年度 2024 年度","x0":300,"x1":815,"y0":100,"y1":110,"yc":105}
classic=_classic_absolute_year_words(line)
general=_period_words_generalized(line)
print("FRAGMENT CLASSIC",[(x["year"],x["xc"],x["token"]) for x in classic])
print("FRAGMENT GENERAL",[(x["year"],x["xc"],x["token"]) for x in general])
assert len(classic)==4
assert len(general)==4
print("PERIOD_MAXIMAL_SPAN_DEDUP_PASS")

# ------------------------------------------------------------------
# CASE B: standard absolute-year + restated: 4 real cols, never 8.
# ------------------------------------------------------------------
pdf=root/"标准保险2024年度报告.pdf"
doc=fitz.open();p=doc.new_page(width=1000,height=1000)
p.insert_text((50,60),"34. 业务及管理费",fontname="china-s",fontsize=14)
p.insert_text((390,110),"本集团",fontname="china-s",fontsize=12)
p.insert_text((730,110),"本公司",fontname="china-s",fontsize=12)
xs=[330,500,670,840]
for x,t in zip(xs,["2024 年度","2023 年度（已重述）","2024 年度","2023 年度（已重述）"]):
    p.insert_text((x,145),t,fontname="china-s",fontsize=10)
y=210
for n in range(10):
    p.insert_text((70,y),f"费用项目{n}",fontname="china-s",fontsize=10)
    for x,v in zip(xs,[100+n,90+n,80+n,70+n]):
        p.insert_text((x,y),f"{v*1000000:,}",fontsize=10)
    y+=30
p.insert_text((50,650),"35. 下一附注",fontname="china-s",fontsize=14)
doc.save(pdf);doc.close()

r=capture_named_table(pdf,"业务及管理费",header_parser_mode="AUTO")
print("ABS parser",r.stats["header_parser"])
print("ABS cols",[(c.year,c.scope,c.restated) for c in r.columns])
assert r.stats["header_parser"]=="ABSOLUTE_YEAR_CLASSIC"
assert len(r.columns)==4
assert [(c.year,c.scope,c.restated) for c in r.columns]==[
    ("2024","本集团",False),("2023","本集团",True),
    ("2024","本公司",False),("2023","本公司",True),
]
arb=r.stats["header_arbitration"]
assert arb["candidates"]["ABSOLUTE_YEAR_CLASSIC"]["numeric_cluster_count"]==4
assert arb["candidates"]["ABSOLUTE_YEAR_CLASSIC"]["leaf_count"]==4
print("STANDARD_4COL_NOT_8_PASS")

# Explicit generalized still available and should not destroy standard table.
rg=capture_named_table(pdf,"业务及管理费",header_parser_mode="GENERALIZED_PERIOD_V57")
assert len(rg.columns)==4
print("GENERALIZED_STANDARD_COMPAT_PASS")

# ------------------------------------------------------------------
# CASE C: v5.7 relative-period + wrapped rows + formula remains supported.
# ------------------------------------------------------------------
pdf2=root/"相对期间保险2025年度报告.pdf"
doc=fitz.open()
p=doc.new_page(width=1000,height=1000)
p.insert_text((50,80),"目录",fontname="china-s",fontsize=14)
p.insert_text((70,140),"34. 业务及管理费 ........ 48",fontname="china-s",fontsize=11)

p=doc.new_page(width=1000,height=1200)
p.insert_text((50,60),"34. 业务及管理费",fontname="china-s",fontsize=14)
p.insert_text((390,110),"本集团",fontname="china-s",fontsize=12)
p.insert_text((730,110),"本公司",fontname="china-s",fontsize=12)
for x,t in zip(xs,["本年累计数","上年累计数","本年累计数","上年累计数"]):
    p.insert_text((x,145),t,fontname="china-s",fontsize=10)
    p.insert_text((x+20,175),"人民币元",fontname="china-s",fontsize=9)
y=230
rows=[
("工资和福利费",["1,169,648,937","1,100,025,060","1,063,416,253","1,000,374,052"],70),
("其他",["37,906,512","37,047,850","35,521,028","34,827,366"],70),
("小计",["1,207,555,449","1,137,072,910","1,098,937,281","1,035,201,418"],70),
("减:",["","","",""],70),
("当期发生的保费获取",["","","",""],70),
("现金流",["100,000,000","90,000,000","80,000,000","70,000,000"],110),
("当期发生的其他保险",["","","",""],70),
("履约现金流",["200,000,000","190,000,000","180,000,000","170,000,000"],110),
("合计",["907,555,449","857,072,910","838,937,281","795,201,418"],70),
]
for item,vals,xlab in rows:
    p.insert_text((xlab,y),item,fontname="china-s",fontsize=10)
    for x,val in zip(xs,vals):
        if val:p.insert_text((x,y),val,fontsize=9)
    y+=34
p.insert_text((50,700),"35. 下一附注",fontname="china-s",fontsize=14)
doc.save(pdf2);doc.close()

rr=capture_named_table(pdf2,"业务及管理费",note_number=None,header_parser_mode="AUTO")
print("REL parser",rr.stats["header_parser"])
assert rr.start_page==2
assert rr.stats["header_parser"]=="GENERALIZED_PERIOD_V57"
assert len(rr.columns)==4
items=[x.raw_item for x in rr.rows]
assert "当期发生的保费获取现金流" in items
assert "当期发生的其他保险履约现金流" in items
print("V57_RELATIVE_WRAPPED_FEATURES_PASS")

cap_rel=root/"cap_rel";cap_rel.mkdir()
write_capture_artifacts(cap_rel,rr)
audit=pd.read_csv(cap_rel/"table_reconciliation_audit.csv")
final=audit[audit.target_item=="合计"]
assert not final.empty
assert set(final.pattern)=={"BASE_MINUS_COMPONENTS"}
assert set(final.status)=={"PASS_EXACT"}
print("V57_FORMULA_RECONCILIATION_PASS")

# ------------------------------------------------------------------
# CASE D: independent referee rejects 8-header vs 4 numeric clusters.
# ------------------------------------------------------------------
# Reuse real body lines through low-level page extraction indirectly from arbitration:
abs_general=arb["candidates"]["GENERALIZED_PERIOD_V57"]
assert abs_general["leaf_count"]==4
# Synthetic metric object representing old 8-anchor failure must be hard rejected.
# The invariant is tested by the actual arbiter via a manual fake header over numeric lines.
from spatial_table_capture import _page_lines, locate_table_roi, _lines_in_roi
doc=fitz.open(str(pdf))
roi=locate_table_roi(pdf,"业务及管理费")
lines=_lines_in_roi(doc,roi,roi["start_page"])
fake={
 "parser":"GENERALIZED_PERIOD_V57","line_index":0,"line":lines[0],
 "anchors":[320,345,490,515,660,685,830,855],
 "years":["2024","2024","2023","2023","2024","2024","2023","2023"],
 "period_labels":["2024","2024","2023","2023","2024","2024","2023","2023"],
 "period_kinds":["ABSOLUTE_YEAR"]*8,
 "header_y0":140,"header_y1":160,
}
m=_candidate_arbitration_metrics(lines,fake,1000)
print("FAKE8",m["hard_failures"],m["numeric_cluster_count"])
assert "HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS" in m["hard_failures"]
assert m["numeric_cluster_count"]==4
doc.close()
print("NUMERIC_CLUSTER_REFEREE_PASS")

# ------------------------------------------------------------------
# CASE E: safe manual topology drop can repair a duplicated machine topology.
# ------------------------------------------------------------------
cap=root/"dup_capture";cap.mkdir()
cols=[]
for i,(year,scope,restated) in enumerate([
    ("2024","本集团",False),("2024","本集团",False),
    ("2023","本集团",True),("2023","本集团",True),
    ("2024","本公司",False),("2024","本公司",False),
    ("2023","本公司",True),("2023","本公司",True),
]):
    cols.append(TableColumn(i,i+1,f"{scope}|{year}",year,scope,restated,year))
cells=[]
for i,val in enumerate([100,100,90,90,80,80,70,70]):
    cells.append(TableCell(i,i+1,str(val),float(val),"元",float(val)))
dup=TableCaptureResult(
    pdf_name="dup.pdf",pdf_sha256="dup",table_query="业务及管理费",note_number="34",
    located_title="34业务及管理费",start_page=1,end_page=1,pages=[1],unit="元",
    columns=cols,
    rows=[TableRow(1,1,"b","test","合计","合计",None,"UNMAPPED","TOTAL",0,None,cells,None)],
    warnings=[],stats={"boundary_reason":"next_note_35","header_arbitration":{}}
)
write_capture_artifacts(cap,dup)
out=apply_column_topology_review(cap,[
    {"ordinal":i,"action":("KEEP" if i in {0,2,4,6} else "DROP_DUPLICATE")}
    for i in range(8)
])
assert out["active_ordinals"]==[0,2,4,6]
official=pd.read_csv(cap/"table_raw_long.csv")
machine=pd.read_csv(cap/"machine_capture_full_long.csv")
assert official["column_ordinal"].nunique()==4
assert machine["column_ordinal"].nunique()==8
print("SAFE_TOPOLOGY_DROP_PASS")

# ------------------------------------------------------------------
# CASE F: v5.8 absolute year resolution remains intact.
# ------------------------------------------------------------------
merge=root/"merge_rel"
create_merge_project(
    [cap_rel],
    [{"capture_run_id":"cap_rel","company":"测试保险","document_year":"2025"}],
    merge,"业务及管理费",root/"tax.json",reference_capture_run_id="cap_rel"
)
raw=pd.read_csv(merge/"merge_raw_long.csv")
numeric=raw[raw.value.notna()]
assert set(numeric.year.astype(int))=={2024,2025}
assert {"本年累计数","上年累计数"}<=set(numeric.source_period_label.dropna())
print("V58_ABSOLUTE_YEAR_RESOLUTION_PASS")

# Candidate audit artifacts exist.
cap_abs=root/"cap_abs";cap_abs.mkdir()
write_capture_artifacts(cap_abs,r)
assert (cap_abs/"machine_header_arbitration.json").exists()
cand=pd.read_csv(cap_abs/"header_parser_candidates.csv")
assert {"ABSOLUTE_YEAR_CLASSIC","GENERALIZED_PERIOD_V57"}<=set(cand.parser)
print("ARBITRATION_AUDIT_ARTIFACTS_PASS")

print("ALL_V59_REGRESSION_CORPUS_PASS")
shutil.rmtree(root)
