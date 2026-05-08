"""Heuristics that turn a parsed Session into structured debrief sections.

Each function takes a Session and returns a small dataclass. The renderer
formats those into markdown. Keep heuristics single-purpose and easy to test.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

from .parser import Session, ToolUse


SATISFACTION_WORDS = (
    "thanks", "thank you", "perfect", "great", "awesome",
    "nice", "exactly", "that worked", "looks good", "lgtm",
)
CORRECTION_WORDS = (
    "no,", "no.", "not that", "instead", "actually", "wait,",
    "stop", "don't", "doesn't work", "broken", "wrong",
)


@dataclass
class GoalOutcome:
    first_prompt: str
    last_prompt: str
    n_prompts: int
    satisfaction_signals: int
    correction_signals: int
    verdict: str  # "satisfied" | "mixed" | "corrected" | "unknown"


@dataclass
class ReadingEconomy:
    files_read: int
    files_edited: int
    files_read_then_edited: int
    files_read_never_touched: list[str]
    signal_ratio: float  # read_then_edited / files_read, 0..1


@dataclass
class Span:
    start_turn: int  # 1-indexed
    end_turn: int
    length: int
    tools: list[str]
    label: str  # "exploring" | "producing" | "mixed"


@dataclass
class FlowReport:
    spans: list[Span]
    longest_exploration: Span | None
    longest_production: Span | None
    wandering_score: float  # 0..1, higher = more wandering


@dataclass
class DecisionPoint:
    turn: int
    line_no: int
    kind: str   # "empty_grep" | "tool_error" | "tool_cancelled" | "user_redirect" | "tool_rejected"
    detail: str


@dataclass
class BestSpan:
    start_turn: int
    end_turn: int
    pattern: list[str]
    score: float
    note: str


@dataclass
class ThinkingProfile:
    total_chars: int
    turns_with_thinking: int
    chars_per_tool_call: float  # 0 if no tool calls
    silent_tool_runs: int  # tool-using turns with zero thinking


@dataclass
class Debrief:
    session_id: str
    n_turns: int
    n_tools: int
    goal: GoalOutcome
    reading: ReadingEconomy
    flow: FlowReport
    decisions: list[DecisionPoint]
    best: BestSpan | None
    tool_histogram: list[tuple[str, int]]
    thinking: ThinkingProfile


# --- goal & outcome -------------------------------------------------------

def goal_outcome(s: Session) -> GoalOutcome:
    if not s.prompts:
        return GoalOutcome(
            first_prompt="(no user prompts)",
            last_prompt="",
            n_prompts=0,
            satisfaction_signals=0,
            correction_signals=0,
            verdict="unknown",
        )
    first = s.prompts[0].text.strip()
    last = s.prompts[-1].text.strip()
    sat = 0
    cor = 0
    # Look at the last 3 prompts — that's where the user reacts to recent work.
    for p in s.prompts[-3:]:
        low = p.text.lower()
        sat += sum(1 for w in SATISFACTION_WORDS if w in low)
        cor += sum(1 for w in CORRECTION_WORDS if w in low)
    if sat and not cor:
        verdict = "satisfied"
    elif cor and not sat:
        verdict = "corrected"
    elif sat and cor:
        verdict = "mixed"
    else:
        verdict = "unknown"
    return GoalOutcome(
        first_prompt=first[:240],
        last_prompt=last[:240],
        n_prompts=len(s.prompts),
        satisfaction_signals=sat,
        correction_signals=cor,
        verdict=verdict,
    )


# --- reading economy ------------------------------------------------------

def _norm_path(p: str) -> str:
    if not p:
        return p
    return os.path.normcase(os.path.normpath(p))


def _file_path_from_tool(tu: ToolUse) -> str | None:
    """Extract the file path a tool acted on, if any."""
    inp = tu.input or {}
    name = tu.name
    if name == "Read":
        return inp.get("file_path")
    if name in ("Edit", "Write"):
        return inp.get("file_path")
    if name == "NotebookEdit":
        return inp.get("notebook_path")
    return None


def reading_economy(s: Session) -> ReadingEconomy:
    reads: dict[str, int] = {}
    edits: set[str] = set()
    bash_text = []  # accumulated Bash commands and outputs — search-haystack for path mentions

    for tu in s.tool_uses:
        if tu.result_text is None:
            continue
        if tu.name == "Bash":
            bash_text.append((tu.input or {}).get("command", "") or "")
            bash_text.append(tu.result_text or "")
            continue
        fp = _file_path_from_tool(tu)
        if not fp:
            continue
        key = _norm_path(fp)
        if tu.name == "Read":
            reads[key] = reads.get(key, 0) + 1
        elif tu.name in ("Edit", "Write", "NotebookEdit"):
            edits.add(key)

    bash_blob = "\n".join(bash_text).lower()

    # A read is "supported" if the file was Edit/Write'd OR referenced in any Bash
    # command (e.g., a CLI that wrote to it via --out, or a process invoked on it).
    def _is_supported(path_norm: str) -> bool:
        if path_norm in edits:
            return True
        # Match either the full normalized path or the basename — Bash commands
        # often use forward slashes or cd-relative paths.
        base = os.path.basename(path_norm)
        return base.lower() in bash_blob or path_norm.lower() in bash_blob

    read_set = set(reads.keys())
    supported = {p for p in read_set if _is_supported(p)}
    never_touched = sorted(read_set - supported)
    files_read = len(read_set)
    ratio = (len(supported) / files_read) if files_read else 0.0
    return ReadingEconomy(
        files_read=files_read,
        files_edited=len(edits),
        files_read_then_edited=len(supported),
        files_read_never_touched=never_touched[:20],
        signal_ratio=ratio,
    )


# --- flow / spans ---------------------------------------------------------

EXPLORATION_TOOLS = {"Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch", "Agent", "ToolSearch"}
PRODUCTION_TOOLS = {"Edit", "Write", "NotebookEdit"}


def flow_report(s: Session) -> FlowReport:
    spans: list[Span] = []
    if not s.turns:
        return FlowReport(spans=[], longest_exploration=None, longest_production=None, wandering_score=0.0)

    # Walk turns; group consecutive turns that share the same broad mode.
    def mode(turn) -> str:
        names = [s.tool_index[t].name for t in turn.tool_use_ids if t in s.tool_index]
        if not names:
            return "talk"
        prod = sum(1 for n in names if n in PRODUCTION_TOOLS)
        expl = sum(1 for n in names if n in EXPLORATION_TOOLS)
        if prod and not expl:
            return "producing"
        if expl and not prod:
            return "exploring"
        if prod and expl:
            return "mixed"
        return "talk"

    cur_mode = None
    cur_start = 0
    cur_tools: list[str] = []
    for idx, turn in enumerate(s.turns, start=1):
        m = mode(turn)
        names = [s.tool_index[t].name for t in turn.tool_use_ids if t in s.tool_index]
        if m != cur_mode:
            if cur_mode is not None and cur_mode != "talk":
                spans.append(Span(
                    start_turn=cur_start,
                    end_turn=idx - 1,
                    length=idx - cur_start,
                    tools=cur_tools,
                    label=cur_mode,
                ))
            cur_mode = m
            cur_start = idx
            cur_tools = list(names)
        else:
            cur_tools.extend(names)
    # close trailing
    if cur_mode is not None and cur_mode != "talk":
        spans.append(Span(
            start_turn=cur_start,
            end_turn=len(s.turns),
            length=len(s.turns) - cur_start + 1,
            tools=cur_tools,
            label=cur_mode,
        ))

    longest_expl = max(
        (sp for sp in spans if sp.label == "exploring"),
        key=lambda sp: sp.length,
        default=None,
    )
    longest_prod = max(
        (sp for sp in spans if sp.label == "producing" or sp.label == "mixed"),
        key=lambda sp: sp.length,
        default=None,
    )
    expl_total = sum(sp.length for sp in spans if sp.label == "exploring")
    prod_total = sum(sp.length for sp in spans if sp.label in ("producing", "mixed"))
    denom = expl_total + prod_total
    wandering = (expl_total / denom) if denom else 0.0
    return FlowReport(
        spans=spans,
        longest_exploration=longest_expl,
        longest_production=longest_prod,
        wandering_score=wandering,
    )


# --- decision points ------------------------------------------------------

def decision_points(s: Session) -> list[DecisionPoint]:
    out: list[DecisionPoint] = []
    for tu in s.tool_uses:
        if tu.result_text is None:
            # No result ever arrived — tool was either cancelled mid-flight
            # or the transcript was truncated. Don't flood with these; only
            # report if we're not at the tail (last 2 tool uses).
            if tu is not s.tool_uses[-1] and tu is not s.tool_uses[-2 if len(s.tool_uses) > 1 else -1]:
                out.append(DecisionPoint(
                    turn=_turn_index(s, tu.line_no),
                    line_no=tu.line_no,
                    kind="tool_cancelled",
                    detail=f"{tu.name} produced no result",
                ))
            continue
        if tu.result_error:
            body = (tu.result_text or "").lower()
            # Specific case: user rejected the tool. Only counts when error=true,
            # otherwise the phrase is just incidental content from a Read of a transcript.
            if "user doesn't want to proceed" in body:
                out.append(DecisionPoint(
                    turn=_turn_index(s, tu.line_no),
                    line_no=tu.line_no,
                    kind="tool_rejected",
                    detail=f"{tu.name} rejected by user",
                ))
            elif _is_benign_cache_hit(body):
                # Wizard's pretool_cache_hook returns is_error=true to short-circuit
                # redundant Reads, but it's normal flow, not a real error.
                pass
            else:
                out.append(DecisionPoint(
                    turn=_turn_index(s, tu.line_no),
                    line_no=tu.line_no,
                    kind="tool_error",
                    detail=f"{tu.name} returned error: {_sanitize(tu.result_text or '')}",
                ))
            continue
        if tu.name == "Grep":
            body = tu.result_text or ""
            if _looks_like_zero_grep(body):
                out.append(DecisionPoint(
                    turn=_turn_index(s, tu.line_no),
                    line_no=tu.line_no,
                    kind="empty_grep",
                    detail=f"Grep for {tu.input.get('pattern','?')!r} returned no matches",
                ))
    # user redirects: prompts after the first that contain correction words
    for p in s.prompts[1:]:
        low = p.text.lower()
        if any(w in low for w in CORRECTION_WORDS):
            out.append(DecisionPoint(
                turn=_turn_index_for_prompt(s, p.line_no),
                line_no=p.line_no,
                kind="user_redirect",
                detail=f"User: {_sanitize(p.text, limit=80)!r}",
            ))
    return sorted(out, key=lambda d: d.line_no)


def _turn_index(s: Session, line_no: int) -> int:
    """Return 1-indexed turn number whose line range contains this line."""
    for idx, t in enumerate(s.turns, start=1):
        if t.line_no >= line_no:
            return idx
    return len(s.turns)


def _turn_index_for_prompt(s: Session, line_no: int) -> int:
    """Return the 1-indexed turn that follows this prompt line."""
    for idx, t in enumerate(s.turns, start=1):
        if t.line_no > line_no:
            return idx
    return len(s.turns)


_ZERO_GREP_PATTERNS = (
    re.compile(r"\bNo (matches|files) found\b", re.I),
    re.compile(r"^\s*$"),
    re.compile(r"\bFound 0\b", re.I),
)

# CSI sequences (color codes) come through verbatim from PowerShell/Bash error output.
_ANSI_CSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
# OSC sequences (terminal title etc.), terminated by BEL or ESC \
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def _sanitize(text: str, limit: int = 140) -> str:
    """Strip ANSI escapes, collapse whitespace, and truncate for one-line display."""
    if not text:
        return ""
    s = _ANSI_OSC.sub("", text)
    s = _ANSI_CSI.sub("", s)
    s = s.replace("\r", " ").replace("\t", " ")
    # Collapse runs of whitespace (including newlines) to single spaces.
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _looks_like_zero_grep(body: str) -> bool:
    body = (body or "").strip()
    if not body:
        return True
    return any(p.search(body) for p in _ZERO_GREP_PATTERNS)


_BENIGN_CACHE_PHRASES = (
    "cached tool result reused",
    "cache short-circuit",
    "memoized",
)


def _is_benign_cache_hit(body_lower: str) -> bool:
    return any(p in body_lower for p in _BENIGN_CACHE_PHRASES)


# --- best span ------------------------------------------------------------

def best_span(s: Session) -> BestSpan | None:
    """Find the cleanest read -> reason -> edit -> verify cycle.

    We look for windows of ~2-6 consecutive tool uses that go:
      Read|Grep -> (optional Read|Grep) -> Edit|Write -> (optional Bash test).
    Score by length and by presence of all four phases.
    """
    if not s.tool_uses:
        return None
    flat = [tu for tu in s.tool_uses if tu.result_text is not None]
    best: BestSpan | None = None
    n = len(flat)
    for i in range(n):
        for j in range(i + 2, min(i + 7, n + 1)):
            window = flat[i:j]
            score, note = _score_window(window)
            if score <= 0:
                continue
            start_turn = _turn_index(s, window[0].line_no)
            end_turn = _turn_index(s, window[-1].line_no)
            cand = BestSpan(
                start_turn=start_turn,
                end_turn=end_turn,
                pattern=[tu.name for tu in window],
                score=score,
                note=note,
            )
            if best is None or cand.score > best.score:
                best = cand
    return best


def _score_window(window: list[ToolUse]) -> tuple[float, str]:
    names = [tu.name for tu in window]
    has_read = any(n in ("Read", "Grep", "Glob") for n in names)
    has_edit = any(n in ("Edit", "Write") for n in names)
    if not (has_read and has_edit):
        return 0.0, ""
    # Prefer the canonical order: read before edit.
    first_read = next(i for i, n in enumerate(names) if n in ("Read", "Grep", "Glob"))
    first_edit = next(i for i, n in enumerate(names) if n in ("Edit", "Write"))
    if first_read >= first_edit:
        return 0.0, ""
    score = 1.0 + 0.4 * (first_edit - first_read)
    note = "read → edit"
    if any(n == "Bash" for n in names[first_edit:]):
        score += 1.0
        note = "read → edit → verify"
    if any(tu.result_error for tu in window):
        score -= 0.5
    return score, note


# --- thinking profile -----------------------------------------------------

def thinking_profile(s: Session) -> ThinkingProfile:
    total = sum(t.thinking_chars for t in s.turns)
    with_thinking = sum(1 for t in s.turns if t.thinking_chars > 0)
    n_tool_calls = sum(1 for tu in s.tool_uses if tu.result_text is not None)
    silent = sum(1 for t in s.turns if t.tool_use_ids and t.thinking_chars == 0)
    return ThinkingProfile(
        total_chars=total,
        turns_with_thinking=with_thinking,
        chars_per_tool_call=(total / n_tool_calls) if n_tool_calls else 0.0,
        silent_tool_runs=silent,
    )


# --- top-level ------------------------------------------------------------

def debrief(s: Session) -> Debrief:
    histo = Counter(tu.name for tu in s.tool_uses if tu.result_text is not None)
    return Debrief(
        session_id=s.session_id,
        n_turns=len(s.turns),
        n_tools=sum(1 for tu in s.tool_uses if tu.result_text is not None),
        goal=goal_outcome(s),
        reading=reading_economy(s),
        flow=flow_report(s),
        decisions=decision_points(s),
        best=best_span(s),
        tool_histogram=sorted(histo.items(), key=lambda kv: (-kv[1], kv[0])),
        thinking=thinking_profile(s),
    )
