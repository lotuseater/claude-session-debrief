"""CLI for session_debrief.

Usage:
    python -m session_debrief <path.jsonl>      # debrief a specific transcript
    python -m session_debrief --last            # debrief the most-recent session
    python -m session_debrief --last 5          # multi-session aggregate over last 5
    python -m session_debrief --stats           # aggregate over every transcript on disk
    python -m session_debrief --list            # print the picker menu, no debrief

Options:
    --out PATH    Write markdown to PATH instead of stdout.
    --root DIR    Project root, used to shorten absolute file paths in output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import locator, multi
from .heuristics import debrief
from .parser import parse
from .renderer import render, render_multi


def _write_or_print(md: str, out: str | None) -> None:
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"wrote {out}")
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    try:
        sys.stdout.write(md)
    except UnicodeEncodeError:
        sys.stdout.write(md.encode("ascii", "replace").decode("ascii"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="session_debrief")
    ap.add_argument(
        "transcript",
        nargs="?",
        help="Path to a Claude Code .jsonl transcript (omit with --last/--stats/--list)",
    )
    ap.add_argument(
        "--last",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="Debrief the most-recent session, or aggregate over the last N",
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help="Aggregate across every transcript on disk",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="Print the recent-transcripts picker menu and exit",
    )
    ap.add_argument("--out", help="Write markdown here (default: stdout)")
    ap.add_argument(
        "--root",
        help="Project root used to shorten file paths in output",
    )
    args = ap.parse_args(argv)

    if args.list:
        infos = locator.recent(20)
        print(locator.format_menu(infos))
        return 0

    if args.stats:
        all_paths = [ti.path for ti in locator.list_transcripts()]
        if not all_paths:
            print("no transcripts found", file=sys.stderr)
            return 1
        report = multi.aggregate(all_paths)
        _write_or_print(render_multi(report, label="all sessions"), args.out)
        return 0

    if args.last is not None:
        infos = locator.recent(max(1, args.last))
        if not infos:
            print("no transcripts found", file=sys.stderr)
            return 1
        if args.last <= 1:
            s = parse(infos[0].path)
            md = render(debrief(s), project_root=args.root)
        else:
            report = multi.aggregate([ti.path for ti in infos])
            md = render_multi(report, label=f"last {len(infos)} sessions")
        _write_or_print(md, args.out)
        return 0

    if not args.transcript:
        ap.error("provide a transcript path, or use --last / --stats / --list")
    p = Path(args.transcript)
    if not p.exists():
        print(f"transcript not found: {p}", file=sys.stderr)
        return 2
    s = parse(p)
    md = render(debrief(s), project_root=args.root)
    _write_or_print(md, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
