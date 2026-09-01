# Financial Metric Resolver v4.2 GUI — Live Progress

新增逐页解析进度、当前工作内容、实时日志、慢页提示与 activity.log。

# Financial Metric Resolver v4.1 GUI

新增：PDF 文件头预检、HTML伪PDF识别、截断警告、友好错误提示、diagnose_pdf.py。

# Financial Metric Resolver v4 GUI

v4 将 v3 的 PDF-first 引擎整合到一个本地 Web 图形工作台中。

## 一键启动

### Windows PowerShell

```powershell
cd C:\dev\AXA_research\financial_metric_resolver_v4_gui
python -m pip install -r requirements.txt
streamlit run app.py
```

或者双击：

```text
run_gui.bat
```

启动后浏览器会打开本地界面（通常是 localhost）。

## 界面模块

### 1. 总览
查看：
- L0 标准指标数量
- 已导入 PDF
- 历史运行
- 规则备份
- 完整工作流

### 2. L0 指标字典
无需手工修改 JSON：
- 搜索标准指标 / 别名
- 新增、编辑、删除指标
- aliases
- soft_aliases
- keywords
- exclude
- table_hint
- position_hint
- metric_type
- value_type
- 保存前自动校验
- 跨指标别名冲突检查
- 每次保存自动生成规则备份

这样可避免手工编辑 JSON 时少逗号导致 `JSONDecodeError`。

### 3. PDF 项目
- 拖拽上传 PDF
- 管理已导入 PDF
- 选择当前 PDF
- 查看 SHA256 / 文件大小

### 4. 运行提取
- 从 L0 多选指标
- 输入字典外指标用于 RULE GAP 测试
- 可选 DeepSeek / Gemini
- API Key 只保存在当前 Streamlit 会话环境，不写入报告/规则
- 可调整 Top-K 和置信度阈值
- 一键运行
- 自动生成：
  - results.json
  - audit.jsonl
  - report.html
  - report.md

### 5. 人工复核
逐个指标查看：
- 状态
- L0/L1/L2
- 置信度
- PDF页码
- 匹配原始科目
- 所有数值列
- 原始表格上下文
- Top候选

人工可：
- 确认自动结果
- 改选候选
- 驳回
- 写复核备注
- 将经过确认的查询别名回写 L0

人工复核写入：

```text
human_review.jsonl
```

不会覆盖原始机器结果，保留完整审计链。

### 6. 报告与审计
界面内直接查看：
- HTML 报告
- Markdown 报告
- results.json
- audit.jsonl
- human_review.jsonl

并可下载。

---

## 核心安全原则

1. LLM 不生成财务金额，只能在已有候选中选择或 abstain。
2. L0 规则保存前验证 JSON 结构和跨指标别名冲突。
3. 每次修改 L0 自动备份旧版本。
4. 自动结果与人工复核分层保存，不静默覆盖。
5. “权益”“收入”等宽泛词不应轻易提升为强别名。
6. 当前 v4 GUI 保留 v3 引擎逻辑；后续应加入“字典未命中时仍执行 PDF-first fallback 召回”的 v4.1 引擎改造。

## 文件结构

```text
financial_metric_resolver_v4_gui/
├── app.py
├── financial_metric_pdf_resolver.py
├── llm_providers.py
├── metric_aliases.json
├── requirements.txt
├── run_gui.bat
├── workspace/
│   ├── uploads/
│   ├── runs/
│   ├── rule_backups/
│   └── reviews/
└── README_GUI.md
```
