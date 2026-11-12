import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from appcheck import agents, copilot
from appcheck.agents import IDLE, WAITING, WORKING, proc_start_time

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
SECRET = "SEKRETNA-TRESC-haslo-123"
SID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def ms(minutes_ago):
    return int((NOW - timedelta(minutes=minutes_ago)).timestamp() * 1000)


def ev(kind, minutes_ago, **data):
    return {"type": kind, "id": f"{kind}-{minutes_ago}", "timestamp": iso(minutes_ago), "data": data}


def cli_session(state_dir, sid, events, workspace=None, mtime=NOW):
    d = state_dir / sid
    d.mkdir(parents=True, exist_ok=True)
    p = d / "events.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    os.utime(p, (mtime.timestamp(), mtime.timestamp()))
    if workspace is not None:
        (d / "workspace.yaml").write_text(workspace, encoding="utf-8")
    return d


def fake_proc(proc_root, pid, argv, start=5000, fds=()):
    d = proc_root / str(pid)
    d.mkdir(parents=True)
    fields = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 10
    (d / "stat").write_text(f"{pid} (x) " + " ".join(fields) + "\n", encoding="ascii")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "fd").mkdir()
    for n, target in enumerate(fds):
        (d / "fd" / str(n)).symlink_to(target)


# --- Copilot CLI: procesy --------------------------------------------------------------------------

def test_recognizes_copilot_processes(tmp_path):
    fake_proc(tmp_path, 10, ["/usr/bin/copilot", "--resume"])
    fake_proc(tmp_path, 11, ["node", "/usr/lib/node_modules/@github/copilot/index.js"])
    fake_proc(tmp_path, 12, ["/usr/bin/node", "/home/x/.local/bin/copilot"])
    fake_proc(tmp_path, 13, ["bash", "-c", "copilot"])
    fake_proc(tmp_path, 14, ["/usr/bin/copilot-agent"])
    fake_proc(tmp_path, 15, [])
    assert [p for p in range(10, 17) if copilot.is_copilot_process(p, tmp_path)] == [10, 11, 12]


def test_live_cli_processes_from_open_files_and_lock(tmp_path):
    state, proc = tmp_path / "session-state", tmp_path / "proc"
    for sid in (SID, "druga", "obca", "z-lockiem", "zly-lock"):
        cli_session(state, sid, [])
    (state / "z-lockiem" / "inuse.20.lock").write_text("")
    (state / "zly-lock" / "inuse.30.lock").write_text("")
    outside = tmp_path / "gdzie-indziej.txt"
    outside.write_text("")
    fake_proc(proc, 10, ["copilot"], start=111, fds=[state / SID / "events.jsonl", outside])
    fake_proc(proc, 11, ["copilot"], start=222, fds=[state / "druga" / "workspace.yaml"])
    fake_proc(proc, 12, ["vim"], fds=[state / "obca" / "events.jsonl"])  # nie copilot
    fake_proc(proc, 13, ["copilot"], fds=[state / ".." / "x"])
    fake_proc(proc, 20, ["copilot"], start=333)
    fake_proc(proc, 30, ["sleep", "60"])  # lock wskazuje na inny program
    live = copilot.live_cli_processes(state, proc)
    assert live == {SID: copilot.CopilotProcess(10, "111"), "druga": copilot.CopilotProcess(11, "222"),
                    "z-lockiem": copilot.CopilotProcess(20, "333")}
    assert copilot.live_cli_processes(tmp_path / "brak", proc) == {}


@pytest.fixture
def copilot_like(tmp_path):
    """Prawdziwy proces o nazwie `copilot`, który trzyma otwarty plik sesji."""
    state = tmp_path / "session-state"
    events = cli_session(state, SID, [ev("user.message", 0.5, content=SECRET)]) / "events.jsonl"
    proc = subprocess.Popen(["bash", "-c", 'exec 3<"$1"; exec -a copilot sleep 60', "_", str(events)])
    yield state, proc
    proc.kill()
    proc.wait()


def wait_live(state, sid):
    for _ in range(50):
        if sid in copilot.live_cli_processes(state):
            return True
        subprocess.run(["sleep", "0.05"])
    return False


def test_kill_cli_session(copilot_like):
    state, proc = copilot_like
    assert wait_live(state, SID)
    assert copilot.kill_cli_session("../" + SID, state) is None
    assert copilot.kill_cli_session("inna", state) is None
    assert proc.poll() is None
    assert copilot.kill_cli_session(SID, state) == proc.pid
    assert proc.wait(5) == -15
    assert copilot.kill_cli_session(SID, state) is None


def test_kill_rechecks_program_before_signal(copilot_like, monkeypatch):
    state, proc = copilot_like
    assert wait_live(state, SID)
    found = copilot.live_cli_processes(state)
    # między wyszukaniem a sygnałem proces przestał być copilotem (np. PID użyty ponownie) — nie zabijamy
    monkeypatch.setattr(copilot, "live_cli_processes", lambda s, p=None: found)
    monkeypatch.setattr(copilot, "is_copilot_process", lambda pid, proc_root=None: False)
    assert copilot.kill_cli_session(SID, state) is None
    assert proc.poll() is None


# --- Copilot CLI: sesje ----------------------------------------------------------------------------

WORKSPACE = f"""id: {SID}
cwd: /home/x/proj
branch: DA-13
name: |
  Dodanie   Copilota
  druga linia
summary: stary opis
"""


def scan(state, sids, now=NOW):
    live = {sid: copilot.CopilotProcess(1, "1") for sid in sids}
    return {s.session_id: s for s in copilot.scan_cli_sessions(state, live, now=now)}


def test_cli_states_and_metadata(tmp_path):
    cli_session(tmp_path, "tool", [ev("session.start", 30, context={"cwd": "/z/kontekstu"}),
                                   ev("user.message", 20, content=SECRET),
                                   ev("tool.execution_start", 1, toolName="bash", toolCallId="c1",
                                      arguments={"command": SECRET})], workspace=WORKSPACE)
    cli_session(tmp_path, "waiting", [ev("user.message", 30, content=SECRET),
                                      ev("tool.execution_start", 25, toolName="view", toolCallId="c1"),
                                      ev("tool.execution_complete", 24, toolName="view", toolCallId="c1",
                                         result={"content": SECRET}),
                                      ev("assistant.message", 21, content=SECRET),
                                      ev("assistant.turn_end", 20)])
    cli_session(tmp_path, "thinking", [ev("user.message", 0.5, content=SECRET)])
    cli_session(tmp_path, "stale-tool", [ev("tool.execution_start", 60, toolName="bash", toolCallId="c")])
    cli_session(tmp_path, "fresh", [ev("session.start", 1)], workspace="summary: Tylko summary\n")
    cli_session(tmp_path, "no-ts", [{"type": "user.message", "data": {}}], mtime=NOW - timedelta(minutes=30))
    got = scan(tmp_path, ["tool", "waiting", "thinking", "stale-tool", "fresh", "no-ts", "nie-ma"])
    assert set(got) == {"tool", "waiting", "thinking", "stale-tool", "fresh", "no-ts"}
    t = got["tool"]
    assert (t.state, t.last_tool, t.project, t.branch, t.title) == (WORKING, "bash", "/home/x/proj", "DA-13",
                                                                   "Dodanie Copilota")
    assert t.agent == "copilot-cli" and t.can_kill
    assert got["waiting"].state == WAITING and got["waiting"].last_tool == "view"
    assert got["waiting"].project == "Copilot CLI"
    assert got["thinking"].state == WORKING
    assert got["stale-tool"].state == IDLE
    assert got["fresh"].state == WAITING and got["fresh"].title == "Tylko summary"
    assert got["no-ts"].state == IDLE and got["no-ts"].last_activity == iso(30).replace("Z", "+00:00")
    assert SECRET not in json.dumps([agents.to_dict(s) for s in got.values()])


def test_cli_ignores_symlinks_bad_yaml_and_garbage(tmp_path):
    state = tmp_path / "state"
    outside = cli_session(tmp_path / "outside", "x", [ev("user.message", 0.5)])
    state.mkdir()
    (state / "link").symlink_to(outside, target_is_directory=True)
    d = cli_session(state, "garbage", [], workspace="name: [niedomknięte\n")
    (d / "events.jsonl").write_bytes(b"\xff\xfe nie json\n[]\n{\"type\": 5}\n")
    d2 = cli_session(state, "link-events", [])
    (d2 / "events.jsonl").unlink()
    (d2 / "events.jsonl").symlink_to(outside / "events.jsonl")
    got = scan(state, ["link", "garbage", "link-events"])
    assert set(got) == {"garbage"} and got["garbage"].title is None
    assert copilot.scan_cli_sessions(state, {}) == []


# --- Copilot Chat ----------------------------------------------------------------------------------

def request(minutes_ago, state=1, tool=None):
    response = [{"kind": "markdownContent", "content": {"value": SECRET}}]
    if tool:
        response.append({"kind": "toolInvocationSerialized", "toolId": tool, "resultDetails": SECRET})
    model_state = {"value": state, **({"completedAt": ms(minutes_ago)} if state in (1, 2, 3) else {})}
    return {"requestId": f"r{minutes_ago}", "timestamp": ms(minutes_ago + 1), "message": {"text": SECRET},
            "response": response, "modelState": model_state}


def chat(storage, ws, sid, content, suffix=".jsonl", folder=None, mtime=NOW):
    d = storage / ws / "chatSessions"
    d.mkdir(parents=True, exist_ok=True)
    if folder:
        (storage / ws / "workspace.json").write_text(json.dumps({"folder": folder}), encoding="utf-8")
    p = d / f"{sid}{suffix}"
    if suffix == ".jsonl":
        p.write_text("\n".join(json.dumps(e) for e in content) + "\n", encoding="utf-8")
    else:
        p.write_text(json.dumps(content), encoding="utf-8")
    os.utime(p, (mtime.timestamp(), mtime.timestamp()))
    return p


def test_mutation_log():
    lines = [json.dumps(e).encode() for e in [
        {"kind": 1, "k": ["x"], "v": 1},  # przed Initial — pomijane
        {"kind": 0, "v": {"requests": [{"a": 1}, {"a": 2}, {"a": 3}], "customTitle": "stary"}},
        {"kind": 1, "k": ["customTitle"], "v": "nowy"},
        {"kind": 2, "k": ["requests"], "i": 1, "v": [{"a": 9}]},
        {"kind": 2, "k": ["requests"], "v": [{"a": 10}]},
        {"kind": 1, "k": ["requests", 1, "modelState"], "v": {"value": 1}},
        {"kind": 2, "k": ["requests", 0, "response"], "v": [{"kind": "x"}]},
        {"kind": 3, "k": ["customTitle"]},
        {"kind": 1, "k": ["requests", 99, "x"], "v": 1},  # zła ścieżka — pomijana
        {"kind": 1, "k": ["requests", "x"], "v": 1},
        {"kind": 1, "k": [], "v": 1},
    ]] + [b"nie json", b"[]"]
    state = copilot.apply_mutation_log(lines)
    assert state == {"requests": [{"a": 1, "response": [{"kind": "x"}]}, {"a": 9, "modelState": {"value": 1}},
                                  {"a": 10}], "customTitle": None}
    later = [*lines, json.dumps({"kind": 0, "v": {"requests": []}}).encode()]
    assert copilot.apply_mutation_log(later) == {"requests": []}
    assert copilot.apply_mutation_log([b'{"kind": 0, "v": []}']) is None


def test_chat_sessions(tmp_path):
    storage = tmp_path / "workspaceStorage"
    initial = {"version": 3, "sessionId": "a", "requests": [request(30)]}
    chat(storage, "ws1", "aktywna", [{"kind": 0, "v": initial},
                                    {"kind": 2, "k": ["requests"], "v": [request(1, state=0, tool="runInTerminal")]},
                                    {"kind": 1, "k": ["customTitle"], "v": "Naprawa   logowania"}],
         folder="vscode-remote://wsl%2Bubuntu/home/x/m%C3%B3j-projekt")
    chat(storage, "ws1", "czeka", {"version": 2, "computedTitle": "Stara wersja", "requests": [request(20)],
                                   "workingDirectory": "file:///home/x/inny"}, suffix=".json")
    chat(storage, "ws2", "dwa-formaty", {"requests": [request(5)], "customTitle": "z json"}, suffix=".json")
    chat(storage, "ws2", "dwa-formaty", [{"kind": 0, "v": {"requests": [request(5)], "customTitle": "z jsonl"}}])
    chat(storage, "ws2", "zawieszona", [{"kind": 0, "v": {"requests": [request(60, state=0)]}}])
    chat(storage, "ws2", "dawna", [{"kind": 0, "v": {"requests": [request(600)]}}],
         mtime=NOW - timedelta(hours=10))
    chat(storage, "ws2", "pusta", [{"kind": 0, "v": {"requests": []}}])
    chat(storage, "ws2", "zla..nazwa", [{"kind": 0, "v": {"requests": [request(1)]}}])
    (storage / "ws2" / "chatSessions" / "smiec.json").write_bytes(b"\xff nie json")
    outside = chat(tmp_path / "outside", "w", "obca", [{"kind": 0, "v": {"requests": [request(1)]}}])
    (storage / "ws2" / "chatSessions" / "link.jsonl").symlink_to(outside)
    (storage / "ws-link").symlink_to(outside.parent.parent, target_is_directory=True)

    got = {s.session_id: s for s in copilot.scan_chat_sessions((storage, tmp_path / "brak"), now=NOW)}
    assert set(got) == {"aktywna", "czeka", "dwa-formaty"}
    a = got["aktywna"]
    assert (a.state, a.title, a.last_tool, a.project) == (WORKING, "Naprawa logowania", "runInTerminal",
                                                         "/home/x/mój-projekt")
    assert a.agent == "copilot-chat" and not a.can_kill and a.branch is None
    assert got["czeka"].state == WAITING and got["czeka"].title == "Stara wersja"
    assert got["czeka"].project == "/home/x/inny"
    assert got["dwa-formaty"].title == "z jsonl"
    assert SECRET not in json.dumps([agents.to_dict(s) for s in got.values()])


def test_chat_skips_oversized_files(tmp_path, monkeypatch):
    storage = tmp_path / "s"
    chat(storage, "w", "duza", [{"kind": 0, "v": {"requests": [request(1)]}}])
    monkeypatch.setattr(copilot, "MAX_CHAT_FILE", 10)
    assert copilot.scan_chat_sessions((storage,), now=NOW) == []
