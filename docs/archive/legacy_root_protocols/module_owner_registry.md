# Module Owner Registry (模块 Ownership 注册表)

> **说明**：本注册表明确定义了 AXA\_research 代码库中各核心模块的责任 Owner 与允许的变更范围。 **强约束规则**：任何 Agent 在修改指定模块之前，必须严格核对本表。修改前必须检查：  
> 

> 1. 上游契约 (Upstream Contract)  
> 2. 下游契约 (Downstream Contract)  
> 3. 回归测试套件 (Regression Tests)

---

## 1\. 模块 Owner 权责分配表

| Module | Owner | Allowed Change Scope (允许变更范围) | Forbidden Change (严格禁止变更) |
| :---- | :---- | :---- | :---- |
| **OCR (`src/ocr/`)** | `OCR Owner` | OCR profile / cache / 图像预处理配置 / 400 DPI 渲染 | 禁止直接生成金额，禁止输出低 DPI 结果 |
| **Discovery (`src/discovery/`)** | `Discovery Owner` | Pattern 匹配算法 / Candidate Ranking 优化 / 章节规则 | 禁止修改下游 Capture 或 Merge 数据清洗规则 |
| **Capture (`src/capture/`)** | `Capture Owner` | Table extraction 算法 / 边界切分 / 单元格拓扑解析 | 禁止跨层直接生成研究宽表，禁止改写原始物理文本 |
| **Canonical (`src/canonical/`)** | `Canonical Owner` | 科目编码 Mapping / Normalization 归一化逻辑 | 禁止篡改 PDF 原始物理坐标证据，禁止做跨期指标组合 |
| **Merge (`src/merge/`)** | `Merge Owner` | Research aggregation 研究级组合 / 跨期对齐 / 勾稽校验 | 禁止重新解析 PDF，禁止违背 Rule 002 混入非金融投资科目 |
| **Review (`src/review/`)** | `Review Owner` | Human workflow 审核流程 / 证据链展示 / 审核动作响应 | 禁止无证据下伪造 `CERTIFIED` 状态 (Rule 004\) |
| **Export (`src/export/`)** | `Export Owner` | XLSX 样式渲染 / CSV 格式导出 / 超链接绑定 | 禁止在导出层重新调整数据解析或归一化逻辑 |

---

## 2\. 变更合规三步校验流程

任何 Agent 尝试对上述模块提交 Pull Request 或修改前，必须在代码注释或 Startup Audit 中确认以下 3 点：

1. **Upstream Check**：本次修改是否兼容上游模块输出的 Data Contract？  
2. **Downstream Check**：本次修改是否打破了下游模块依赖的 API 或数据结构？  
3. **Regression Check**：运行 `pytest tests/` 确保包含 5 项 Golden Cases 在内的所有测试通过。

