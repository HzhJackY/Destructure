import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

# China Re 2023
doc23 = fitz.open(docu / "中国再保2023年年度报告.pdf")
print("=== 中国再保 2023 Balance Sheet P155 ===")
print(doc23[154].get_text()[:1500])
print("=== 中国再保 2023 MD&A P51 ===")
print(doc23[50].get_text()[:2000])

# China Re 2024
doc24 = fitz.open(docu / "中国再保2024年年度报告.pdf")
print("=== 中国再保 2024 Balance Sheet P155 ===")
print(doc24[154].get_text()[:1500])
print("=== 中国再保 2024 MD&A P51 ===")
print(doc24[50].get_text()[:2000])

# China Re 2025
doc25 = fitz.open(docu / "中国再保2025年年度报告.pdf")
print("=== 中国再保 2025 Balance Sheet P154 ===")
print(doc25[153].get_text()[:1500])
print("=== 中国再保 2025 MD&A P49 ===")
print(doc25[48].get_text()[:2000])
