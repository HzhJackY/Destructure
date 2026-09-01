# Evidence Note: 中国人寿 2024年报

- **Filing ID**: CHINA_LIFE_2024_ANNUAL_REPORT
- **Canonical PDF**: 中国人寿2024年年度报告.pdf
- **SHA256**: `3cc6db9bbd9c3c754548b6be288bcebae7187e5264eba59025237f5aa8c667e0`
- **Page Anchor**: PDF Reader Page 96 (Zero-based Index 95), Printed Label "94"
- **Document Modality**: TEXT_DOMINANT_OR_HYBRID
- **Pattern Type**: IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED
- **Resolution Mode**: IMPLICIT_MEMBER_SET
- **Parent Row Label**: None (Raw: None)
- **Requires OCR**: False
- **Crop Reference**: `evidence/page_crops/china_life_2024_p96_crop.png`
- **Verification Summary**: 直接从 PDF 原图与文本层独立核对确认。
- **Supplementary Evidence**: PDF reader p186 原图与文本层确认“7. 债权投资（续）”公允价值层级表；分类轴重置形成独立 `SUPPLEMENTARY_TABLE`，并在同页附注 8 开始前自然结束。
- **Supplementary Value Cells**: 2024 年 4 行乘 4 列，共 16 个。
- **Identity Correction**: Canonical PDF 的章节标题为“十一、合并财务报表项目附注”，segment registry 已由错误的“十、”修正为“十一、”。

## 主表 SOURCE 完整性补证

- PDF reader p185-p187 的四张主表在分类明细后各自再次印有一个“合计”行；这些行与表内较早出现的“合计”具有不同的物理行序，不能因 raw label 重复而折叠。
- 第二个真实“合计”分别为：交易性金融资产 `1,908,098`、债权投资 `196,754`、其他债权投资 `3,458,895`、其他权益工具投资 `171,817`。
- 四个金额槽由 SHA 绑定 PDF 原生文字、词坐标与页面原图 `evidence/page_crops/china_life_2024_p185_full.png`、`evidence/page_crops/china_life_2024_p186_full.png`、`evidence/page_crops/china_life_2024_p187_full.png` 逐项核验；未从 Capture/parser 输出反推。
