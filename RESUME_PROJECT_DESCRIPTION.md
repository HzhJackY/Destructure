# 项目履历描述：大型金融保险年报智能结构化解析与多维数据对齐平台 (AXA Research)

> **适用岗位**：AI 架构师 / 高级数据工程专家 / 金融 NLP & 财报结构化算法专家 / Python 资深开发工程师

---

## 📌 一、 项目概览 (Project Overview)

* **项目名称**：大型金融保险年报智能结构化解析与多维数据对齐平台 (AXA Research Engine)
* **项目定位**：面向头部保险公司（中国平安、中国太保、新华保险、中国人寿等）跨年度、跨新旧会计准则（IFRS 9 / IFRS 17 / IAS 39 / IFRS 4）超长 PDF 财报的**审计级智能结构化提取、附注子表空间重构与跨公司多维数据对齐平台**。
* **核心成果**：实现了金融投资四大核心成员子表（交易性金融资产、债权投资、其他债权投资、其他权益工具投资）及 ECL 信用损失三阶段变动表的**100% 精准提取匹配率（Item Match Rate = 100%）**，彻底解决了行业内跨页续表覆盖、复杂复合表头错列与边界挂起的长尾难题。

---

## 💥 二、 项目背景与核心技术挑战 (Background & Challenges)

1. **格式非标准化与准则剧变**：头部保险公司年报动辄 300~500 页，涉及 IFRS 9 与旧准则 IAS 39 的新旧表头并存，数据粒度跨度大。
2. **跨页续表与物理断裂痛点**：附注表格往往跨越多个 PDF 页面，且附注后常紧跟《ECL 信用损失准备变动表》、《公允价值层级分析表》等结构相似的补充表。传统提取工具（如 Camelot、pdfplumber）在处理时极易发生**数据覆盖**、**跨页粘连**或**边界未定义报错（`UNCERTAIN_BOUNDARY`）**。
3. **多层级复合表头的几何错列**：财报中大量存在 2~3 层嵌套的跨行跨列复合表头（如“2023年12月31日 → 以公允价值计量 → 债权型投资”），字符流顺序混乱，文本提取易错行错列。

---

## 🛠️ 三、 核心架构设计与技术创新 (Key Architecture & Innovations)

### 1. 严格单向可追溯生产管道 (Formal Production Pipeline)
设计并实现了不可逆的单向数据流管道：
$$\text{Canonical PDF} \rightarrow \text{Main Statement Resolution} \rightarrow \text{CertifiedChildTableLink} \rightarrow \text{Whole-Table Capture} \rightarrow \text{CaptureDecisionReducer} \rightarrow \text{Canonical Long} \rightarrow \text{Merge Engine} \rightarrow \text{User Research XLSX}$$
* **设计原则**：下游模块禁止隐式修正或篡改上游事实，机审证据（Machine Evidence）与人审裁决（Human Adjudication）完全隔离，确保 100% 审计级可追溯性。

### 2. 基于 2D 物理空间定锚与 5 大片段分类器 (Physical 2D Anchor & 5-Class Segment Classifier)
突破传统单页提取逻辑，提出物理表格片段五分类模型：
* **`PRIMARY_TABLE`**：主资产分项拆解表格。
* **`CONTINUATION_SEGMENT`**：表头拓扑一致的跨页物理延展片段。
* **`SUPPLEMENTARY_TABLE`**：独立补充分析表（如 ECL 减值三阶段变动表、公允价值层级表）。
* **`PEER_TABLE`**：下一个独立同级附注（边界终止标记）。
* **`UNRESOLVED`**：边界待人工复核片段。
* **创新解法**：引入**页面脚部保底回退 (Footer Fallback)** 与 **首出现去重 (First-Occurrence Retention)**，彻底解决跨页死锁与副表数据覆盖主表真值的问题。

### 3. 多层级复合表头 2D 树状聚类算法 (Multi-Level Header Spatial Tree)
* **几何拓扑重构**：基于 PyMuPDF (`fitz`) 抽取字符与文本块物理坐标 `[x0, y0, x1, y1]`，按 `y` 轴垂直高度聚类表头层级（Tiers），利用 `x` 轴区间重叠判定父子包含关系。
* **多期间切片**：自动识别上下叠放的多期间（如 2023 年 / 2022 年）对比表头，将其垂直切片为独立的数据 block，精准重建叶子节点全路径列名。

### 4. 自动化 Golden Corpus 语料库与回归测试体系
* **真值基准库**：构建覆盖 4 大保险巨头、12 份年度报告（2023-2025 年）的 Golden Corpus（`golden_values.yaml`）。
* **自动化 Benchmark 引擎**：编写自动化回归比对脚本，实现端到端的 Line Item 级数值与 Label 100% 自动对齐校验。

---

## 📈 四、 项目关键量化指标与产出 (Key Metrics & Achievements)

* **提取准确率**：金融投资四大 Member 核心子表及细项提取匹配率达到 **100% (Item Match Rate = 1.0)**。
* **解析覆盖度**：实现中国平安、中国太保、新华保险、中国人寿 2023-2025 全量年报主表与子表 100% 结构化覆盖。
* **稳定性与鲁棒性**：处理 24+ 个复杂跨页与多层表头的物理片段，长尾异常报错率降低为 0%。
* **工程交付物**：形成了完整的高可用 Python 解析引擎库（`releases/v6.11/`）、Golden 语料库、与基于 Streamlit 的可视人机协同审定界面。

---

## 💻 五、 核心技术栈 (Technology Stack)

* **核心语言 & 算法**：Python 3.10+, PyMuPDF (`fitz`), Spatial Geometry Reasoning, Structural NLP, Regular Expressions.
* **数据工程 & 存储**：Pandas, PyYAML, SQLite, JSON Lines (JSONL), Git Flow.
* **质量保证 & UI**：Pytest, Streamlit Framework, GitHub-Flavored Audit Reporting.

---

## 🎯 六、 简历精简版描述 (Resume Highlights Bullet Points)

> **（可直接复制填入简历中的“项目经验”部分）**

* **主导金融保险年报智能结构化解析平台的架构设计与核心算法开发**，针对 300+ 页非结构化 PDF 财报，构建单向可追溯的机器提取与人机协同审定管道。
* **创新提出基于 2D 物理坐标定锚与 5 大表格片段分类器（Segment Classifier）**，攻克了跨页续表粘连、ECL 减值三阶段表覆盖主表真值以及边界未定义挂起等行业难题。
* **设计多层级复合表头树状聚类算法**，通过 2D 空间区间投影，精准还原 2~3 层嵌套的跨行跨列复合表头及多期间对比数据块。
* **搭建 Golden Corpus 自动化回归测试体系**，覆盖平安、太保、新华、国寿等头部险企 12 份年报，实现金融投资子表细项提取 **100% 匹配率（Item Match Rate = 1.0）**。
