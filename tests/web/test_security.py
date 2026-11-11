"""Testy wymagań z sekcji „Bezpieczeństwo” specyfikacji dashboardu."""
import stat

import pytest

import serve
from appcheck.config import ConfigError
from appcheck.web.app import create_app
from appcheck.web.security import SESSION_COOKIE, LoginThrottle, SessionStore, origin_allowed
from appcheck.web.settings import Settings

from .conftest import POST_HEADERS, TOKEN, login, make_client


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- 1, 2: sieć i token -------------------------------------------------------------------

def _env(**kw):
    return {"DASHBOARD_TOKEN": TOKEN, **kw}


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "example.com"])
def test_non_loopback_host_refused(tmp_path, host):
    with pytest.raises(ConfigError, match="tylko na adresie lokalnym"):
        Settings.from_env(_env(DASHBOARD_HOST=host), tmp_path)


@pytest.mark.parametrize("token", [None, "", "krotki", "a" * 40, "x" * 20 + " " + "y" * 20])
def test_missing_or_weak_token_refused(tmp_path, token):
    env = {} if token is None else {"DASHBOARD_TOKEN": token}
    with pytest.raises(ConfigError, match="DASHBOARD_TOKEN"):
        Settings.from_env(env, tmp_path)


def test_settings_defaults_and_allowed_hosts(tmp_path):
    s = Settings.from_env(_env(DASHBOARD_ALLOWED_HOSTS="Komputer.tailnet-abc.ts.net, ",
                               DASHBOARD_GITHUB="MatrasTomek"), tmp_path)
    assert (s.host, s.port) == ("127.0.0.1", 8765)
    assert s.allowed_hosts == ("localhost", "127.0.0.1", "komputer.tailnet-abc.ts.net")
    assert s.github_accounts == ("MatrasTomek",)


@pytest.mark.parametrize("env", [{"DASHBOARD_ALLOWED_HOSTS": "evil.com/x"}, {"DASHBOARD_PORT": "80"},
                                 {"DASHBOARD_GITHUB": "../etc"}])
def test_invalid_settings_refused(tmp_path, env):
    with pytest.raises(ConfigError):
        Settings.from_env(_env(**env), tmp_path)


def test_gen_token_is_strong(capsys):
    assert serve.main(["--gen-token"]) == 0
    token = capsys.readouterr().out.strip()
    assert Settings.from_env({"DASHBOARD_TOKEN": token}, ".").token == token


def test_serve_refuses_without_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    assert serve.main(["--env-file", str(tmp_path / "brak.env")]) == 2
    assert "serve.py --gen-token" in capsys.readouterr().err


def test_env_file_permission_warning(tmp_path):
    env = tmp_path / ".env"
    env.write_text("X=1", encoding="utf-8")
    env.chmod(0o644)
    assert "chmod 600" in serve.env_file_warning(env)
    env.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert serve.env_file_warning(env) is None


# --- 3, 4: sesja i logowanie -------------------------------------------------------------

def test_api_requires_login(client):
    assert client.get("/api/session").json() == {"authenticated": False}
    assert client.get("/api/servers").status_code == 401
    assert client.get("/api/nieistniejace").status_code == 401  # domyślnie zamknięte
    assert client.get("/api/health").json() == {"ok": True}


def test_login_sets_hardened_cookie_without_token(client):
    r = login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert TOKEN not in cookie and "Domain" not in cookie
    assert client.get("/api/session").json() == {"authenticated": True}


def test_wrong_token_rejected(client):
    assert login(client, "zly" + TOKEN).status_code == 401
    assert client.get("/api/session").json() == {"authenticated": False}


def test_forged_session_cookie_rejected(client):
    client.cookies.set(SESSION_COOKIE, "podrobione", domain="localhost")
    assert client.get("/api/servers").status_code == 401


def test_logout_revokes_session(authed):
    sid = authed.cookies.get(SESSION_COOKIE)
    assert authed.post("/api/logout", headers=POST_HEADERS).status_code == 204
    authed.cookies.set(SESSION_COOKIE, sid, domain="localhost")  # stare ciasteczko nic nie daje
    assert authed.get("/api/servers").status_code == 401


def test_session_expires():
    clock = Clock()
    store = SessionStore(ttl_seconds=60, clock=clock)
    sid = store.create()
    assert store.valid(sid)
    clock.now += 61
    assert not store.valid(sid)


def test_lockout_after_failures(settings):
    clock = Clock()
    app = create_app(settings, throttle=LoginThrottle(5, 900, clock=clock))
    with make_client(app) as c:
        for _ in range(5):
            assert login(c, "zly-token").status_code == 401
        r = login(c)  # nawet poprawny token jest blokowany
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        clock.now += 901
        assert login(c).status_code == 200


def test_validation_error_does_not_echo_input(client):
    secret = "S" * 600
    r = client.post("/api/login", json={"token": secret}, headers=POST_HEADERS)
    assert r.status_code == 422 and secret not in r.text


# --- 5, 6: DNS rebinding i CSRF -----------------------------------------------------------

def test_unknown_host_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:8765"}).status_code == 200


def test_tailnet_host_allowed(tmp_path):
    s = Settings(token=TOKEN, base_dir=tmp_path, allowed_hosts=("localhost", "pc.tail.ts.net"))
    with make_client(create_app(s)) as c:
        assert c.get("/api/health", headers={"Host": "pc.tail.ts.net"}).status_code == 200


@pytest.mark.parametrize("headers", [
    {},
    {"X-Dashboard": "1"},
    {"Origin": "https://localhost"},
    {"Origin": "https://evil.example", "X-Dashboard": "1"},
    {"Origin": "null", "X-Dashboard": "1"},
    {"Origin": "file://localhost", "X-Dashboard": "1"},
])
def test_post_without_csrf_protection_rejected(client, headers):
    r = client.post("/api/login", json={"token": TOKEN}, headers=headers)
    assert r.status_code == 403
    assert SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_cors_preflight_rejected(client):
    r = client.options("/api/login", headers={"Origin": "https://evil.example",
                                              "Access-Control-Request-Method": "POST"})
    assert r.status_code == 403 and "access-control-allow-origin" not in r.headers


def test_origin_allowed_parsing():
    hosts = ("localhost", "pc.ts.net")
    assert origin_allowed("https://pc.ts.net", hosts)
    assert origin_allowed("http://localhost:8765", hosts)
    assert not origin_allowed("https://pc.ts.net.evil.com", hosts)
    assert not origin_allowed("https://evil.com#@pc.ts.net", hosts)
    assert not origin_allowed("javascript://localhost", hosts)


def test_oversized_body_rejected(client):
    r = client.post("/api/login", content=b"x" * 70_000,
                    headers={**POST_HEADERS, "Content-Type": "application/json"})
    assert r.status_code == 413


# --- 7, 8: nagłówki i powierzchnia API ----------------------------------------------------

def test_security_headers(client):
    r = client.get("/api/health")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert "camera=()" in r.headers["permissions-policy"]
    assert "interest-cohort" not in r.headers["permissions-policy"]  # usunięte z Chrome — ostrzeżenie w konsoli
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in r.headers
    # nagłówki są także przy odmowie
    assert "content-security-policy" in client.get("/api/servers").headers


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_disabled(authed, path):
    assert authed.get(path).status_code == 404
