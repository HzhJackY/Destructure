import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

# 1. Sunshine Insurance 2023
doc23 = fitz.open(docu / "阳光保险2023年度报告.pdf")
print("=== 阳光保险 2023 Balance Sheet P160 ===")
print(doc23[159].get_text())
print("=== 阳光保险 2023 MD&A P51 ===")
print(doc23[50].get_text())
print("=== 阳光保险 2023 MD&A P53 ===")
print(doc23[52].get_text())

# 2. Sunshine Insurance 2024
doc24 = fitz.open(docu / "阳光保险2024年度报告.pdf")
print("=== 阳光保险 2024 Balance Sheet P160 ===")
print(doc24[159].get_text())
print("=== 阳光保险 2024 MD&A P49 ===")
print(doc24[48].get_text())
print("=== 阳光保险 2024 MD&A P50 ===")
print(doc24[49].get_text())

# 3. Sunshine Insurance 2025
doc25 = fitz.open(docu / "阳光保险2025年度报告.pdf")
print("=== 阳光保险 2025 Balance Sheet P147 ===")
print(doc25[146].get_text())
print("=== 阳光保险 2025 MD&A P44 ===")
print(doc25[43].get_text())
print("=== 阳光保险 2025 MD&A P46 ===")
print(doc25[45].get_text())
