"""Tests for the locator and multi-session aggregation modules."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from session_debrief import locator, multi
from session_debrief.renderer import render_multi


FIX = Path(__file__).parent / "fixtures"


def _make_fake_root(tmp_path: Path, names: list[str]) -> Path:
    """Lay out a fake ~/.claude/projects with one project dir holding given fixtures."""
    proj = tmp_path / "C--Users-test"
    proj.mkdir(parents=True)
    for name in names:
        src = FIX / name
        dst = proj / name.replace(".jsonl", "-session.jsonl")
        shutil.copy(src, dst)
    return tmp_path


# --- locator -------------------------------------------------------------

def test_list_transcripts_returns_newest_first(tmp_path):
    root = _make_fake_root(tmp_path, ["tight.jsonl", "wandering.jsonl", "errored.jsonl"])
    infos = locator.list_transcripts(root)
    assert len(infos) == 3
    # Newest first => mtimes monotonically non-increasing.
    times = [i.mtime for i in infos]
    assert times == sorted(times, reverse=True)


def test_list_transcripts_skips_zero_byte_files(tmp_path):
    root = _make_fake_root(tmp_path, ["tight.jsonl", "empty.jsonl"])
    infos = locator.list_transcripts(root)
    # empty.jsonl should be skipped because it's 0 bytes.
    assert len(infos) == 1
    assert "tight" in infos[0].path.name


def test_most_recent_returns_none_for_empty_root(tmp_path):
    assert locator.most_recent(tmp_path) is None


def test_format_menu_handles_empty_list():
    assert "no transcripts" in locator.format_menu([]).lower()


def test_first_prompt_peek_extracts_real_user_text(tmp_path):
    root = _make_fake_root(tmp_path, ["tight.jsonl"])
    infos = locator.list_transcripts(root)
    assert "docstring" in infos[0].first_prompt.lower()


# --- multi ---------------------------------------------------------------

def test_aggregate_handles_empty_input():
    m = multi.aggregate([])
    assert m.n_sessions == 0
    assert m.total_turns == 0
    md = render_multi(m, label="empty")
    assert "no sessions" in md.lower()


def test_aggregate_combines_two_sessions(tmp_path):
    root = _make_fake_root(tmp_path, ["tight.jsonl", "wandering.jsonl"])
    paths = [i.path for i in locator.list_transcripts(root)]
    m = multi.aggregate(paths)
    assert m.n_sessions == 2
    assert m.total_tools >= 1
    # The verdicts dict should sum to n_sessions.
    assert sum(m.verdicts.values()) == 2
    md = render_multi(m, label="last 2 sessions")
    assert "Multi-Session Debrief" in md
    assert "## Averages" in md


def test_repeat_reads_only_lists_files_in_2plus_sessions(tmp_path):
    """In our fixtures each session reads different paths, so repeat_reads is empty."""
    root = _make_fake_root(tmp_path, ["tight.jsonl", "wandering.jsonl"])
    paths = [i.path for i in locator.list_transcripts(root)]
    m = multi.aggregate(paths)
    # No file appears in both fixtures, so the list should be empty.
    assert m.repeat_reads == []


def test_repeat_reads_finds_overlap_when_present(tmp_path):
    """Two synthesized sessions both reading /shared/x.py should show in repeat_reads."""
    rows = lambda sid: [
        {"type": "user", "message": {"role": "user", "content": "go"},
         "uuid": f"u-{sid}", "timestamp": "t", "sessionId": sid},
        {"type": "assistant", "requestId": f"r-{sid}",
         "message": {"id": f"m-{sid}", "role": "assistant", "content": [
             {"type": "tool_use", "id": f"t-{sid}", "name": "Read",
              "input": {"file_path": "/shared/x.py"}}]},
         "uuid": f"a-{sid}", "timestamp": "t", "sessionId": sid},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": f"t-{sid}", "type": "tool_result",
             "content": "...", "is_error": False}]},
         "uuid": f"u2-{sid}", "timestamp": "t", "sessionId": sid},
    ]
    proj = tmp_path / "proj"
    proj.mkdir()
    for sid in ("aaa", "bbb"):
        with (proj / f"{sid}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows(sid):
                f.write(json.dumps(r) + "\n")
    paths = list((tmp_path / "proj").glob("*.jsonl"))
    m = multi.aggregate(paths)
    assert m.n_sessions == 2
    assert any("x.py" in p for p, _ in m.repeat_reads)
