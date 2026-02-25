---
description: Scan all installed plugins, commands, agents, and skills to generate a capability inventory
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py:*)
---

Scan all Claude Code capabilities across installed plugins, user-level configurations, and project-level configurations.

Run the capability scanner with cache health analysis:

!`python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --all --cache-health`

## Instructions

After receiving the scan results above, present them to the user clearly:

1. **Summary table**: List all capabilities in a compact table with columns:
   - Name | Type | Source | Provider | Invocation
   - **Source column**: Use the FULL source value from the scan output, e.g. `plugin:code-review`, `plugin:semgrep-plugin`, `user`, `project`. The source is shown in square brackets like `[plugin:code-review]`. Do NOT shorten it to just `plugin` — always include the plugin name after the colon.
   - **Provider column**: Shows the marketplace origin (e.g. "claude-plugins-official"). Look for the "@" marker in the scan output (e.g. `@claude-plugins-official`). Leave blank for user-level and project-level capabilities.

2. **Statistics**: Show counts by type (commands, skills, agents, hooks) and by source (plugin/user/project).

3. **Notable findings** (if any):
   - Capabilities with broad permissions (e.g. unrestricted Bash access)
   - Hooks that auto-trigger on every tool use
   - Duplicate capability names from different sources

4. **Cache health** (from the CACHE HEALTH REPORT section):
   - Total cache size and orphaned size
   - Number of orphaned versions (old plugin versions no longer active)
   - Version conflicts (same plugin using different versions in user vs project scope)
   - Blocked plugins (if any)
   - If orphaned versions exist, note the disk space they occupy

5. If the user wants details about a specific capability, suggest using `/audit-help <name>`.
