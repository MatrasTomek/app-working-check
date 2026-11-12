"""Sesje GitHub Copilot: Copilot CLI (~/.copilot/session-state) i Copilot Chat w VS Code — tylko metadane.

Tak jak dla Claude Code nie zwracamy treści wiadomości, odpowiedzi ani wyników narzędzi.

Copilot CLI nie zapisuje PID-u sesji tak jak Claude Code. Działający proces rozpoznajemy w /proc:
proces musi należeć do nas, być programem `copilot` i mieć otwarty plik z katalogu sesji
(albo sesja ma plik `inuse.<pid>.lock` z PID-em takiego procesu). Kill wysyła SIGTERM przez pidfd
i przed wysłaniem jeszcze raz sprawdza czas startu i nazwę programu.

Copilot Chat działa wewnątrz VS Code (extension host), więc nie ma własnego procesu i nie da się
go zakończyć. Pokazujemy rozmowy z ostatnich godzin z workspaceStorage/<hash>/chatSessions/.
"""
from __future__ import annotations

import json
import os
import re
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from appcheck import agents
from appcheck.agents import IDLE, WAITING, WORKING, AgentSession

MAX_WORKSPACE_FILE = 64 * 1024
MAX_CHAT_FILE = 32 * 1024 * 1024
MAX_FDS = 4096
LOCK_RE = re.compile(r"^inuse\.(\d+)\.lock$")
COPILOT_SCRIPT_SUFFIXES = ("/@github/copilot/index.js", "/@github/copilot/npm-loader.js")

# ResponseModelState z VS Code (chatService.ts)
PENDING, COMPLETE, CANCELLED, FAILED, NEEDS_INPUT = 0, 1, 2, 3, 4


# --- Copilot CLI: procesy ------------------------------------------------------------------------

@dataclass(frozen=True)
class CopilotProcess:
    pid: int
    proc_start: str


def _proc(proc_root: Path | None) -> Path:
    return proc_root or agents.PROC_ROOT


def is_copilot_process(pid: int, proc_root: Path | None = None) -> bool:
    """Proces należy do bieżącego użytkownika i jest programem Copilot CLI."""
    d = _proc(proc_root) / str(pid)
    try:
        if d.stat().st_uid != os.getuid():
            return False
        argv = (d / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    args = [a.decode("utf-8", "replace") for a in argv[:3] if a]
    if not args:
        return False
    if os.path.basename(args[0]) == "copilot":
        return True
    # node /…/@github/copilot/index.js
    return (os.path.basename(args[0]) in ("node", "nodejs") and len(args) > 1
            and (args[1].endswith(COPILOT_SCRIPT_SUFFIXES) or os.path.basename(args[1]) == "copilot"))


def _session_of(target: str, state_dir: str) -> str | None:
    if not target.startswith(state_dir + os.sep):
        return None
    sid = target[len(state_dir) + 1:].split(os.sep, 1)[0]
    return sid if agents.SESSION_ID_RE.match(sid) else None


def live_cli_processes(state_dir: Path, proc_root: Path | None = None) -> dict[str, CopilotProcess]:
    """sessionId → działający proces Copilot CLI."""
    try:
        state = str(state_dir.resolve(strict=True))
    except OSError:
        return {}
    root = _proc(proc_root)
    live: dict[str, CopilotProcess] = {}

    def add(sid: str, pid: int) -> None:
        start = agents.proc_start_time(pid, proc_root)
        if start and sid not in live:
            live[sid] = CopilotProcess(pid, start)

    try:
        pids = [int(p.name) for p in root.iterdir() if p.name.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        if pid <= 1 or pid == os.getpid() or not is_copilot_process(pid, proc_root):
            continue
        try:
            fds = list((root / str(pid) / "fd").iterdir())[:MAX_FDS]
        except OSError:
            continue
        for fd in fds:
            try:
                sid = _session_of(os.readlink(fd), state)
            except OSError:
                continue
            if sid:
                add(sid, pid)
    # pliki inuse.<pid>.lock (o ile CLI je tworzy) — PID i tak musi wskazywać na proces copilot
    try:
        dirs = [d for d in Path(state).iterdir() if not d.is_symlink() and d.is_dir()]
    except OSError:
        dirs = []
    for d in dirs:
        if not agents.SESSION_ID_RE.match(d.name) or d.name in live:
            continue
        try:
            locks = [m for f in d.iterdir() if (m := LOCK_RE.match(f.name))]
        except OSError:
            continue
        for m in locks:
            pid = int(m.group(1))
            if 1 < pid != os.getpid() and is_copilot_process(pid, proc_root):
                add(d.name, pid)
                break
    return live


def kill_cli_session(session_id: str, state_dir: Path, proc_root: Path | None = None) -> int | None:
    """SIGTERM do procesu sesji Copilot CLI. Zwraca PID albo None, gdy sesja nie działa."""
    if not isinstance(session_id, str) or not agents.SESSION_ID_RE.match(session_id):
        return None
    proc = live_cli_processes(state_dir, proc_root).get(session_id)
    if proc is None:
        return None
    try:
        fd = os.pidfd_open(proc.pid)
    except OSError:
        return None
    try:
        # pidfd wskazuje konkretny proces — sprawdzamy, że to wciąż ten sam copilot
        if (agents.proc_start_time(proc.pid, proc_root) != proc.proc_start
                or not is_copilot_process(proc.pid, proc_root)):
            return None
        signal.pidfd_send_signal(fd, signal.SIGTERM)
    except OSError:
        return None
    finally:
        os.close(fd)
    return proc.pid


# --- Copilot CLI: sesje --------------------------------------------------------------------------

def _ts(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc)  # milisekundy
        except (OverflowError, OSError, ValueError):
            return None
    return agents._parse_ts(value)


def _read_workspace(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_WORKSPACE_FILE:
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_line(value: object) -> str | None:
    return value.strip().splitlines()[0] if isinstance(value, str) and value.strip() else None


def summarize_cli(session_dir: Path, entries: list[dict], workspace: dict, mtime: float,
                  now: datetime) -> AgentSession:
    last_type = last_tool = None
    last_ts: datetime | None = None
    cwd = workspace.get("cwd") if isinstance(workspace.get("cwd"), str) else None
    open_tools: set[str] = set()
    for e in entries:
        kind = e.get("type")
        if not isinstance(kind, str):
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        context = data.get("context") if isinstance(data.get("context"), dict) else {}
        if cwd is None and isinstance(context.get("cwd"), str):
            cwd = context["cwd"]
        call_id = data.get("toolCallId")
        if kind == "tool.execution_start":
            if isinstance(data.get("toolName"), str):
                last_tool = data["toolName"]
            if isinstance(call_id, str):
                open_tools.add(call_id)
        elif kind == "tool.execution_complete" and isinstance(call_id, str):
            open_tools.discard(call_id)
        elif kind == "assistant.turn_end":
            open_tools.clear()
        if kind.startswith(("user.", "assistant.", "tool.", "session.")):
            last_type = kind
            last_ts = _ts(e.get("timestamp")) or last_ts
    last_ts = last_ts or datetime.fromtimestamp(mtime, timezone.utc)
    age = (now - last_ts).total_seconds()
    if open_tools:
        state = WORKING if age < agents.TOOL_SECONDS else IDLE
    elif last_type is None or last_type == "assistant.turn_end" or last_type.startswith("session."):
        state = WAITING if age < agents.WAITING_SECONDS else IDLE
    else:
        state = WORKING if age < agents.THINKING_SECONDS else IDLE
    return AgentSession(
        session_id=session_dir.name,
        project=cwd or "Copilot CLI",
        branch=agents._clip(workspace.get("branch"), 100),
        title=agents._clip(_first_line(workspace.get("name")) or _first_line(workspace.get("summary")),
                           agents.MAX_TITLE),
        state=state,
        last_activity=last_ts.isoformat(timespec="seconds"),
        last_tool=agents._clip(last_tool, 60),
        pr_url=None,
        agent="copilot-cli",
    )


def scan_cli_sessions(state_dir: Path, live: dict[str, CopilotProcess],
                      now: datetime | None = None) -> list[AgentSession]:
    """Sesje Copilot CLI, które mają działający proces."""
    now = now or datetime.now(timezone.utc)
    if not live:
        return []
    try:
        root = state_dir.resolve(strict=True)
    except OSError:
        return []
    sessions = []
    for sid in sorted(live)[:agents.MAX_SESSIONS]:
        d = root / sid
        events = d / "events.jsonl"
        try:
            if d.is_symlink() or not d.is_dir() or events.is_symlink() or not events.is_file():
                continue
            mtime = events.stat().st_mtime
            entries = agents._read_tail(events)
        except OSError:
            continue
        sessions.append(summarize_cli(d, entries, _read_workspace(d / "workspace.yaml"), mtime, now))
    return sessions


# --- Copilot Chat (VS Code) ----------------------------------------------------------------------

def _walk(state: object, path: list) -> tuple[object, object] | None:
    """Rodzic ostatniego elementu ścieżki i ten element (albo None, gdy ścieżka nie pasuje)."""
    if not path:
        return None
    node = state
    for key in path[:-1]:
        node = _child(node, key)
        if node is None:
            return None
    last = path[-1]
    if isinstance(node, dict) and isinstance(last, str):
        return node, last
    if (isinstance(node, list) and isinstance(last, int) and not isinstance(last, bool)
            and 0 <= last <= len(node)):
        return node, last
    return None


def _child(node: object, key: object) -> object:
    if isinstance(node, dict) and isinstance(key, str):
        return node.get(key)
    if isinstance(node, list) and isinstance(key, int) and not isinstance(key, bool) and 0 <= key < len(node):
        return node[key]
    return None


def _set(parent: dict | list, key: str | int, value: object) -> None:
    if isinstance(parent, dict) or key < len(parent):
        parent[key] = value
    else:
        parent.append(value)  # key == len(parent)


def apply_mutation_log(lines: list[bytes]) -> dict | None:
    """Odtwarza stan sesji z dziennika zmian VS Code (objectMutationLog.ts: 0 Initial, 1 Set, 2 Push, 3 Delete)."""
    state: object = None
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(entry, dict):
            continue
        kind, path = entry.get("kind"), entry.get("k")
        if kind == 0:
            state = entry.get("v")
            continue
        if state is None or not isinstance(path, list):
            continue
        where = _walk(state, path)
        if where is None:
            continue
        parent, key = where
        if kind in (1, 3):
            _set(parent, key, entry.get("v") if kind == 1 else None)
        elif kind == 2:
            arr = _child(parent, key)
            if not isinstance(arr, list):
                arr = []
                _set(parent, key, arr)
            i = entry.get("i")
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(arr):
                del arr[i:]
            values = entry.get("v")
            if isinstance(values, list):
                arr.extend(values)
    return state if isinstance(state, dict) else None


def _uri_path(uri: object) -> str | None:
    if not isinstance(uri, str):
        return None
    parts = urlsplit(uri)
    if parts.scheme in ("file", "vscode-remote") and parts.path:
        return unquote(parts.path)
    return None


def _workspace_folder(storage: Path) -> str | None:
    path = storage / "workspace.json"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_WORKSPACE_FILE:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return _uri_path(data.get("folder")) if isinstance(data, dict) else None


def summarize_chat(session_id: str, data: dict, project: str | None, mtime: float,
                   now: datetime) -> AgentSession | None:
    requests = [r for r in data.get("requests") or [] if isinstance(r, dict)] \
        if isinstance(data.get("requests"), list) else []
    if not requests:
        return None
    last = requests[-1]
    model_state = last.get("modelState") if isinstance(last.get("modelState"), dict) else {}
    value = model_state.get("value")
    times = [t for t in (_ts(last.get("timestamp")), _ts(last.get("responseTimestamp")),
                         _ts(model_state.get("completedAt"))) if t]
    last_ts = max(times) if times else datetime.fromtimestamp(mtime, timezone.utc)
    age = (now - last_ts).total_seconds()
    if value == PENDING:
        state = WORKING if age < agents.TOOL_SECONDS else IDLE
    else:
        state = WAITING if age < agents.WAITING_SECONDS else IDLE
    last_tool = None
    response = last.get("response") if isinstance(last.get("response"), list) else []
    for part in reversed(response):
        if isinstance(part, dict) and part.get("kind") == "toolInvocationSerialized":
            last_tool = part.get("toolId")
            break
    title = data.get("customTitle") or data.get("computedTitle")
    return AgentSession(
        session_id=session_id,
        project=_uri_path(data.get("workingDirectory")) or project or "VS Code",
        branch=None,
        title=agents._clip(title, agents.MAX_TITLE),
        state=state,
        last_activity=last_ts.isoformat(timespec="seconds"),
        last_tool=agents._clip(last_tool, 60),
        pr_url=None,
        agent="copilot-chat",
        can_kill=False,
    )


def _read_chat(path: Path) -> dict | None:
    data = path.read_bytes()
    if path.suffix == ".jsonl":
        return apply_mutation_log(data.split(b"\n"))
    try:
        parsed = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def scan_chat_sessions(storage_dirs: tuple[Path, ...], now: datetime | None = None) -> list[AgentSession]:
    """Rozmowy Copilot Chat z ostatnich godzin (aktywne albo czekające na odpowiedź)."""
    now = now or datetime.now(timezone.utc)
    candidates: dict[tuple[Path, str], tuple[float, Path, Path]] = {}
    for root in storage_dirs:
        try:
            root = root.resolve(strict=True)
            workspaces = [w for w in root.iterdir() if not w.is_symlink() and w.is_dir()]
        except OSError:
            continue
        for ws in workspaces:
            chat_dir = ws / "chatSessions"
            if chat_dir.is_symlink() or not chat_dir.is_dir():
                continue
            try:
                files = [*chat_dir.glob("*.jsonl"), *chat_dir.glob("*.json")]
            except OSError:
                continue
            for path in files:
                if not agents.SESSION_ID_RE.match(path.stem):
                    continue
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    st = path.stat()
                except OSError:
                    continue
                if st.st_size > MAX_CHAT_FILE or now.timestamp() - st.st_mtime > agents.WAITING_SECONDS:
                    continue
                key = (ws, path.stem)
                if key in candidates and candidates[key][1].suffix == ".jsonl":
                    continue  # VS Code czyta najpierw .jsonl, potem .json
                candidates[key] = (st.st_mtime, path, ws)
    sessions = []
    for mtime, path, ws in sorted(candidates.values(), reverse=True)[:agents.MAX_SESSIONS]:
        try:
            data = _read_chat(path)
        except OSError:
            continue
        summary = summarize_chat(path.stem, data, _workspace_folder(ws), mtime, now) if data else None
        if summary and summary.state != IDLE:
            sessions.append(summary)
    return sessions
