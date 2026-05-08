"""Parse a Claude Code .jsonl transcript into typed events.

The transcript schema is informal — observed kinds:
  - top-level type=="user": role=="user" message; content is str or list[part]
  - top-level type=="assistant": role=="assistant" message; content list of
    text/thinking/tool_use parts.
  - top-level type=="attachment": hook output, deferred-tool deltas, etc.
  - top-level type in {"permission-mode","last-prompt","file-history-snapshot"}: meta only.

A "user" message can be (a) the human's actual prompt, (b) a tool_result
the harness sent back to the assistant, or (c) command/output meta. We
distinguish them by inspecting content shape and well-known string prefixes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


META_USER_PREFIXES = (
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<task-notification>",
    "<system-reminder>",
)


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict
    line_no: int
    ts: str
    result_text: str | None = None
    result_error: bool = False
    result_line: int | None = None
    cancelled: bool = False


@dataclass
class UserPrompt:
    text: str
    line_no: int
    ts: str


@dataclass
class AssistantTurn:
    text: str
    thinking_chars: int
    tool_use_ids: list[str]
    line_no: int
    ts: str


@dataclass
class Session:
    session_id: str
    path: str
    prompts: list[UserPrompt] = field(default_factory=list)
    turns: list[AssistantTurn] = field(default_factory=list)
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_index: dict[str, ToolUse] = field(default_factory=dict)
    meta_lines: int = 0
    raw_lines: int = 0


def _content_text(content) -> str:
    """Best-effort flatten of a message.content into a single string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if not isinstance(part, dict):
                continue
            t = part.get("type")
            if t == "text":
                out.append(part.get("text", ""))
            elif t == "thinking":
                continue
            elif t == "tool_result":
                continue
        return "\n".join(out).strip()
    return ""


def _looks_like_meta_user(text: str) -> bool:
    s = text.lstrip()
    return any(s.startswith(p) for p in META_USER_PREFIXES)


def _tool_results_in_user(content) -> list[tuple[str, str, bool]]:
    """Return [(tool_use_id, result_text, is_error)] for a user message."""
    if not isinstance(content, list):
        return []
    out: list[tuple[str, str, bool]] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "tool_result":
            continue
        tid = part.get("tool_use_id", "")
        body = part.get("content", "")
        is_err = bool(part.get("is_error", False))
        if isinstance(body, list):
            chunks = []
            for sub in body:
                if isinstance(sub, dict) and sub.get("type") == "text":
                    chunks.append(sub.get("text", ""))
            body = "\n".join(chunks)
        elif not isinstance(body, str):
            body = json.dumps(body)
        out.append((tid, body, is_err))
    return out


def parse(path: str | Path) -> Session:
    p = Path(path)
    sess = Session(session_id=p.stem, path=str(p))

    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, start=1):
            sess.raw_lines += 1
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = obj.get("type")
            ts = obj.get("timestamp", "")

            if t in ("permission-mode", "last-prompt", "file-history-snapshot"):
                sess.meta_lines += 1
                continue

            if t == "attachment":
                # NOTE: attachment.type == "hook_cancelled" only means *a single hook*
                # in the PreToolUse chain declined to handle the call — the tool may
                # still run. We infer real cancellation post-hoc as "tool_use with no
                # result_text by end of file" in heuristics, not here.
                sess.meta_lines += 1
                continue

            msg = obj.get("message", {}) if isinstance(obj.get("message"), dict) else {}
            role = msg.get("role")

            if t == "user" and role == "user":
                if obj.get("isMeta"):
                    sess.meta_lines += 1
                    continue
                content = msg.get("content")
                tool_results = _tool_results_in_user(content)
                if tool_results:
                    for tid, body, is_err in tool_results:
                        tu = sess.tool_index.get(tid)
                        if tu is not None:
                            tu.result_text = body
                            tu.result_error = is_err
                            tu.result_line = line_no
                    continue
                text = _content_text(content)
                if not text or _looks_like_meta_user(text):
                    sess.meta_lines += 1
                    continue
                sess.prompts.append(UserPrompt(text=text, line_no=line_no, ts=ts))
                continue

            if t == "assistant" and role == "assistant":
                content = msg.get("content", [])
                text_parts: list[str] = []
                thinking_chars = 0
                tool_ids: list[str] = []
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        pt = part.get("type")
                        if pt == "text":
                            text_parts.append(part.get("text", ""))
                        elif pt == "thinking":
                            thinking_chars += len(part.get("thinking", "") or "")
                        elif pt == "tool_use":
                            tid = part.get("id", "")
                            name = part.get("name", "")
                            tool_input = part.get("input", {}) or {}
                            tu = ToolUse(
                                id=tid,
                                name=name,
                                input=tool_input if isinstance(tool_input, dict) else {},
                                line_no=line_no,
                                ts=ts,
                            )
                            sess.tool_uses.append(tu)
                            sess.tool_index[tid] = tu
                            tool_ids.append(tid)
                # Streaming-style transcripts repeat the same assistant message id
                # across multiple lines (one per content part). Collapse them so
                # we report one logical turn per request.
                req_id = obj.get("requestId") or msg.get("id")
                if sess.turns and req_id and getattr(sess.turns[-1], "_req", None) == req_id:
                    last = sess.turns[-1]
                    last.text = (last.text + "\n" + "\n".join(text_parts)).strip()
                    last.thinking_chars += thinking_chars
                    last.tool_use_ids.extend(tool_ids)
                else:
                    turn = AssistantTurn(
                        text="\n".join(text_parts).strip(),
                        thinking_chars=thinking_chars,
                        tool_use_ids=tool_ids,
                        line_no=line_no,
                        ts=ts,
                    )
                    setattr(turn, "_req", req_id)
                    sess.turns.append(turn)
                continue

            sess.meta_lines += 1

    return sess


def iter_sessions(directory: str | Path) -> Iterator[Session]:
    d = Path(directory)
    for p in sorted(d.glob("*.jsonl")):
        yield parse(p)
