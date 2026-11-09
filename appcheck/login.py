"""Automatyczne logowanie przez formularz (selektory z konfiguracji lub wykrywane)."""
from __future__ import annotations

from playwright.sync_api import Locator, Page

from appcheck.config import AppConfig
from appcheck.result import Issue, Severity

_MARK_USER_JS = """pass => {
    const visible = el => {
        const s = getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none' && el.offsetWidth * el.offsetHeight > 0;
    };
    document.querySelectorAll('[data-appcheck-user]').forEach(e => e.removeAttribute('data-appcheck-user'));
    const types = ['text', 'email', 'tel', ''];
    const found = Array.from(document.querySelectorAll('input')).filter(el =>
        types.includes((el.getAttribute('type') || '').toLowerCase()) && visible(el) &&
        (el.compareDocumentPosition(pass) & Node.DOCUMENT_POSITION_FOLLOWING));
    if (!found.length) return false;
    found[found.length - 1].setAttribute('data-appcheck-user', '');
    return true;
}"""

_NO_PASSWORD_JS = """() => !Array.from(document.querySelectorAll('input[type=password]')).some(
    el => el.offsetWidth * el.offsetHeight > 0 && getComputedStyle(el).visibility !== 'hidden')"""

_URL_OR_NO_PASSWORD_JS = f"""old => location.href !== old || ({_NO_PASSWORD_JS})()"""

_ALERT_SELECTOR = "[role=alert]:visible, [class*=error]:visible, [class*=invalid]:visible"
_EXPLICIT_SUBMIT = "button[type=submit]:visible, input[type=submit]:visible"
_UNTYPED_SUBMIT = "button:not([type]):visible"
_NO_FORM = "Nie znaleziono formularza logowania"
_GRACE_MS = 2000  # czas na zniknięcie pola hasła po zmianie adresu (SPA)


def _failure(message: str) -> Issue:
    return Issue(Severity.ERROR, "logowanie", message)


def _find_user_field(page: Page, password: Locator) -> Locator | None:
    if password.evaluate(_MARK_USER_JS):
        return page.locator("[data-appcheck-user]").first
    return None


def _find_submit(password: Locator) -> Locator | None:
    form = password.locator("xpath=ancestor::form[1]")
    for selector in (_EXPLICIT_SUBMIT, _UNTYPED_SUBMIT):  # przycisk bez type to ostateczność (np. "pokaż hasło")
        button = form.locator(selector).first
        if button.count():
            return button
    return None


def _failure_text(page: Page) -> str | None:
    try:
        alert = page.locator(_ALERT_SELECTOR).first
        text = alert.inner_text(timeout=1000).strip() if alert.count() else ""
        return text or None
    except Exception:
        return None


def perform_login(page: Page, app: AppConfig) -> Issue | None:
    """Loguje przez formularz. None = zalogowano; inaczej Issue(ERROR, "logowanie")."""
    timeout_ms = app.timeout * 1000
    try:
        password = page.locator(app.pass_selector or "input[type=password]:visible").first
        if not password.count():
            return _failure(_NO_FORM)
        if app.user_selector:
            user = page.locator(app.user_selector).first
        else:
            user = _find_user_field(page, password)
            if user is None:
                return _failure(_NO_FORM)
        user.fill(app.username or "", timeout=timeout_ms)
        password.fill(app.password or "", timeout=timeout_ms)

        if app.submit_selector:
            submit = page.locator(app.submit_selector).first
        else:
            submit = _find_submit(password)
        url_before = page.url
        if submit is not None:
            submit.click(timeout=timeout_ms)
        else:
            password.press("Enter", timeout=timeout_ms)

        try:
            page.wait_for_function(_URL_OR_NO_PASSWORD_JS, arg=url_before, timeout=timeout_ms)
            # pełna nawigacja: poczekaj na nowy dokument, zanim ocenimy obecność pola hasła
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            # zmiana adresu bez zniknięcia pola hasła (np. przeładowanie z błędem) to jeszcze nie sukces
            page.wait_for_function(_NO_PASSWORD_JS, timeout=_GRACE_MS)
            return None
        except Exception:
            text = _failure_text(page)
            return _failure("Logowanie nieudane" + (f": {text}" if text else ""))
    except Exception as e:
        return _failure(f"Logowanie nieudane: {str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__}")
