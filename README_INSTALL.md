# AXA_research AI Engineering Layer v1

将本包内全部文件和目录复制到：

`C:\dev\AXA_research\`

首次安装后执行：

```powershell
cd C:\dev\AXA_research
python scripts\generate_ai_context.py
```

主要入口：

- `AGENTS.md`：Codex
- `CLAUDE.md`：Claude Code
- `GEMINI.md`：Gemini CLI / Google 系 Agent
- `ANTIGRAVITY.md`：Antigravity 项目规则入口
- `AI_CONTEXT.md`：项目当前事实
- `AI_RULES.md`：永久规则
- `ARCHITECTURE.md`：模块边界和唯一数据流
- `DATA_CONTRACTS.md`：证据、金额、Capture、Canonical 和 Merge 契约
- `skills/*/SKILL.md`：专项任务工作流

`ANTIGRAVITY.md` 是否自动加载取决于版本；应在其 workspace rules 中明确要求读取该文件。
