# Evidence Note: 中国人寿 2025年报

- **Filing ID**: CHINA_LIFE_2025_ANNUAL_REPORT
- **Canonical PDF**: 中国人寿2025年年度报告.pdf
- **SHA256**: `575a833fd7b83ad3568483273645236eddb751a92ab89f7e1c09105d92cedb27`
- **Page Anchor**: PDF Reader Page 89 (Zero-based Index 88), Printed Label "87"
- **Document Modality**: TEXT_DOMINANT_OR_HYBRID
- **Pattern Type**: IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED
- **Resolution Mode**: IMPLICIT_MEMBER_SET
- **Parent Row Label**: None (Raw: None)
- **Requires OCR**: False
- **Crop Reference**: `evidence/page_crops/china_life_2025_p89_crop.png`
- **Verification Summary**: 直接从 PDF 原图与文本层独立核对确认。
- **Supplementary Evidence**: PDF reader p168 原图与文本层确认“5. 债权投资（续）”公允价值层级表；2025/2024 两个纵向期间区块属于一张独立 `SUPPLEMENTARY_TABLE`、一个共享物理段，并在同页附注 6 前结束。
- **Supplementary Value Cells**: 两个期间各 4 行乘 4 列，共 32 个。

## 主表 SOURCE 完整性补证

- PDF reader p167-p169 的四张主表在分类明细后各自再次印有一个“合计”行；它们与表内较早出现的“合计”是不同物理行，必须按行序保留。
- 第二个真实“合计”在 2025/2024 两期分别为：交易性金融资产 `2,067,288 / 1,908,098`、债权投资 `173,992 / 196,754`、其他债权投资 `3,926,042 / 3,458,895`、其他权益工具投资 `317,876 / 171,817`。
- 八个金额槽由 SHA 绑定 PDF 原生文字、词坐标与页面原图 `evidence/page_crops/china_life_2025_p167_full.png`、`evidence/page_crops/china_life_2025_p168_full.png`、`evidence/page_crops/china_life_2025_p169_full.png` 逐项核验；未从 Capture/parser 输出反推。
