# 中国再保 (2023) Golden 数据审计与视觉核实依据

## 1. 物理页码与指纹
- **官方 PDF 文件名**: `中国再保2023年年度报告.pdf`
- **SHA256**: `cad91861bded6b02ace912405f50f03524f4eb0a1e05fbe6cb4b04ac5ba32d3c`
- **总页数**: 390
- **合并资产负债表物理页**: P155 (印刷页: P154)
- **投资组合 MD&A 物理页**: P51

## 2. 币种单位核准
- **资产负债表与附注单位**: `RMB_THOUSAND`
- **MD&A 投资组合单位**: `RMB_MILLION`

## 3. 视觉截图证据索引
- 资产负债表截图: `golden_corpus/v1.1.0/evidence/crops/china_re/2023/china_re_2023_balance_sheet_p155.png`
- MD&A 投资组合截图: `golden_corpus/v1.1.0/evidence/crops/china_re/2023/china_re_2023_mda_category_p51.png`
- 附注子表截图: `golden_corpus/v1.1.0/evidence/crops/china_re/2023/`

## 4. 审核结论
- **金融投资主表与附注 Primary Child Table**: 经 300 DPI 实页截图比对与双重校验，确认金额、附注索引、单位 100% 吻合。
- **MD&A 投资组合**: 纠正单位口径与总额，确认品种分类与计量分类占比 100% 吻合。
