---
allowed-tools: Bash(python:*), Bash(py:*), Bash(python3:*)
description: Generate a retrospective for a Claude Code session
argument-hint: [last [N] | stats | list | <session-id-or-path>]
---

Run exactly this single bash command and show its stdout to the user as-is. Do not paste the full markdown report inline — the command's `--quiet` mode prints just a one-line summary plus the path to the saved report file.

```
cd "${CLAUDE_PLUGIN_ROOT}" && PYTHONIOENCODING=utf-8 python -m session_debrief --quiet $ARGUMENTS
```

If `python` isn't on PATH, fall back to `py -3` (Windows) or `python3` (Unix), keeping the rest identical.

Empty `$ARGUMENTS` debriefs the most-recent session. Use `last N`, `stats`, `list`, or a `<session-id-prefix>` / `<.jsonl path>` to pick something else.
