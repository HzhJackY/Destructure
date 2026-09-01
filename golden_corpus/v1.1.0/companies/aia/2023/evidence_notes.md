# 友邦保险 (2023) Golden 数据审计与视觉核实依据

## 1. 物理页码与指纹
- **官方 PDF 文件名**: `友邦保险2023年报.pdf`
- **SHA256**: `24d40562aff2a09911845532bca4be841d484ce3ef2c1366b68c183cf6718779`
- **总页数**: 376
- **合并资产负债表物理页**: P160 (印刷页: P158)
- **投资组合 MD&A 物理页**: P42

## 2. 币种单位核准
- **资产负债表与附注单位**: `USD_MILLION`
- **MD&A 投资组合单位**: `USD_MILLION`

## 3. 视觉截图证据索引
- 资产负债表截图: `golden_corpus/v1.1.0/evidence/crops/aia/2023/aia_2023_balance_sheet_p160.png`
- MD&A 投资组合截图: `golden_corpus/v1.1.0/evidence/crops/aia/2023/aia_2023_mda_category_p42.png`
- 附注子表截图: `golden_corpus/v1.1.0/evidence/crops/aia/2023/`

## 4. 审核结论
- **金融投资主表与附注 Primary Child Table**: 经 300 DPI 实页截图比对与双重校验，确认金额、附注索引、单位 100% 吻合。
- **MD&A 投资组合**: 纠正单位口径与总额，确认品种分类与计量分类占比 100% 吻合。
