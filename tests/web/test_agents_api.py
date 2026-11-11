import json
from datetime import datetime, timezone

from appcheck.web.app import create_app

from .conftest import TOKEN, login, make_client


def test_agents_endpoint(settings):
    d = settings.agents_dir / "proj"
    d.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    entries = [{"type": "ai-title", "aiTitle": f"Tytuł z {TOKEN}"},
               {"type": "assistant", "timestamp": now, "cwd": "/w", "message": {
                   "content": [{"type": "tool_use", "name": "Bash", "input": {"x": "tajne"}}],
                   "stop_reason": "tool_use"}}]
    (d / "s1.jsonl").write_text("\n".join(map(json.dumps, entries)), encoding="utf-8")
    with make_client(create_app(settings, env={})) as c:
        assert c.get("/api/agents").status_code == 401
        login(c)
        data = c.get("/api/agents").json()
    assert data["counts"]["pracuje"] == 1
    agent = data["agents"][0]
    assert agent["last_tool"] == "Bash" and agent["project"] == "/w"
    assert TOKEN not in json.dumps(data) and "tajne" not in json.dumps(data)
