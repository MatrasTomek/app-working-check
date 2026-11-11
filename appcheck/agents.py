"""Odczyt stanu sesji Claude Code z ~/.claude/projects/*/*.jsonl — wyłącznie metadane.

Nie zwracamy treści wiadomości, myśli ani wyników narzędzi (mogą zawierać sekrety i kod).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

TAIL_BYTES = 256 * 1024
MAX_SESSIONS = 50
RECENT_SECONDS = 24 * 3600
THINKING_SECONDS = 2 * 60  # ostatni wpis od użytkownika / wynik narzędzia — model pracuje
TOOL_SECONDS = 10 * 60  # ostatni wpis to wywołanie narzędzia — narzędzie się wykonuje
WAITING_SECONDS = 6 * 3600  # odpowiedź zakończona — czeka na Ciebie
MAX_TITLE = 80

WORKING, WAITING, IDLE = "pracuje", "czeka na Ciebie", "bezczynny"


@dataclass
class AgentSession:
    session_id: str
    project: str  # katalog roboczy (cwd) sesji
    branch: str | None
    title: str | None
    state: str
    last_activity: str  # ISO 8601
    last_tool: str | None
    pr_url: str | None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _read_tail(path: Path) -> list[dict]:
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        start = max(0, size - TAIL_BYTES)
        f.seek(start)
        data = f.read()
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # pierwszy wiersz może być ucięty
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _tool_names(entry: dict) -> list[str]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [b["name"] for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("name"), str)]


def _stop_reason(entry: dict) -> str | None:
    message = entry.get("message")
    return message.get("stop_reason") if isinstance(message, dict) else None


def _safe_pr_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    return url if parts.scheme == "https" and parts.netloc == "github.com" else None


def _clip(text: object, limit: int) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize(path: Path, entries: list[dict], now: datetime) -> AgentSession | None:
    title = pr_url = cwd = branch = last_tool = None
    last: dict | None = None
    last_ts: datetime | None = None
    for e in entries:
        kind = e.get("type")
        if kind == "ai-title":
            title = e.get("aiTitle") or title
        elif kind == "pr-link":
            pr_url = _safe_pr_url(e.get("prUrl")) or pr_url
        elif kind in ("user", "assistant") and not e.get("isSidechain"):
            ts = _parse_ts(e.get("timestamp"))
            if ts is None:
                continue
            last, last_ts = e, ts
            cwd = e.get("cwd") if isinstance(e.get("cwd"), str) else cwd
            branch = e.get("gitBranch") if isinstance(e.get("gitBranch"), str) else branch
            tools = _tool_names(e) if kind == "assistant" else []
            if tools:
                last_tool = tools[-1]
    if last is None or last_ts is None:
        return None
    age = (now - last_ts).total_seconds()
    if last.get("type") == "assistant" and _tool_names(last):
        state = WORKING if age < TOOL_SECONDS else IDLE
    elif last.get("type") == "assistant" and _stop_reason(last) in ("end_turn", "stop_sequence", None):
        state = WAITING if age < WAITING_SECONDS else IDLE
    else:
        state = WORKING if age < THINKING_SECONDS else IDLE
    return AgentSession(
        session_id=path.stem[:64],
        project=cwd or path.parent.name,
        branch=_clip(branch, 100),
        title=_clip(title, MAX_TITLE),
        state=state,
        last_activity=last_ts.isoformat(timespec="seconds"),
        last_tool=_clip(last_tool, 60),
        pr_url=pr_url,
    )


def scan_sessions(root: Path, now: datetime | None = None) -> list[AgentSession]:
    now = now or datetime.now(timezone.utc)
    try:
        root = root.resolve(strict=True)
    except OSError:
        return []
    candidates: list[tuple[float, Path]] = []
    for project_dir in root.iterdir():
        if project_dir.is_symlink() or not project_dir.is_dir():
            continue
        for path in project_dir.glob("*.jsonl"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now.timestamp() - mtime <= RECENT_SECONDS:
                candidates.append((mtime, path))
    candidates.sort(reverse=True)
    sessions = []
    for _, path in candidates[:MAX_SESSIONS]:
        try:
            summary = summarize(path, _read_tail(path), now)
        except OSError:
            continue
        if summary:
            sessions.append(summary)
    return sessions


def to_dict(session: AgentSession) -> dict:
    return asdict(session)
