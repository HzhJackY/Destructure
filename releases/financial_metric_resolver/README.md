# 财务科目三层解析器

可直接运行的“规则优先 → 启发式 → LLM兜底”财务报表科目解析器。

## 设计原则

- **L0 人工规则**：规范化后做精确标准名/别名匹配；故意不采用危险的 `alias in user_input`。
- **L1 启发式**：综合字符串相似度、关键词、表类型、位置和数值密度评分。
- **L2 LLM**：可选；只允许从 L1 已抽取候选中选择 `candidate_id` 或 abstain，禁止编造数值和行号。
- **可审计**：输出 JSON，同时写 JSONL 审计日志和源文件 SHA256。

重要修正：`净利润`、`归母净利润`、`综合收益总额` 是不同科目；`保险服务收入` 也不应机械并入传统 `营业收入`。

## 安装

```bash
python -m pip install -r requirements.txt
```

建议 Python 3.10+。

## 校验规则

```bash
python financial_metric_resolver.py \
  --input sample_financial.xlsx \
  --metrics 营业收入 \
  --rules metric_aliases.json \
  --validate-rules-only
```

## 默认运行（不调用 LLM）

```bash
python financial_metric_resolver.py \
  --input sample_financial.xlsx \
  --metrics 营业收入 净利润 归母净利润 货币资金 保险合同负债 \
  --rules metric_aliases.json \
  --output result.json \
  --audit audit.jsonl
```

`--input` 也可指向目录，会递归处理所有 `.xlsx/.xlsm`。

## 启用 LLM 兜底

PowerShell：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="gpt-5.5"
python financial_metric_resolver.py --input sample_financial.xlsx --metrics 营业收益 --rules metric_aliases.json --enable-llm
```

默认使用 OpenAI Python SDK 的 Responses API。LLM 只接收候选摘要，不直接决定金额。

## 状态

- `RESOLVED`：自动解析成功
- `REVIEW_REQUIRED`：证据不足，需人工审核
- `UNRESOLVED`：输入无法安全映射到当前规则知识库
- `L0`：精确规则
- `L1`：启发式评分
- `L2`：LLM bounded-choice 兜底

## 生产化建议

1. `metric_aliases.json` 纳入 Git 版本控制，由财务专家审批。
2. 统计高频 `REVIEW_REQUIRED/UNRESOLVED`，作为规则增量候选。
3. 加入公司/行业/会计准则期间维度，避免同名科目跨行业语义漂移。
4. 金额落库前增加单位归一化、跨期勾稽、资产=负债+权益等 QA。
5. LLM 只做消歧，不做“凭空识别”；所有自动决策保留候选证据。
