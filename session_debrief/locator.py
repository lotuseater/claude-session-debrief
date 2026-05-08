"""Find Claude Code transcript files on disk.

Claude Code stores conversation transcripts as JSONL under
``~/.claude/projects/<project-slug>/<session-uuid>.jsonl`` on every platform
it supports today. This module wraps that knowledge so callers don't have
to construct paths by hand.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .parser import parse


@dataclass
class TranscriptInfo:
    path: Path
    session_id: str
    project_slug: str
    mtime: float
    size: int
    first_prompt: str  # may be empty if the session has no real prompts


def transcripts_root() -> Path:
    """Return the directory under which all transcripts live."""
    return Path.home() / ".claude" / "projects"


def all_transcripts(root: Path | None = None) -> Iterator[Path]:
    """Yield every ``.jsonl`` transcript under the projects root."""
    base = Path(root) if root else transcripts_root()
    if not base.exists():
        return
    for project_dir in base.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            yield f


def _peek_first_prompt(path: Path, limit: int = 120) -> str:
    """Cheap-ish way to read the first user prompt without walking the whole file.

    We still parse end-to-end because the parser is fast and correctness
    matters more than micro-optimization. A future variant could short-circuit
    on the first prompt encountered, but ``parse()`` already streams the file.
    """
    try:
        s = parse(path)
    except Exception:
        return ""
    if not s.prompts:
        return ""
    text = s.prompts[0].text.strip().replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def list_transcripts(root: Path | None = None) -> list[TranscriptInfo]:
    """Return all transcripts, sorted by mtime descending (newest first)."""
    out: list[TranscriptInfo] = []
    for p in all_transcripts(root):
        try:
            stat = p.stat()
        except OSError:
            continue
        if stat.st_size == 0:
            continue
        out.append(
            TranscriptInfo(
                path=p,
                session_id=p.stem,
                project_slug=p.parent.name,
                mtime=stat.st_mtime,
                size=stat.st_size,
                first_prompt=_peek_first_prompt(p),
            )
        )
    out.sort(key=lambda ti: ti.mtime, reverse=True)
    return out


def most_recent(root: Path | None = None) -> TranscriptInfo | None:
    items = list_transcripts(root)
    return items[0] if items else None


def recent(n: int = 10, root: Path | None = None) -> list[TranscriptInfo]:
    return list_transcripts(root)[:n]


def format_menu(infos: list[TranscriptInfo]) -> str:
    """Render the recent-transcripts list as a plain-text picker menu."""
    if not infos:
        return "(no transcripts found in ~/.claude/projects/)"
    lines = []
    import datetime as _dt
    for i, ti in enumerate(infos, start=1):
        when = _dt.datetime.fromtimestamp(ti.mtime).strftime("%Y-%m-%d %H:%M")
        prompt = ti.first_prompt or "(no prompt)"
        lines.append(f"{i:>2}. {when}  [{ti.session_id[:8]}]  {prompt}")
    return "\n".join(lines)
