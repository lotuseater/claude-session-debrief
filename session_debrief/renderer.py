"""Render a Debrief into markdown."""

from __future__ import annotations

import os

from .heuristics import Debrief


def _short(p: str, root: str | None = None) -> str:
    if root:
        try:
            rel = os.path.relpath(p, root)
            if not rel.startswith(".."):
                return rel
        except ValueError:
            pass
    # Truncate long absolute paths from the left.
    if len(p) > 70:
        return "…" + p[-67:]
    return p


def render(d: Debrief, project_root: str | None = None) -> str:
    out: list[str] = []
    out.append(f"# Session Debrief — `{d.session_id}`")
    out.append("")
    out.append(f"**Turns:** {d.n_turns}  •  **Tool calls:** {d.n_tools}  •  "
               f"**Verdict:** {d.goal.verdict}")
    out.append("")

    # Goal & outcome
    out.append("## Goal & outcome")
    if d.goal.n_prompts == 0:
        out.append("_No user prompts found._")
    else:
        out.append(f"- **First prompt:** {d.goal.first_prompt!r}")
        if d.goal.n_prompts > 1:
            out.append(f"- **Last prompt:** {d.goal.last_prompt!r}")
        out.append(f"- **Prompts total:** {d.goal.n_prompts}")
        out.append(f"- **Satisfaction signals:** {d.goal.satisfaction_signals}  "
                   f"•  **Correction signals:** {d.goal.correction_signals}")
    out.append("")

    # Reading economy
    out.append("## Reading economy")
    r = d.reading
    if r.files_read == 0 and r.files_edited == 0:
        out.append("_No file reads or edits in this session._")
    else:
        out.append(f"- Files Read: **{r.files_read}**  •  "
                   f"Files Edited/Written: **{r.files_edited}**  •  "
                   f"Read→Edited overlap: **{r.files_read_then_edited}**")
        out.append(f"- Signal ratio (read → edited / read): "
                   f"**{r.signal_ratio:.0%}**")
        if r.files_read_never_touched:
            out.append("- Files read but never edited (potential noise):")
            for fp in r.files_read_never_touched:
                out.append(f"  - `{_short(fp, project_root)}`")
    out.append("")

    # Flow
    out.append("## Exploration vs production")
    f = d.flow
    if not f.spans:
        out.append("_No tool spans._")
    else:
        out.append(f"- Wandering score: **{f.wandering_score:.0%}** "
                   "_(higher = more exploration relative to production)_")
        if f.longest_exploration:
            sp = f.longest_exploration
            top = ", ".join(_top_tools(sp.tools))
            out.append(f"- Longest exploration span: turns {sp.start_turn}–{sp.end_turn} "
                       f"({sp.length} turns; tools: {top})")
        if f.longest_production:
            sp = f.longest_production
            top = ", ".join(_top_tools(sp.tools))
            out.append(f"- Longest production span: turns {sp.start_turn}–{sp.end_turn} "
                       f"({sp.length} turns; tools: {top})")
    out.append("")

    # Decision points
    out.append("## Decision points")
    if not d.decisions:
        out.append("_No decision-point signals detected._")
    else:
        for dp in d.decisions[:15]:
            out.append(f"- **turn {dp.turn}** ({dp.kind}): {dp.detail}")
        if len(d.decisions) > 15:
            out.append(f"- _… and {len(d.decisions) - 15} more_")
    out.append("")

    # Best span
    out.append("## Best span")
    if d.best is None:
        out.append("_No clean read → edit cycle detected._")
    else:
        b = d.best
        pat = " → ".join(b.pattern)
        out.append(f"- Turns {b.start_turn}–{b.end_turn}: `{pat}` ({b.note}, score {b.score:.1f})")
    out.append("")

    # Thinking density
    out.append("## Thinking density")
    th = d.thinking
    if th.total_chars == 0:
        out.append("_No visible thinking in this transcript._")
    else:
        out.append(f"- Total thinking: **{th.total_chars:,} chars** "
                   f"across {th.turns_with_thinking}/{d.n_turns} turns")
        if d.n_tools:
            out.append(f"- Per tool call: **{th.chars_per_tool_call:,.0f} chars**")
        if th.silent_tool_runs:
            out.append(f"- Tool-using turns with zero thinking: **{th.silent_tool_runs}** "
                       "_(autopilot moments — fine for routine work, suspicious for novel problems)_")
    out.append("")

    # Tool histogram
    out.append("## Tools used")
    if not d.tool_histogram:
        out.append("_No tool calls._")
    else:
        for name, count in d.tool_histogram:
            bar = "█" * min(count, 30)
            out.append(f"- `{name}`: {count} {bar}")
    out.append("")

    return "\n".join(out)


def _top_tools(names: list[str], k: int = 3) -> list[str]:
    from collections import Counter
    c = Counter(names)
    return [f"{n}×{cnt}" for n, cnt in c.most_common(k)]


def render_multi(m, label: str = "sessions", project_root: str | None = None) -> str:
    """Render a MultiDebrief (cross-session aggregate) to markdown."""
    out: list[str] = []
    out.append(f"# Multi-Session Debrief — {label}")
    out.append("")
    if m.n_sessions == 0:
        out.append("_No sessions to aggregate._")
        return "\n".join(out)
    out.append(f"**Sessions:** {m.n_sessions}  •  "
               f"**Total turns:** {m.total_turns:,}  •  "
               f"**Total tool calls:** {m.total_tools:,}")
    out.append("")

    out.append("## Averages")
    out.append(f"- Average wandering score: **{m.avg_wandering:.0%}**")
    out.append(f"- Average signal ratio (read→supported / read): **{m.avg_signal_ratio:.0%}**")
    out.append("")

    out.append("## Verdict mix")
    if m.verdicts:
        for v, c in sorted(m.verdicts.items(), key=lambda kv: -kv[1]):
            out.append(f"- `{v}`: {c}")
    else:
        out.append("_no verdict data_")
    out.append("")

    out.append("## Decision-point kinds")
    if m.decision_kinds:
        for kind, count in m.decision_kinds[:10]:
            out.append(f"- `{kind}`: {count}")
    else:
        out.append("_none_")
    out.append("")

    out.append("## Tools used (across all sessions)")
    if m.tool_histogram:
        for name, count in m.tool_histogram[:20]:
            bar = "█" * min(count // max(1, m.total_tools // 30), 30)
            out.append(f"- `{name}`: {count} {bar}")
    else:
        out.append("_no tool calls_")
    out.append("")

    out.append("## Files re-read across sessions")
    if m.repeat_reads:
        out.append("_Files Read in 2+ distinct sessions — strong candidates for memory._")
        out.append("")
        for path, sessions_count in m.repeat_reads:
            short = path
            if len(short) > 70:
                short = "…" + short[-67:]
            out.append(f"- `{short}` — read in {sessions_count} sessions")
    else:
        out.append("_no file was read across multiple sessions_")
    out.append("")

    return "\n".join(out)
