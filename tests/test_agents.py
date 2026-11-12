import json
import os
from datetime import datetime, timedelta, timezone

from appcheck import agents
from appcheck.agents import IDLE, WAITING, WORKING, scan_sessions

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SECRET = "SEKRETNA-TRESC-haslo-123"


def ts(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def user(minutes_ago, content=SECRET):
    return {"type": "user", "timestamp": ts(minutes_ago), "cwd": "/home/x/proj", "gitBranch": "main",
            "message": {"role": "user", "content": [{"type": "tool_result", "content": content}]}}


def assistant(minutes_ago, tool=None, stop="end_turn"):
    block = ({"type": "tool_use", "name": tool, "input": {"command": SECRET}} if tool
             else {"type": "text", "text": SECRET})
    return {"type": "assistant", "timestamp": ts(minutes_ago), "cwd": "/home/x/proj", "gitBranch": "DA-06",
            "message": {"role": "assistant", "content": [block], "stop_reason": "tool_use" if tool else stop}}


def write(root, project, sid, entries, mtime=NOW):
    d = root / project
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    os.utime(p, (mtime.timestamp(), mtime.timestamp()))
    return p


def test_states_and_metadata(tmp_path):
    write(tmp_path, "p1", "tool", [{"type": "ai-title", "aiTitle": "Dashboard   aplikacji"},
                                    {"type": "pr-link", "prUrl": "https://github.com/a/b/pull/1"},
                                    user(10), assistant(1, tool="Bash")])
    write(tmp_path, "p1", "waiting", [user(30), assistant(20)])
    write(tmp_path, "p2", "thinking", [assistant(5, tool="Edit"), user(0.5)])
    write(tmp_path, "p2", "old", [user(600), assistant(500)])
    write(tmp_path, "p2", "stale-tool", [assistant(60, tool="Bash")])
    got = {s.session_id: s for s in scan_sessions(tmp_path, now=NOW)}
    assert got["tool"].state == WORKING and got["tool"].last_tool == "Bash"
    assert got["tool"].title == "Dashboard aplikacji" and got["tool"].pr_url == "https://github.com/a/b/pull/1"
    assert got["tool"].project == "/home/x/proj" and got["tool"].branch == "DA-06"
    assert got["waiting"].state == WAITING
    assert got["thinking"].state == WORKING and got["thinking"].last_tool == "Edit"
    assert got["old"].state == IDLE
    assert got["stale-tool"].state == IDLE


def test_never_returns_message_content(tmp_path):
    write(tmp_path, "p", "s", [user(1), assistant(0.5, tool="Bash"), assistant(0.2)])
    out = json.dumps([agents.to_dict(s) for s in scan_sessions(tmp_path, now=NOW)])
    assert SECRET not in out


def test_skips_old_files_symlinks_and_garbage(tmp_path):
    root = tmp_path / "projects"
    write(root, "p", "old", [user(1)], mtime=NOW - timedelta(days=2))
    write(root, "p", "garbage", [])
    (root / "p" / "garbage.jsonl").write_bytes(b"\xff\xfe nie json\n{\"type\": 1}\n[]\n")
    outside = write(tmp_path / "outside", "q", "secret", [user(1)])
    (root / "link").symlink_to(outside.parent, target_is_directory=True)
    (root / "p" / "linked.jsonl").symlink_to(outside)
    assert scan_sessions(root, now=NOW) == []


def test_missing_root(tmp_path):
    assert scan_sessions(tmp_path / "brak", now=NOW) == []


def test_untrusted_pr_url_and_long_title(tmp_path):
    write(tmp_path, "p", "s", [{"type": "pr-link", "prUrl": "javascript:alert(1)"},
                               {"type": "ai-title", "aiTitle": "x" * 500}, user(1)])
    s = scan_sessions(tmp_path, now=NOW)[0]
    assert s.pr_url is None and len(s.title) == agents.MAX_TITLE


def test_reads_only_tail_of_large_file(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "TAIL_BYTES", 2000)
    big = [user(100 - i / 10) for i in range(200)] + [assistant(0.1, tool="Read")]
    write(tmp_path, "p", "big", big)
    s = scan_sessions(tmp_path, now=NOW)[0]
    assert s.last_tool == "Read" and s.state == WORKING


# --- żywe procesy (~/.claude/sessions) ---------------------------------------------------------
import subprocess  # noqa: E402

import pytest  # noqa: E402

from appcheck.agents import kill_session, live_processes, proc_start_time  # noqa: E402


def fake_proc(proc_root, pid, start, name="claude", state="S"):
    d = proc_root / str(pid)
    d.mkdir(parents=True)
    fields = [state] + ["0"] * 18 + [str(start)] + ["0"] * 10  # pola 3…; pole 22 = czas startu
    (d / "stat").write_text(f"{pid} ({name}) " + " ".join(fields) + "\n", encoding="ascii")


def session_file(sessions_dir, pid, sid, start, **extra):
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f"{pid}.json").write_text(
        json.dumps({"pid": pid, "sessionId": sid, "procStart": str(start), **extra}), encoding="utf-8")


def test_proc_start_time_handles_spaces_and_parens_in_name(tmp_path):
    fake_proc(tmp_path, 42, 777, name="a) b (c")
    assert proc_start_time(42, tmp_path) == "777"
    assert proc_start_time(43, tmp_path) is None
    fake_proc(tmp_path, 44, 888, state="Z")
    assert proc_start_time(44, tmp_path) is None  # zombie = zakończony


def test_live_processes_requires_matching_start_time(tmp_path):
    proc, sess = tmp_path / "proc", tmp_path / "sessions"
    fake_proc(proc, 100, 5000)
    fake_proc(proc, 101, 6000)
    session_file(sess, 100, "zywa", 5000)
    session_file(sess, 101, "pid-ponownie-uzyty", 1234)  # ten PID ma teraz inny proces
    session_file(sess, 102, "martwa", 7000)  # brak procesu (np. po wsl --shutdown)
    (sess / "103.json").write_text('{"pid": 104, "sessionId": "zla-nazwa", "procStart": "1"}')
    (sess / "105.json").write_text('{"pid": 105, "sessionId": "../../x", "procStart": "1"}')
    (sess / "106.json").write_text("nie json")
    (sess / "1.json").write_text('{"pid": 1, "sessionId": "init", "procStart": "1"}')
    assert live_processes(sess, proc) == {"zywa": agents.LiveProcess(100, "5000")}
    assert live_processes(tmp_path / "brak", proc) == {}


def test_scan_with_live_hides_dead_sessions_regardless_of_age(tmp_path):
    write(tmp_path, "p", "zywa", [user(30), assistant(20)], mtime=NOW - timedelta(days=3))
    write(tmp_path, "p", "zywa-stara", [user(900), assistant(800)])
    write(tmp_path, "p", "martwa", [user(30), assistant(20)])
    live = {"zywa": agents.LiveProcess(1, "1"), "zywa-stara": agents.LiveProcess(2, "2")}
    got = {s.session_id: s.state for s in scan_sessions(tmp_path, now=NOW, live=live)}
    assert got == {"zywa": WAITING, "zywa-stara": IDLE}
    assert scan_sessions(tmp_path, now=NOW, live={}) == []


@pytest.fixture
def sleeper():
    proc = subprocess.Popen(["sleep", "60"])
    yield proc
    proc.kill()
    proc.wait()


def test_kill_session_terminates_only_matching_process(tmp_path, sleeper):
    start = proc_start_time(sleeper.pid)
    assert start
    sess = tmp_path / "sessions"
    session_file(sess, sleeper.pid, "obca", int(start) + 1)
    assert kill_session("obca", sess) is None  # inny czas startu — nie ruszamy procesu
    assert sleeper.poll() is None
    assert kill_session("../obca", sess) is None
    session_file(sess, sleeper.pid, "moja", start)
    assert kill_session("moja", sess) == sleeper.pid
    assert sleeper.wait(5) == -15
    assert kill_session("moja", sess) is None
