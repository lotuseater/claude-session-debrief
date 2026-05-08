# claude-session-debrief

Generate a markdown retrospective of any Claude Code session.

A small, dependency-free Python package and Claude Code plugin that parses a
`.jsonl` transcript and tells you what happened: which files were read for
nothing, where direction changed, the cleanest read → edit → verify cycle,
and how things compare across sessions.

## What it reports

For a single session:

- **Goal & outcome** — first/last user prompt; satisfaction-vs-correction signal.
- **Reading economy** — files Read that later got Edit'd or referenced in Bash (signal) vs files Read but never touched again (noise).
- **Exploration vs production** — wandering score; longest exploration span; longest production span.
- **Decision points** — turns where direction changed: tool errors, user rejections, empty greps, user redirects.
- **Best span** — cleanest read → edit → verify cycle.
- **Thinking density** — total reasoning chars per turn / per tool call; "silent" tool runs (autopilot).
- **Tools used** — frequency histogram.

Across many sessions (`/debrief last 5`, `/debrief stats`):

- Average wandering score and signal ratio.
- Verdict mix (satisfied / corrected / mixed / unknown).
- Decision-point kinds across the corpus.
- Files re-read across multiple sessions — strong candidates for memory.

## Install as a Claude Code plugin

```
/plugin marketplace add lotuseater/claude-session-debrief
/plugin install debrief
```

Then inside Claude Code:

```
/debrief:debrief             # picker — pick from recent sessions
/debrief:debrief last        # debrief the most-recent session (works on active sessions too)
/debrief:debrief last 5      # multi-session aggregate over the last 5
/debrief:debrief stats       # aggregate over every transcript on disk
/debrief:debrief list        # just print the picker menu
/debrief:debrief <path>      # debrief a specific .jsonl path or session-id prefix
```

The slash command writes to `~/.claude/debriefs/<session-id>.md` and prints a one-line summary. Open the file to see the full report.

`/debrief:debrief last` works on the active session too — it reads the JSONL transcript while it's being appended to and gives you a partial-but-valid debrief of the work-so-far. Re-run any time to refresh.

The plugin needs Python 3.10+ on `PATH`.

## Install as a CLI

```
pip install "git+https://github.com/lotuseater/claude-session-debrief.git#subdirectory=plugins/debrief"
session-debrief last
session-debrief last 5 --out report.md
session-debrief path/to/transcript.jsonl --root /path/to/project
```

`--root` shortens absolute paths in the report to project-relative form.

## Where transcripts live

Claude Code stores each session as JSONL under
`~/.claude/projects/<project-slug>/<session-uuid>.jsonl`. The `locator` module
finds them automatically; you only need to pass a path when you want a
specific one.

## Run the tests

```
git clone https://github.com/lotuseater/claude-session-debrief.git
cd claude-session-debrief/plugins/debrief
pip install -e .[dev]
pytest tests/ -v
```

## Status

Alpha — heuristics work well on the 13 transcripts they were validated against,
but the format of the JSONL is not officially specified, so future Claude Code
versions may break parsing. Bug reports welcome.

## License

MIT.
