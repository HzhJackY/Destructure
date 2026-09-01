# 友邦保险 (2024) Golden 数据审计与视觉核实依据

## 1. 物理页码与指纹
- **官方 PDF 文件名**: `友邦保险2024年报.pdf`
- **SHA256**: `50ebe59813386119ba1026a6a42fabc00a86470e970659fa3cf467f1d376a588`
- **总页数**: 371
- **合并资产负债表物理页**: P154 (印刷页: P152)
- **投资组合 MD&A 物理页**: P45

## 2. 币种单位核准
- **资产负债表与附注单位**: `USD_MILLION`
- **MD&A 投资组合单位**: `USD_MILLION`

## 3. 视觉截图证据索引
- 资产负债表截图: `golden_corpus/v1.1.0/evidence/crops/aia/2024/aia_2024_balance_sheet_p154.png`
- MD&A 投资组合截图: `golden_corpus/v1.1.0/evidence/crops/aia/2024/aia_2024_mda_category_p45.png`
- 附注子表截图: `golden_corpus/v1.1.0/evidence/crops/aia/2024/`

## 4. 审核结论
- **金融投资主表与附注 Primary Child Table**: 经 300 DPI 实页截图比对与双重校验，确认金额、附注索引、单位 100% 吻合。
- **MD&A 投资组合**: 纠正单位口径与总额，确认品种分类与计量分类占比 100% 吻合。
