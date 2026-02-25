# plugin-audit

> Capability inventory & security audit tool for Claude Code

Scan all installed plugins, user commands, agents, and skills — generate a structured capability inventory, risk report, and change detection.

## Install

```bash
# 1. Add the marketplace
/plugins marketplace add nestedcat/nestedcat-claude-marketplace

# 2. Install the plugin
/plugins install plugin-audit@nestedcat-claude-marketplace
```

## Commands

| Command | Description |
|---------|-------------|
| `/audit` | Full capability scan with cache health report |
| `/audit-help <name>` | Detailed info for a specific capability |
| `/audit-risk` | Risk assessment report for all capabilities |
| `/audit-diff` | Compare current state against a saved snapshot |

## What it scans

- **Plugins**: `~/.claude/plugins/installed_plugins.json` → each plugin's commands, skills, agents, hooks
- **User-level**: `~/.claude/commands/`, `agents/`, `skills/`
- **Project-level**: `.claude/commands/`, `agents/`, `skills/`

## Example output

Running `/audit` produces a structured capability inventory like this:

| Name | Type | Source | Provider | Invocation |
|------|------|--------|----------|------------|
| frontend-design | skill | plugin:frontend-design | claude-plugins-official | Auto-triggered by model |
| setup_semgrep_plugin | command | plugin:semgrep-plugin | claude-plugins-official | `/setup_semgrep_plugin` |
| code-review | command | plugin:code-review | claude-plugins-official | `/code-review` |
| code-simplifier | agent | plugin:code-simplifier | claude-plugins-official | Use code-simplifier agent |
| revise-claude-md | command | plugin:claude-md-management | claude-plugins-official | `/revise-claude-md` |
| audit | command | plugin:plugin-audit | nestedcat-claude-marketplace | `/audit` |
| PostToolUse:Write\|Edit | hook | plugin:semgrep-plugin | claude-plugins-official | Auto-trigger |
| planner | agent | user | — | Use planner agent |
| tdd-guide | agent | user | — | Use tdd-guide agent |

**Statistics**: 18 capabilities — 6 commands, 3 skills, 3 agents, 6 hooks · from 6 plugins + user-level

**Notable findings**:
- `claude-md-improver` has broad permissions including `Bash`
- `semgrep-plugin` registers 4 hooks that auto-trigger on tool use and session start

The report also includes a **Cache Health** section showing orphaned plugin versions, version conflicts, and blocked plugins.

### Other commands

```
> /audit-help code-review
# Shows detailed info: description, permissions, invocation, source path

> /audit-risk
# Shows risk scores: CRITICAL / HIGH / MEDIUM / LOW

> /audit-diff
# Shows added / removed / changed capabilities since last snapshot
```

## Risk scoring

| Permission | Score |
|------------|-------|
| Bash (unrestricted) | 15 |
| Bash (pattern) | 8 |
| Write | 6 |
| Edit / NotebookEdit | 5 |
| WebFetch | 4 |
| Task / WebSearch | 3 |
| Read | 2 |
| Glob / Grep | 1 |
| Hook (auto-trigger) | +3 |
| Hook (wildcard) | +2 |

**Levels**: CRITICAL (≥15) · HIGH (≥10) · MEDIUM (≥5) · LOW (<5)

## Requirements

- Claude Code with Plugin support
- Python 3.11+ (stdlib only, zero dependencies)

## Development

```bash
# Run tests
cd scripts && python3 -m unittest test_scan -v

# Run scan directly
python3 scripts/scan.py --all
python3 scripts/scan.py --risk
python3 scripts/scan.py --detail <name>

# Load plugin locally
claude --plugin-dir /path/to/plugin-audit
```

## Disclaimer

This tool provides automated capability scanning and risk scoring as a convenience. It is **not** a substitute for professional security auditing. Risk scores are heuristic-based and may not capture all threats. Use at your own discretion.

## License

[MIT](LICENSE)

---

# plugin-audit

> Claude Code 能力索引与安全审计工具

扫描所有已安装的插件、用户命令、Agent 和 Skill，生成结构化能力清单、风险报告和变更检测。

## 安装

```bash
# 1. 添加插件市场
/plugins marketplace add nestedcat/nestedcat-claude-marketplace

# 2. 安装插件
/plugins install plugin-audit@nestedcat-claude-marketplace
```

## 命令

| 命令 | 说明 |
|------|------|
| `/audit` | 全面扫描，输出能力清单和缓存健康报告 |
| `/audit-help <name>` | 查询单个能力的详细信息 |
| `/audit-risk` | 所有能力的风险评估报告 |
| `/audit-diff` | 与历史快照对比，检测变更 |

## 扫描范围

- **插件**: `~/.claude/plugins/installed_plugins.json` → 每个插件的命令、技能、Agent、Hook
- **用户级**: `~/.claude/commands/`、`agents/`、`skills/`
- **项目级**: `.claude/commands/`、`agents/`、`skills/`

## 输出示例

运行 `/audit` 后，Claude 会将扫描结果整理为如下能力清单表格：

| 名称 | 类型 | 来源 | 提供者 | 调用方式 |
|------|------|------|--------|----------|
| frontend-design | skill | plugin:frontend-design | claude-plugins-official | 模型自动触发 |
| setup_semgrep_plugin | command | plugin:semgrep-plugin | claude-plugins-official | `/setup_semgrep_plugin` |
| code-review | command | plugin:code-review | claude-plugins-official | `/code-review` |
| code-simplifier | agent | plugin:code-simplifier | claude-plugins-official | Use code-simplifier agent |
| revise-claude-md | command | plugin:claude-md-management | claude-plugins-official | `/revise-claude-md` |
| audit | command | plugin:plugin-audit | nestedcat-claude-marketplace | `/audit` |
| PostToolUse:Write\|Edit | hook | plugin:semgrep-plugin | claude-plugins-official | 自动触发 |
| planner | agent | user | — | Use planner agent |
| tdd-guide | agent | user | — | Use tdd-guide agent |

**统计**: 18 个能力 — 6 命令、3 技能、3 Agent、6 Hook · 来自 6 个插件 + 用户级

**重要发现**：
- `claude-md-improver` 拥有包括 `Bash` 在内的广泛权限
- `semgrep-plugin` 注册了 4 个 Hook，在工具调用和会话启动时自动触发

报告还包含 **缓存健康** 部分，显示孤立的插件版本、版本冲突和被封锁的插件。

### 其他命令

```
> /audit-help code-review
# 显示详细信息：描述、权限、调用方式、源文件路径

> /audit-risk
# 显示风险评分：CRITICAL / HIGH / MEDIUM / LOW

> /audit-diff
# 显示新增 / 删除 / 变更的能力（与上次快照对比）
```

## 风险评分

| 权限 | 分值 |
|------|------|
| Bash（无限制） | 15 |
| Bash（受限模式） | 8 |
| Write | 6 |
| Edit / NotebookEdit | 5 |
| WebFetch | 4 |
| Task / WebSearch | 3 |
| Read | 2 |
| Glob / Grep | 1 |
| Hook（自动触发） | +3 |
| Hook（通配匹配） | +2 |

**风险等级**: CRITICAL (≥15) · HIGH (≥10) · MEDIUM (≥5) · LOW (<5)

## 环境要求

- 支持插件的 Claude Code
- Python 3.11+（仅标准库，零外部依赖）

## 开发

```bash
# 运行测试
cd scripts && python3 -m unittest test_scan -v

# 直接运行扫描
python3 scripts/scan.py --all
python3 scripts/scan.py --risk
python3 scripts/scan.py --detail <name>

# 本地加载插件测试
claude --plugin-dir /path/to/plugin-audit
```

## 免责声明

本工具提供自动化的能力扫描和风险评分，仅作为辅助参考。它**不能**替代专业的安全审计。风险评分基于启发式规则，可能无法覆盖所有威胁。请自行判断后使用。

## 许可证

[MIT](LICENSE)
