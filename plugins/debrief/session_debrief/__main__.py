"""CLI for session_debrief.

Positional command form (preferred — easy from a slash command):
    python -m session_debrief                 # picker menu (prints recent + exit)
    python -m session_debrief last            # most-recent session
    python -m session_debrief last 5          # multi-session over last 5
    python -m session_debrief stats           # aggregate over every transcript
    python -m session_debrief list            # picker menu only
    python -m session_debrief <path.jsonl>    # specific transcript
    python -m session_debrief <session-id>    # by session-id prefix (8+ chars)

Flags (also accepted for back-compat):
    --last [N]                                same as `last [N]`
    --stats                                   same as `stats`
    --list                                    same as `list`

Common options:
    --out PATH        Write markdown to PATH (default: also auto-saves to ~/.claude/debriefs/<id>.md)
    --root DIR        Project root, shortens absolute paths in output
    --quiet           Suppress full markdown stdout; print just the saved-file path + 1-line summary
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import locator, multi
from .heuristics import Debrief, debrief
from .parser import parse
from .renderer import render, render_multi


DEFAULT_OUT_DIR = Path.home() / ".claude" / "debriefs"


def _stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def _write(md: str, out: Path | None, summary: str, quiet: bool) -> None:
    """Write to `out` (always when given), and either print full md to stdout
    or — if quiet — just a one-line summary."""
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
    _stdout_utf8()
    if quiet:
        if out is not None:
            print(f"{summary}  →  {out}")
        else:
            print(summary)
        return
    try:
        sys.stdout.write(md)
    except UnicodeEncodeError:
        sys.stdout.write(md.encode("ascii", "replace").decode("ascii"))
    if out is not None:
        sys.stdout.write(f"\n\n_(saved to {out})_\n")


def _summary(d: Debrief) -> str:
    return (
        f"session {d.session_id[:8]}: {d.n_turns} turns, {d.n_tools} tools, "
        f"signal={d.reading.signal_ratio:.0%}, wander={d.flow.wandering_score:.0%}, "
        f"verdict={d.goal.verdict}"
    )


def _multi_summary(m, label: str) -> str:
    return (
        f"{label}: {m.n_sessions} sessions, {m.total_turns:,} turns, "
        f"{m.total_tools:,} tools, avg_signal={m.avg_signal_ratio:.0%}, "
        f"avg_wander={m.avg_wandering:.0%}"
    )


def _resolve_session_id(token: str) -> Path | None:
    """Treat token as a session-id prefix; find a matching transcript."""
    if len(token) < 8:
        return None
    for ti in locator.list_transcripts():
        if ti.session_id.startswith(token):
            return ti.path
    return None


def _do_one(path: Path, root: str | None, out: Path | None, quiet: bool) -> int:
    s = parse(path)
    d = debrief(s)
    md = render(d, project_root=root)
    if out is None:
        out = DEFAULT_OUT_DIR / f"{d.session_id}.md"
    _write(md, out, _summary(d), quiet)
    return 0


def _do_multi(paths: list[Path], label: str, out: Path | None, quiet: bool) -> int:
    if not paths:
        print("no transcripts found", file=sys.stderr)
        return 1
    m = multi.aggregate(paths)
    md = render_multi(m, label=label)
    if out is None:
        slug = label.replace(" ", "-")
        out = DEFAULT_OUT_DIR / f"multi-{slug}.md"
    _write(md, out, _multi_summary(m, label), quiet)
    return 0


def _do_list() -> int:
    infos = locator.recent(20)
    print(locator.format_menu(infos))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="session_debrief",
        description="Generate a markdown retrospective of a Claude Code session.",
    )
    ap.add_argument(
        "args",
        nargs="*",
        help="Command + args: '', 'last', 'last N', 'stats', 'list', or a path/id",
    )
    ap.add_argument("--last", nargs="?", const=1, type=int, metavar="N",
                    help="Same as positional 'last [N]'")
    ap.add_argument("--stats", action="store_true",
                    help="Same as positional 'stats'")
    ap.add_argument("--list", dest="show_list", action="store_true",
                    help="Same as positional 'list'")
    ap.add_argument("--out", help="Write markdown here")
    ap.add_argument("--root", help="Project root for path-shortening in output")
    ap.add_argument("--quiet", action="store_true",
                    help="Print one-line summary instead of full markdown")
    args = ap.parse_args(argv)

    out = Path(args.out) if args.out else None

    # Flag forms (back-compat) — translate to positional intent.
    if args.show_list or (args.args and args.args[0].lower() == "list"):
        return _do_list()
    if args.stats or (args.args and args.args[0].lower() == "stats"):
        return _do_multi(
            [ti.path for ti in locator.list_transcripts()],
            label="all sessions",
            out=out,
            quiet=args.quiet,
        )

    n_last: int | None = None
    if args.last is not None:
        n_last = args.last
    elif args.args and args.args[0].lower() == "last":
        n_last = int(args.args[1]) if len(args.args) > 1 else 1

    if n_last is not None:
        infos = locator.recent(max(1, n_last))
        if not infos:
            print("no transcripts found", file=sys.stderr)
            return 1
        if n_last <= 1:
            return _do_one(infos[0].path, args.root, out, args.quiet)
        return _do_multi(
            [ti.path for ti in infos],
            label=f"last {len(infos)} sessions",
            out=out,
            quiet=args.quiet,
        )

    if not args.args:
        # Empty invocation → debrief the most-recent session (one-shot, no picker).
        infos = locator.recent(1)
        if not infos:
            print("no transcripts found", file=sys.stderr)
            return 1
        return _do_one(infos[0].path, args.root, out, args.quiet)

    token = args.args[0]
    p = Path(token)
    if p.exists():
        return _do_one(p, args.root, out, args.quiet)
    by_id = _resolve_session_id(token)
    if by_id is not None:
        return _do_one(by_id, args.root, out, args.quiet)
    print(f"unrecognized argument: {token!r}", file=sys.stderr)
    print("expected: last [N] | stats | list | <path.jsonl> | <session-id-prefix>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
