---
allowed-tools: Bash(python:*), Bash(py:*), Bash(python3:*)
description: Generate a retrospective for a Claude Code session
argument-hint: [last [N] | stats | list | <session-id-or-path>]
---

Run from `${CLAUDE_PLUGIN_ROOT}`:
`PYTHONIOENCODING=utf-8 python -m session_debrief --quiet $ARGUMENTS`

(falls back to `py -3` or `python3` if `python` isn't on PATH).

Show stdout to the user as-is — it's a one-line summary plus the path to the saved markdown report. Don't paste the full report inline; the user can open the file when curious.

If `$ARGUMENTS` is empty, the command prints a numbered list of recent sessions; ask the user (AskUserQuestion) which one they want, then re-run with that session id.
