import json
import subprocess
from datetime import datetime, timezone

import pytest

from appcheck.agents import proc_start_time
from appcheck.web.app import create_app

from .conftest import POST_HEADERS, TOKEN, login, make_client


@pytest.fixture
def sleeper():
    proc = subprocess.Popen(["sleep", "60"])
    yield proc
    proc.kill()
    proc.wait()


def add_session(settings, sid, entries, pid=None):
    d = settings.agents_dir / "proj"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.jsonl").write_text("\n".join(map(json.dumps, entries)), encoding="utf-8")
    if pid:
        settings.claude_sessions_dir.mkdir(parents=True, exist_ok=True)
        (settings.claude_sessions_dir / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": sid, "procStart": proc_start_time(pid)}), encoding="utf-8")


def working(now):
    return {"type": "assistant", "timestamp": now, "cwd": "/w", "message": {
        "content": [{"type": "tool_use", "name": "Bash", "input": {"x": "tajne"}}], "stop_reason": "tool_use"}}


def test_agents_endpoint_shows_only_live_sessions(settings, sleeper):
    now = datetime.now(timezone.utc).isoformat()
    add_session(settings, "s1", [{"type": "ai-title", "aiTitle": f"Tytuł z {TOKEN}"}, working(now)],
                pid=sleeper.pid)
    add_session(settings, "martwa", [working(now)])
    with make_client(create_app(settings, env={})) as c:
        assert c.get("/api/agents").status_code == 401
        login(c)
        data = c.get("/api/agents").json()
    assert data["counts"]["pracuje"] == 1 and len(data["agents"]) == 1
    agent = data["agents"][0]
    assert agent["session_id"] == "s1" and agent["last_tool"] == "Bash" and agent["project"] == "/w"
    assert TOKEN not in json.dumps(data) and "tajne" not in json.dumps(data)


def test_kill_endpoint(settings, sleeper):
    add_session(settings, "s1", [working(datetime.now(timezone.utc).isoformat())], pid=sleeper.pid)
    with make_client(create_app(settings, env={})) as c:
        assert c.post("/api/agents/s1/kill", headers=POST_HEADERS).status_code == 401
        login(c)
        assert c.post("/api/agents/s1/kill").status_code == 403  # bez nagłówków CSRF
        assert sleeper.poll() is None
        assert c.post("/api/agents/inna/kill", headers=POST_HEADERS).status_code == 404
        assert c.post("/api/agents/s1/kill", headers=POST_HEADERS).json() == {"ok": True}
        assert sleeper.wait(5) == -15
        assert c.post("/api/agents/s1/kill", headers=POST_HEADERS).status_code == 404


def test_agents_endpoint_includes_copilot_cli_and_chat(settings):
    sid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    state = settings.copilot_dir / "session-state" / sid
    state.mkdir(parents=True)
    events = state / "events.jsonl"
    events.write_text(json.dumps({"type": "tool.execution_start", "timestamp": datetime.now(timezone.utc).isoformat(),
                                  "data": {"toolName": "bash", "toolCallId": "c", "arguments": "tajne"}}) + "\n")
    (state / "workspace.yaml").write_text(f"cwd: /cli\nname: Tytuł z {TOKEN}\n")
    chats = settings.vscode_storage_dirs[0] / "ws" / "chatSessions"
    chats.mkdir(parents=True)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    (chats / "czat.jsonl").write_text(json.dumps({"kind": 0, "v": {
        "workingDirectory": "file:///chat", "requests": [
            {"timestamp": now_ms, "message": {"text": "tajne"}, "modelState": {"value": 1, "completedAt": now_ms}}]}}))
    proc = subprocess.Popen(["bash", "-c", 'exec 3<"$1"; exec -a copilot sleep 60', "_", str(events)])
    try:
        with make_client(create_app(settings, env={})) as c:
            login(c)
            for _ in range(50):
                data = c.get("/api/agents").json()
                if len(data["agents"]) == 2:
                    break
            by_agent = {a["agent"]: a for a in data["agents"]}
            assert by_agent["copilot-cli"]["project"] == "/cli" and by_agent["copilot-cli"]["can_kill"]
            assert by_agent["copilot-cli"]["state"] == "pracuje"
            assert by_agent["copilot-chat"]["project"] == "/chat" and not by_agent["copilot-chat"]["can_kill"]
            assert TOKEN not in json.dumps(data) and "tajne" not in json.dumps(data)
            assert c.post("/api/agents/czat/kill", headers=POST_HEADERS).status_code == 404
            assert c.post(f"/api/agents/{sid}/kill", headers=POST_HEADERS).json() == {"ok": True}
            assert proc.wait(5) == -15
    finally:
        proc.kill()
        proc.wait()
