---
description: Compare current capabilities against a saved snapshot to detect changes
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py:*)
---

Compare the current Claude Code capabilities against a previously saved snapshot.

## Usage

This command requires a snapshot file. The typical workflow is:

1. **Save a baseline snapshot** (run once):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --all --save-snapshot ~/.claude/audit-snapshot.json
   ```

2. **Compare against the baseline** (run anytime after plugin changes):
   Use `/audit-diff` to see what changed.

Running the diff now:

!`python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --diff ~/.claude/audit-snapshot.json`

## Instructions

After receiving the diff output above:

### If SNAPSHOT_NOT_FOUND

Tell the user they need to save a baseline snapshot first. Provide this command:

```bash
python3 ~/.claude/plugins/cache/*/plugin-audit/*/scripts/scan.py --all --save-snapshot ~/.claude/audit-snapshot.json
```

Or if using the plugin directly:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --all --save-snapshot ~/.claude/audit-snapshot.json
```

### If diff results are available

Present the results clearly:

1. **Change summary**: Show total changes count (added, removed, changed).

2. **Added capabilities**: List newly discovered capabilities with their type, source, and invocation.

3. **Removed capabilities**: List capabilities that are no longer present.

4. **Changed capabilities**: Show what specifically changed (description, permissions, invocation) with before/after comparison.

5. **Security implications**: Highlight any changes that affect risk:
   - New capabilities with Bash or Write permissions
   - Permission escalations (capabilities that gained new tool access)
   - New auto-triggered hooks

6. **Next steps**: Suggest running `/audit-risk` if new high-risk capabilities were detected.
