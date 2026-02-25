---
description: Assess risk levels for all installed plugins, commands, agents, and skills
allowed-tools: Bash(python:*)
---

Scan all Claude Code capabilities and output a risk assessment report.

!`python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --risk`

## Instructions

After receiving the risk report above, present the results clearly:

1. **Risk summary**: Show the count of capabilities at each risk level (CRITICAL, HIGH, MEDIUM, LOW).

2. **Risk table**: List all capabilities scored MEDIUM or above in a table with columns:
   - Name | Type | Source | Score | Level
   - **Source column**: Use the FULL source value, e.g. `plugin:code-review`, `user`, `project`. Do NOT shorten to just `plugin`.
   - Sort by score descending (highest risk first).

3. **Risk factors**: For each CRITICAL or HIGH capability, explain the specific risk factors (e.g. "Unrestricted Bash access", "Auto-triggered hook").

4. **Risk level definitions**:
   - **CRITICAL** (score >= 15): Capabilities with unrestricted shell access or broad dangerous permissions
   - **HIGH** (score >= 10): Capabilities with restricted but powerful tool access (e.g. Bash patterns + Write)
   - **MEDIUM** (score >= 5): Capabilities with moderate tool access (e.g. Write, Edit, WebFetch)
   - **LOW** (score < 5): Capabilities with read-only or no tool permissions

5. **Recommendations**: Suggest actions for CRITICAL and HIGH risk capabilities:
   - Review whether the permissions are justified for the capability's purpose
   - Consider restricting broad Bash patterns
   - Monitor auto-triggered hooks for unexpected behavior

6. If the user wants details about a specific capability, suggest using `/audit-help <name>`.
