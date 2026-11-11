import threading

from appcheck.config import AppConfig
from appcheck.result import AppResult, Issue, Severity
from appcheck.runner import RunnerError
from appcheck.web.app import create_app
from appcheck.web.jobs import Job
from appcheck.web.servers import collect_secrets

from .conftest import POST_HEADERS, TOKEN, login, make_client

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _fake_runner(results_for, calls=None, gate=None):
    def runner(apps, screenshot_dir, repo_of=None, **kw):
        if calls is not None:
            calls.append([a.name for a in apps])
        if gate is not None:
            gate.wait(5)
        return results_for(apps, screenshot_dir)
    return runner


def _client(settings, env, runner):
    c = make_client(create_app(settings, env=env, check_runner=runner))
    c.__enter__()
    assert login(c).status_code == 200
    return c


def _check_and_wait(c):
    r = c.post("/api/servers/check", headers=POST_HEADERS)
    assert r.status_code == 200
    c.app.state.servers_job.wait(10)
    return c.get("/api/servers").json()


def _apps_yaml(settings, body):
    settings.base_dir.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text(body, encoding="utf-8")


def test_check_returns_results_and_masks_secrets(settings):
    _apps_yaml(settings, "apps:\n  - {name: Panel, url: 'https://panel.example', login: P}\n")
    env = {"P_USER": "jan", "P_PASS": "SuperTajne!42", "GITHUB_TOKEN": "ghp_sekretny_token"}

    def results(apps, shot_dir):
        shot_dir.mkdir(parents=True)
        (shot_dir / "panel-abc123.png").write_bytes(PNG)
        r = AppResult(name=apps[0].name, url=apps[0].url + "/?p=SuperTajne!42", load_time_ms=120,
                      screenshot=shot_dir / "panel-abc123.png")
        r.issues.append(Issue(Severity.ERROR, "logowanie", f"Błąd: SuperTajne!42 {TOKEN} ghp_sekretny_token"))
        return [r]

    c = _client(settings, env, _fake_runner(results))
    data = _check_and_wait(c)
    assert data["state"] == "idle" and data["error"] is None
    app = data["run"]["apps"][0]
    assert app["status"] == "error" and data["run"]["counts"] == {"ok": 0, "warning": 0, "error": 1}
    body = str(data)
    for secret in ("SuperTajne!42", TOKEN, "ghp_sekretny_token"):
        assert secret not in body
    shot = c.get(app["screenshot"])
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"
    assert shot.headers["x-content-type-options"] == "nosniff"


def test_screenshot_only_from_current_run(settings, tmp_path):
    _apps_yaml(settings, "apps:\n  - {name: A, url: 'https://a.example'}\n")
    secret = settings.base_dir / "sekret.png"
    secret.write_bytes(PNG)

    def results(apps, shot_dir):
        shot_dir.mkdir(parents=True)
        (shot_dir / "a-111111.png").write_bytes(PNG)
        (shot_dir / "inny-222222.png").write_bytes(PNG)  # plik spoza wyniku
        return [AppResult(name="A", url="https://a.example", screenshot=shot_dir / "a-111111.png")]

    c = _client(settings, {}, _fake_runner(results))
    run_id = _check_and_wait(c)["run"]["id"]
    assert c.get(f"/api/screenshots/{run_id}/a-111111.png").status_code == 200
    for path in (f"/api/screenshots/{run_id}/inny-222222.png",
                 f"/api/screenshots/{run_id}/..%2F..%2Fsekret.png",
                 f"/api/screenshots/{run_id}/%2E%2E%2Fsekret.png",
                 "/api/screenshots/2000-01-01_00-00-00/a-111111.png",
                 f"/api/screenshots/{run_id}/../../sekret.png"):
        assert c.get(path).status_code == 404, path


def test_screenshots_require_login(settings):
    with make_client(create_app(settings, env={})) as c:
        assert c.get("/api/servers").status_code == 401
        assert c.get("/api/screenshots/2026-01-01_00-00-00/a-111111.png").status_code == 401
        assert c.post("/api/servers/check", headers=POST_HEADERS).status_code == 401


def test_only_one_run_at_a_time(settings):
    _apps_yaml(settings, "apps:\n  - {name: A, url: 'https://a.example'}\n")
    gate, calls = threading.Event(), []
    c = _client(settings, {}, _fake_runner(lambda apps, d: [], calls, gate))
    first = c.post("/api/servers/check", headers=POST_HEADERS).json()
    second = c.post("/api/servers/check", headers=POST_HEADERS).json()
    assert first["state"] == second["state"] == "running"
    gate.set()
    c.app.state.servers_job.wait(5)
    assert calls == [["A"]]


def test_user_error_shown_masked_and_internal_error_hidden(settings):
    def failing(exc):
        def work():
            raise exc
        return work

    job = Job("x", failing(RunnerError("Brak przeglądarki tajne123")), mask=lambda s: s.replace("tajne123", "***"))
    job.trigger(); job.wait(5)
    assert job.state()["error"] == "Brak przeglądarki ***"
    job = Job("y", failing(ValueError("wewnętrzne szczegóły z hasłem")))
    job.trigger(); job.wait(5)
    assert job.state()["error"] == "Błąd wewnętrzny — szczegóły w logu serwera"


def test_config_error_reported(settings):
    _apps_yaml(settings, "apps:\n  - {name: A, url: 'https://a', login: BRAK}\n")
    c = _client(settings, {}, _fake_runner(lambda apps, d: []))
    data = _check_and_wait(c)
    assert "BRAK_USER" in data["error"] and data["run"] is None


def test_collect_secrets():
    env = {"A_PASS": "haslo1", "GITHUB_TOKEN": "tok-1234", "API_KEY": "klucz", "A_USER": "jan", "PATH": "/bin"}
    assert sorted(collect_secrets(env)) == ["haslo1", "klucz", "tok-1234"]


def test_real_browser_check(settings, site):
    """Integracja: prawdziwa przeglądarka i strona testowa."""
    _apps_yaml(settings, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n  - {{name: Zle, url: '{site}/status/502'}}\n")
    c = make_client(create_app(settings, env={}))
    c.__enter__()
    login(c)
    data = _check_and_wait(c)
    statuses = {a["name"]: a["status"] for a in data["run"]["apps"]}
    assert statuses == {"Ok": "ok", "Zle": "error"}
    shot = next(a["screenshot"] for a in data["run"]["apps"] if a["name"] == "Zle")
    assert shot and c.get(shot).status_code == 200
