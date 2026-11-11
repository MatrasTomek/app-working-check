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
