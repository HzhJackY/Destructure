import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
out = root / "_smoke_result.json"
audit = root / "_smoke_audit.jsonl"
for p in (out, audit):
    if p.exists():
        p.unlink()

cmd = [
    sys.executable, str(root / "financial_metric_resolver.py"),
    "--input", str(root / "sample_financial.xlsx"),
    "--metrics", "营业收入", "净利润", "归母净利润", "货币资金", "保险合同负债", "收入",
    "--rules", str(root / "metric_aliases.json"),
    "--output", str(out),
    "--audit", str(audit),
]
subprocess.run(cmd, check=True)
rows = json.loads(out.read_text(encoding="utf-8"))
by_metric = {r["metric_input"]: r for r in rows}
assert by_metric["营业收入"]["selected"]["label"] == "一、营业总收入"
assert by_metric["净利润"]["selected"]["label"] == "四、净利润"
assert "归属于母公司股东" in by_metric["归母净利润"]["selected"]["label"]
assert by_metric["货币资金"]["selected"]["values"][0]["header_context"] == "2025-12-31"
assert by_metric["保险合同负债"]["selected"]["values"][0]["raw_value"] == 2440000
assert by_metric["收入"]["status"] == "UNRESOLVED"  # 故意拒绝把过于宽泛的“收入”自动等同“营业收入”
print("SMOKE TEST PASS")
