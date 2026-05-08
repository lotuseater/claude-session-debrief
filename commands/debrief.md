---
allowed-tools: Bash(python:*), Bash(py:*), Bash(python3:*), Bash(mkdir:*), Read, AskUserQuestion
description: Generate a retrospective for a past Claude Code session
argument-hint: [last [N] | stats | list | <transcript-path>]
---

You are running the `/debrief` command from the `claude-session-debrief` plugin. The plugin's Python module is bundled at `${CLAUDE_PLUGIN_ROOT}/session_debrief/`.

## Argument

The user's argument is: `$ARGUMENTS`

## Logic

Decide which mode based on `$ARGUMENTS`:

1. **No argument (empty)** — Show a picker:
   - Run `python -m session_debrief --list` from `${CLAUDE_PLUGIN_ROOT}` to list the 20 most-recent sessions.
   - Use `AskUserQuestion` to ask which one to debrief, offering the top 4 by recency as options. The 5th option ("Other") is automatically provided by the harness — the user can paste a session UUID prefix.
   - Once a session is picked, locate its full path (look in `~/.claude/projects/*/<id>*.jsonl`) and run the single-session debrief on it.

2. **`last`** — Run `python -m session_debrief --last` and display the resulting markdown.

3. **`last <N>`** (e.g. `last 5`) — Run `python -m session_debrief --last <N>` for a multi-session aggregate.

4. **`stats`** — Run `python -m session_debrief --stats` for an aggregate over every transcript on disk.

5. **`list`** — Run `python -m session_debrief --list` and print the menu without picking anything.

6. **Anything else** — Treat the argument as a path. If it ends in `.jsonl`, run `python -m session_debrief <path>`. Otherwise, treat it as a session-id prefix and search `~/.claude/projects/*/<prefix>*.jsonl` for a match.

## Output

- For all modes that produce a debrief, write the markdown to `~/.claude/debriefs/<session-id-or-summary>.md` (create the directory first if needed) **and** print the report inline so the user sees it immediately.
- Tell the user the path of the saved file at the end.
- Keep your own commentary minimal — the report is the deliverable.

## Notes

- Set `PYTHONIOENCODING=utf-8` when invoking Python on Windows so the markdown's arrows and bullets render correctly.
- All Python invocations should run from `${CLAUDE_PLUGIN_ROOT}` so `python -m session_debrief` finds the bundled package. Use `cd "${CLAUDE_PLUGIN_ROOT}"` first.
- This plugin requires Python 3.10+ on the system. If `python` isn't on PATH, try `py -3` or `python3` in that order.
- Never modify the transcripts. The tool only reads them.
