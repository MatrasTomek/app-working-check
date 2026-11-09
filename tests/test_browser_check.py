from appcheck.browser_check import check_app
from appcheck.config import AppConfig
from appcheck.result import Severity


def run(browser, url, tmp_path, **kw):
    return check_app(browser, AppConfig("Test", url, timeout=kw.pop("timeout", 10), **kw), tmp_path)


def test_ok_page(browser, site, tmp_path):
    r = run(browser, f"{site}/ok.html", tmp_path)
    assert r.status is Severity.OK and r.load_time_ms is not None and r.screenshot is None


def test_redirect_is_ok(browser, site, tmp_path):
    assert run(browser, f"{site}/redirect", tmp_path).status is Severity.OK


def test_console_errors_are_warnings(browser, site, tmp_path):
    r = run(browser, f"{site}/console-error.html", tmp_path)
    assert r.status is Severity.WARNING
    msgs = " ".join(i.message for i in r.issues)
    assert "boom" in msgs and "kaboom" in msgs


def test_api_500_is_error_with_screenshot(browser, site, tmp_path):
    r = run(browser, f"{site}/api500.html", tmp_path)
    assert r.status is Severity.ERROR
    assert any(i.message == "Backend: GET /api/500 → 500" for i in r.issues)
    assert r.screenshot == tmp_path / "test.png" and r.screenshot.exists()


def test_api_404_is_warning(browser, site, tmp_path):
    assert run(browser, f"{site}/api404.html", tmp_path).status is Severity.WARNING


def test_empty_spa_is_error(browser, site, tmp_path):
    r = run(browser, f"{site}/empty.html", tmp_path)
    assert any(i.category == "wyświetlanie" for i in r.issues) and r.status is Severity.ERROR


def test_http_502_is_error(browser, site, tmp_path):
    r = run(browser, f"{site}/status/502", tmp_path)
    assert any(i.category == "dostępność" and "502" in i.message for i in r.issues)


def test_dead_server_is_error(browser, dead_url, tmp_path):
    r = run(browser, dead_url, tmp_path)
    assert r.status is Severity.ERROR
    assert any("Serwer nie odpowiada" in i.message for i in r.issues)


def test_never_idle_page_is_ok(browser, site, tmp_path):
    assert run(browser, f"{site}/never-idle.html", tmp_path, timeout=3).status is Severity.OK
