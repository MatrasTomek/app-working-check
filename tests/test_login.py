from appcheck.browser_check import check_app
from appcheck.config import AppConfig
from appcheck.result import Severity


def app(url, pw="sekret", **kw):
    return AppConfig("Panel", url, username="jan", password=pw, timeout=10, **kw)


def test_login_success(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html"), tmp_path)
    assert r.status is Severity.OK


def test_login_wrong_password(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html", pw="zle"), tmp_path)
    i = next(i for i in r.issues if i.category == "logowanie")
    assert i.message == "Logowanie nieudane: Nieprawidłowy login lub hasło"
    assert "zle" not in " ".join(x.message for x in r.issues)
    assert r.status is Severity.ERROR and r.screenshot is not None


def test_no_form(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/no-form.html"), tmp_path)
    assert any(i.message == "Nie znaleziono formularza logowania" for i in r.issues)


def test_configured_selectors(browser, site, tmp_path):
    a = app(f"{site}/login-js.html", user_selector="#e", pass_selector="#p", submit_selector="#go")
    assert check_app(browser, a, tmp_path).status is Severity.OK


def test_slow_failed_login_is_not_success(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html", pw="slow"), tmp_path)
    assert any(i.category == "logowanie" and "Nieprawidłowy login lub hasło" in i.message
               for i in r.issues)
    assert r.status is Severity.ERROR


def test_password_only_form_is_not_submitted(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/password-only.html"), tmp_path)
    assert any(i.message == "Nie znaleziono formularza logowania" for i in r.issues)


def test_untyped_show_password_button_not_clicked(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login-showpw.html"), tmp_path)
    assert r.status is Severity.OK and not r.failed_requests


def test_login_redirecting_to_error_page_is_error(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html", pw="to502"), tmp_path)
    assert r.status is Severity.ERROR
    assert any(i.category == "dostępność" and i.message == "HTTP 502 Bad Gateway (/status/502)"
               for i in r.issues)
