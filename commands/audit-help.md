---
description: Show detailed information about a specific capability
argument-hint: <capability-name>
allowed-tools: Bash(python:*)
---

Show detailed information about a specific Claude Code capability.

The user provided the following capability name: $ARGUMENTS

Run the detail query:

!`python ${CLAUDE_PLUGIN_ROOT}/scripts/scan.py --detail "$ARGUMENTS"`

## Instructions

After receiving the detail output above, present it clearly:

1. **If the capability is found**, display:
   - Full name, type, and source
   - File path (clickable if possible)
   - Complete description
   - How to invoke it
   - Permissions / allowed tools
   - Additional metadata (model, color, etc.)

2. **If the capability is not found**, the output will include a list of available capabilities. Help the user by:
   - Suggesting the closest matching names
   - Asking if they meant one of the suggestions
