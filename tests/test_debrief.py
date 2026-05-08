"""Tests for session_debrief.

Run from the repo root:
    python -m pytest tests/ -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_debrief.parser import parse
from session_debrief.heuristics import (
    debrief,
    goal_outcome,
    reading_economy,
    flow_report,
    decision_points,
    best_span,
    thinking_profile,
)
from session_debrief.renderer import render


FIX = Path(__file__).parent / "fixtures"


# --- parser ---------------------------------------------------------------

def test_parse_tight_session_extracts_one_prompt_three_tools():
    s = parse(FIX / "tight.jsonl")
    assert len(s.prompts) == 2  # initial request + final "perfect, thanks"
    assert s.prompts[0].text == "Add a docstring to foo.py"
    assert s.prompts[1].text == "perfect, thanks"
    assert len(s.tool_uses) == 3
    assert [t.name for t in s.tool_uses] == ["Read", "Edit", "Bash"]
    # Tool results should be paired in.
    assert all(t.result_text is not None for t in s.tool_uses)


def test_parse_meta_only_yields_no_prompts_or_tools():
    s = parse(FIX / "meta_only.jsonl")
    assert s.prompts == []
    assert s.tool_uses == []
    assert s.meta_lines >= 3


def test_parse_empty_file_is_safe():
    s = parse(FIX / "empty.jsonl")
    assert s.prompts == []
    assert s.tool_uses == []
    assert s.raw_lines == 0


def test_parse_truncated_file_skips_bad_lines():
    s = parse(FIX / "truncated.jsonl")
    # The trailing broken-JSON line should be skipped silently.
    assert len(s.prompts) == 1
    assert len(s.tool_uses) == 2
    # Last tool has no result — transcript truncated mid-flight.
    assert s.tool_uses[-1].result_text is None


# --- heuristics: goal -----------------------------------------------------

def test_goal_outcome_satisfied_when_thanks_appears():
    s = parse(FIX / "tight.jsonl")
    g = goal_outcome(s)
    assert g.verdict == "satisfied"
    assert g.satisfaction_signals >= 1
    assert g.correction_signals == 0


def test_goal_outcome_corrected_when_user_redirects():
    s = parse(FIX / "errored.jsonl")
    g = goal_outcome(s)
    assert g.verdict == "corrected"
    assert g.correction_signals >= 1


def test_goal_outcome_unknown_when_no_signal():
    s = parse(FIX / "wandering.jsonl")
    g = goal_outcome(s)
    # "actually" appears in the redirect prompt — that's a correction.
    assert g.verdict in ("corrected", "unknown")


# --- heuristics: reading economy -----------------------------------------

def test_reading_economy_full_overlap_in_tight():
    s = parse(FIX / "tight.jsonl")
    r = reading_economy(s)
    assert r.files_read == 1
    assert r.files_edited == 1
    assert r.files_read_then_edited == 1
    assert r.signal_ratio == 1.0
    assert r.files_read_never_touched == []


def test_reading_economy_zero_overlap_when_only_grepping():
    s = parse(FIX / "wandering.jsonl")
    r = reading_economy(s)
    assert r.files_read >= 1
    assert r.files_edited == 0
    assert r.signal_ratio == 0.0


def test_reading_economy_treats_bash_produced_files_as_supported():
    """If a Bash command produced /tmp/out.md and we then Read it, that read is
    verification, not noise — the file appears in a Bash command earlier."""
    import json
    import tempfile
    rows = [
        {"type": "user", "message": {"role": "user", "content": "build it"},
         "uuid": "u1", "timestamp": "t", "sessionId": "x"},
        {"type": "assistant", "requestId": "r1",
         "message": {"id": "m1", "role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command": "python build.py --out /proj/out.md"}}]},
         "uuid": "a1", "timestamp": "t", "sessionId": "x"},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": "t1", "type": "tool_result",
             "content": "wrote /proj/out.md", "is_error": False}]},
         "uuid": "u2", "timestamp": "t", "sessionId": "x"},
        {"type": "assistant", "requestId": "r2",
         "message": {"id": "m2", "role": "assistant", "content": [
             {"type": "tool_use", "id": "t2", "name": "Read",
              "input": {"file_path": "/proj/out.md"}}]},
         "uuid": "a2", "timestamp": "t", "sessionId": "x"},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": "t2", "type": "tool_result",
             "content": "...content...", "is_error": False}]},
         "uuid": "u3", "timestamp": "t", "sessionId": "x"},
    ]
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl",
                                     encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        tmp = f.name
    s = parse(tmp)
    r = reading_economy(s)
    # The Read of /proj/out.md should NOT appear as noise — Bash referenced it.
    assert r.files_read_never_touched == []
    assert r.files_read == 1
    assert r.signal_ratio == 1.0


# --- heuristics: flow ----------------------------------------------------

def test_flow_separates_exploration_and_production():
    s = parse(FIX / "tight.jsonl")
    f = flow_report(s)
    labels = [sp.label for sp in f.spans]
    assert "exploring" in labels  # the initial Read
    assert "producing" in labels  # the Edit


# --- heuristics: decision points ------------------------------------------

def test_decision_points_catches_tool_error():
    s = parse(FIX / "errored.jsonl")
    dps = decision_points(s)
    kinds = {d.kind for d in dps}
    assert "tool_error" in kinds
    assert "user_redirect" in kinds


def test_decision_points_catches_empty_grep():
    s = parse(FIX / "wandering.jsonl")
    dps = decision_points(s)
    assert any(d.kind == "empty_grep" for d in dps)


def test_decision_points_distinguishes_rejection_from_generic_error():
    s = parse(FIX / "rejected.jsonl")
    dps = decision_points(s)
    kinds = [d.kind for d in dps]
    # Should be exactly one tool_rejected, not a tool_error.
    assert "tool_rejected" in kinds
    assert "tool_error" not in kinds


def test_decision_points_strip_ansi_escapes_from_error_text():
    """PowerShell errors arrive with ANSI color codes (\\x1b[31;1m...). Those
    must not leak into the rendered detail."""
    import json
    import tempfile
    raw = "\x1b[31;1mInvoke-Pester:\x1b[0m \x1b[31;1mParameter ambiguous\x1b[0m"
    rows = [
        {"type": "user", "message": {"role": "user", "content": "run pester"},
         "uuid": "u1", "timestamp": "t", "sessionId": "x"},
        {"type": "assistant", "requestId": "r1",
         "message": {"id": "m1", "role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "PowerShell",
              "input": {"command": "Invoke-Pester"}}]},
         "uuid": "a1", "timestamp": "t", "sessionId": "x"},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": "t1", "type": "tool_result",
             "content": raw, "is_error": True}]},
         "uuid": "u2", "timestamp": "t", "sessionId": "x"},
    ]
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl",
                                     encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        tmp = f.name
    s = parse(tmp)
    dps = decision_points(s)
    assert len(dps) == 1
    assert "\x1b" not in dps[0].detail
    assert "[31;1m" not in dps[0].detail
    assert "Invoke-Pester" in dps[0].detail
    assert "ambiguous" in dps[0].detail


def test_decision_points_filters_benign_cache_hits():
    """Wizard's pretool_cache_hook returns is_error=true for cache short-circuits.
    Those are normal flow, not real errors — must not appear in decision points."""
    import json
    import tempfile
    rows = [
        {"type": "user", "message": {"role": "user", "content": "read it"},
         "uuid": "u1", "timestamp": "t", "sessionId": "x"},
        {"type": "assistant", "requestId": "r1",
         "message": {"id": "m1", "role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "/x/foo.py"}}]},
         "uuid": "a1", "timestamp": "t", "sessionId": "x"},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": "t1", "type": "tool_result",
             "content": "Cached tool result reused (tool_cache). Read call was memoized 5s ago.",
             "is_error": True}]},
         "uuid": "u2", "timestamp": "t", "sessionId": "x"},
    ]
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl",
                                     encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        tmp = f.name
    s = parse(tmp)
    dps = decision_points(s)
    assert not any(d.kind == "tool_error" for d in dps), \
        "benign cache short-circuit must not be flagged as a tool error"


def test_decision_points_does_not_falsely_flag_incidental_phrase():
    """If a Read result merely *contains* the rejection phrase (e.g., from
    reading a transcript file), it must NOT be flagged as tool_rejected."""
    import json
    import tempfile
    rows = [
        {"type": "user", "message": {"role": "user", "content": "read it"},
         "uuid": "u1", "timestamp": "t", "sessionId": "x"},
        {"type": "assistant", "requestId": "r1",
         "message": {"id": "m1", "role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "/x/log.txt"}}]},
         "uuid": "a1", "timestamp": "t", "sessionId": "x"},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": "t1", "type": "tool_result",
             "content": "log line: the user doesn't want to proceed with this tool use",
             "is_error": False}]},
         "uuid": "u2", "timestamp": "t", "sessionId": "x"},
    ]
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl",
                                     encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        tmp = f.name
    s = parse(tmp)
    dps = decision_points(s)
    assert not any(d.kind == "tool_rejected" for d in dps)


# --- heuristics: best span -----------------------------------------------

def test_best_span_in_tight_is_read_edit_verify():
    s = parse(FIX / "tight.jsonl")
    b = best_span(s)
    assert b is not None
    assert "verify" in b.note  # found the Bash post-edit
    assert b.pattern == ["Read", "Edit", "Bash"]


def test_best_span_none_when_no_edits():
    s = parse(FIX / "wandering.jsonl")
    b = best_span(s)
    assert b is None


# --- renderer ------------------------------------------------------------

def test_renderer_produces_all_sections():
    s = parse(FIX / "tight.jsonl")
    md = render(debrief(s))
    for header in (
        "## Goal & outcome",
        "## Reading economy",
        "## Exploration vs production",
        "## Decision points",
        "## Best span",
        "## Tools used",
    ):
        assert header in md, f"missing section: {header}"


def test_renderer_handles_empty_session_without_crashing():
    s = parse(FIX / "empty.jsonl")
    md = render(debrief(s))
    assert "No tool calls." in md or "No tool spans." in md


# --- thinking profile ----------------------------------------------------

def test_thinking_profile_handles_empty_session():
    s = parse(FIX / "empty.jsonl")
    tp = thinking_profile(s)
    assert tp.total_chars == 0
    assert tp.turns_with_thinking == 0
    assert tp.silent_tool_runs == 0
    assert tp.chars_per_tool_call == 0.0


def test_thinking_profile_counts_silent_tool_runs():
    """Tool-using turns with zero thinking should be counted as silent."""
    s = parse(FIX / "tight.jsonl")
    tp = thinking_profile(s)
    # tight fixture has 3 tool turns, none with thinking
    assert tp.silent_tool_runs == 3
    assert tp.total_chars == 0


def test_renderer_includes_thinking_section():
    s = parse(FIX / "tight.jsonl")
    md = render(debrief(s))
    assert "## Thinking density" in md


# --- end-to-end ----------------------------------------------------------

def test_debrief_top_level_is_internally_consistent():
    s = parse(FIX / "tight.jsonl")
    d = debrief(s)
    assert d.session_id == s.session_id
    assert d.n_turns == len(s.turns)
    # n_tools counts only those with results.
    completed = sum(1 for t in s.tool_uses if t.result_text is not None)
    assert d.n_tools == completed


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
