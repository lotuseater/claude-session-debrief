"""Aggregate debriefs across multiple sessions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .heuristics import Debrief, debrief
from .parser import parse


@dataclass
class MultiDebrief:
    n_sessions: int
    total_turns: int
    total_tools: int
    avg_wandering: float
    avg_signal_ratio: float
    verdicts: dict[str, int]
    tool_histogram: list[tuple[str, int]]
    decision_kinds: list[tuple[str, int]]
    repeat_reads: list[tuple[str, int]]  # (path, sessions_in_which_it_was_read)
    sessions: list[Debrief] = field(default_factory=list)


def aggregate(paths: list[Path]) -> MultiDebrief:
    """Parse and debrief each transcript, then summarize across them."""
    debriefs: list[Debrief] = []
    sessions = []
    for p in paths:
        try:
            s = parse(p)
        except Exception:
            continue
        d = debrief(s)
        debriefs.append(d)
        sessions.append(s)
    if not debriefs:
        return MultiDebrief(
            n_sessions=0,
            total_turns=0,
            total_tools=0,
            avg_wandering=0.0,
            avg_signal_ratio=0.0,
            verdicts={},
            tool_histogram=[],
            decision_kinds=[],
            repeat_reads=[],
        )
    total_turns = sum(d.n_turns for d in debriefs)
    total_tools = sum(d.n_tools for d in debriefs)
    avg_wander = sum(d.flow.wandering_score for d in debriefs) / len(debriefs)
    avg_signal = sum(d.reading.signal_ratio for d in debriefs) / len(debriefs)

    verdicts = Counter(d.goal.verdict for d in debriefs)
    tool_total: Counter[str] = Counter()
    for d in debriefs:
        for name, count in d.tool_histogram:
            tool_total[name] += count
    decision_total: Counter[str] = Counter()
    for d in debriefs:
        for dp in d.decisions:
            decision_total[dp.kind] += 1

    repeat_reads = _files_read_across_sessions(sessions)

    return MultiDebrief(
        n_sessions=len(debriefs),
        total_turns=total_turns,
        total_tools=total_tools,
        avg_wandering=avg_wander,
        avg_signal_ratio=avg_signal,
        verdicts=dict(verdicts),
        tool_histogram=sorted(tool_total.items(), key=lambda kv: (-kv[1], kv[0])),
        decision_kinds=sorted(decision_total.items(), key=lambda kv: (-kv[1], kv[0])),
        repeat_reads=repeat_reads,
        sessions=debriefs,
    )


def _files_read_across_sessions(sessions: list) -> list[tuple[str, int]]:
    """Count how many distinct sessions read each file. Useful for spotting
    files that get re-read again and again — likely candidates for memory."""
    import os
    per_session_paths: list[set[str]] = []
    for s in sessions:
        paths: set[str] = set()
        for tu in s.tool_uses:
            if tu.name == "Read" and tu.result_text is not None:
                fp = (tu.input or {}).get("file_path")
                if fp:
                    paths.add(os.path.normcase(os.path.normpath(fp)))
        per_session_paths.append(paths)
    counter: Counter[str] = Counter()
    for paths in per_session_paths:
        for p in paths:
            counter[p] += 1
    # Only include files read in 2+ sessions — single-session reads aren't "repeat."
    return [(p, c) for p, c in counter.most_common() if c >= 2][:25]
