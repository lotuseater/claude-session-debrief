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
/plugin marketplace add https://github.com/lotuseater/claude-session-debrief.git
/plugin install claude-session-debrief
```

Then inside Claude Code:

```
/debrief                  # picker — choose from the 10 most-recent sessions
/debrief last             # debrief the most-recent session
/debrief last 5           # multi-session aggregate over the last 5
/debrief stats            # aggregate over every transcript on disk
/debrief list             # print the picker menu, no debrief
/debrief <path-to.jsonl>  # debrief a specific transcript path
```

The plugin needs Python 3.10+ on `PATH`. It writes the report to
`~/.claude/debriefs/<session-id>.md` and also prints it inline.

## Install as a CLI

The Python package lives under `plugins/claude-session-debrief/`. Install it via pip's `subdirectory=` option:

```
pip install "git+https://github.com/lotuseater/claude-session-debrief.git#subdirectory=plugins/claude-session-debrief"
session-debrief --last
session-debrief --last 5 --out report.md
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
cd claude-session-debrief/plugins/claude-session-debrief
pip install -e .[dev]
pytest tests/ -v
```

## Status

Alpha — heuristics work well on the 13 transcripts they were validated against,
but the format of the JSONL is not officially specified, so future Claude Code
versions may break parsing. Bug reports welcome.

## License

MIT.
