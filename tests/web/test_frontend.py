"""Frontend w prawdziwej przeglądarce: logowanie, zakładki, Odpytaj, CSP bez naruszeń, brak XSS."""
import json
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone

import pytest
import uvicorn

from appcheck.agents import proc_start_time
from appcheck.github import RepoInfo
from appcheck.result import AppResult, Issue, Severity
from appcheck.web.app import create_app

from .conftest import TOKEN, make_client

XSS = '<img src=x onerror="window.__xss=1">'


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def sleeper():
    proc = subprocess.Popen(["sleep", "60"])
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def server(settings, sleeper):
    settings.base_dir.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text("apps:\n  - {name: A, url: 'https://a.example'}\n", encoding="utf-8")
    d = settings.agents_dir / "p"
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": datetime.now(timezone.utc).isoformat(), "cwd": "/praca/projekt",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}], "stop_reason": "tool_use"}}),
        encoding="utf-8")
    settings.claude_sessions_dir.mkdir(parents=True)
    (settings.claude_sessions_dir / f"{sleeper.pid}.json").write_text(json.dumps(
        {"pid": sleeper.pid, "sessionId": "s", "procStart": proc_start_time(sleeper.pid)}), encoding="utf-8")

    def runner(apps, screenshot_dir, repo_of=None, **kw):
        time.sleep(0.3)
        r = AppResult(name=f"Aplikacja {XSS}", url="javascript:alert(1)", load_time_ms=900)
        r.issues.append(Issue(Severity.ERROR, "backend", f"Błąd 502 {XSS}"))
        return [r, AppResult(name="Dobra", url="https://dobra.example", load_time_ms=100)]

    def fetch(account, token, api_url, on_warning=None):
        return [RepoInfo(name="repo", full_name="konto/repo", html_url="https://github.com/konto/repo",
                         description=f"Opis {XSS}", pushed_at="2026-11-10")]

    import dataclasses
    s = dataclasses.replace(settings, github_accounts=("konto",))
    port = _free_port()
    config = uvicorn.Config(create_app(s, env={}, check_runner=runner, fetch=fetch),
                            host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://localhost:{port}"
    srv.should_exit = True
    t.join(5)


def test_dashboard_flow(server, browser, sleeper):
    page = browser.new_page()
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(server)
    page.fill("#token", "zly-token")
    page.click("#login-form button")
    page.wait_for_selector("#login-error:not([hidden])")
    problems.clear()  # 401 z nieudanego logowania jest oczekiwany

    page.fill("#token", TOKEN)
    page.click("#login-form button")
    page.wait_for_selector("#app:not([hidden])")
    assert page.input_value("#token") == ""

    page.click("#btn-query")
    page.wait_for_selector("#servers-list .card >> text=Dobra")
    cards = page.locator("#servers-list .card")
    assert cards.count() == 2
    assert XSS in cards.first.inner_text()  # pokazane jako tekst
    assert page.evaluate("window.__xss") is None
    assert page.locator("#servers-list a[href^='javascript']").count() == 0

    page.click("[data-tab=projects]")
    page.wait_for_selector("#projects-list .card >> text=konto/repo")
    assert page.locator("#tab-servers").is_hidden()

    page.click("[data-tab=agents]")
    page.wait_for_selector("#agents-list .card >> text=\"/praca/projekt\"")
    assert "pracuje" in page.inner_text("#agents-list")
    page.once("dialog", lambda d: d.dismiss())
    page.click("#agents-list button.danger")
    page.wait_for_timeout(300)
    assert sleeper.poll() is None  # anulowane potwierdzenie — proces działa
    page.once("dialog", lambda d: d.accept())
    page.click("#agents-list button.danger")
    page.wait_for_selector("#agents-list >> text=Brak działających sesji agentów")
    assert sleeper.wait(5) == -15

    page.click("#btn-start")
    page.wait_for_selector("#live-badge[data-on=true]")
    page.click("#btn-stop")
    page.wait_for_selector("#live-badge[data-on=false]")

    page.click("#logout")
    page.wait_for_selector("#login:not([hidden])")
    page.reload()
    page.wait_for_selector("#login:not([hidden])")
    assert problems == [], problems
    page.close()


def test_static_files_served_with_security_headers(settings):
    with make_client(create_app(settings, env={})) as c:
        r = c.get("/")
        assert r.status_code == 200 and "App Dashboard" in r.text
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert c.get("/app.js").headers["content-type"].startswith(("application/javascript", "text/javascript"))
        assert c.get("/../serve.py").status_code == 404
        assert c.get("/%2e%2e/serve.py").status_code == 404


def test_frontend_never_uses_innerhtml():
    from appcheck.web.app import STATIC_DIR
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in js, banned
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "style=" not in html and "onclick" not in html
