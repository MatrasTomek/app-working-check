"""Sprawdzenie jednej aplikacji w przeglądarce: dostępność, wyświetlanie, backend, konsola."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Browser, Page, Request, Response

from appcheck.config import AppConfig
from appcheck.result import AppResult, Issue, RequestRecord, Severity, mask_secrets, slugify
from appcheck.rules import classify_console, classify_page_error, classify_request

_HAS_CONTENT_JS = """() => {
    const body = document.body;
    if (!body) return false;
    if (body.innerText.trim()) return true;
    return Array.from(document.querySelectorAll('img, svg, canvas, input, button, video'))
        .some(el => el.offsetWidth * el.offsetHeight > 0);
}"""


def _is_main_document(request: Request, page: Page) -> bool:
    return request.resource_type == "document" and request.frame == page.main_frame


def check_app(browser: Browser, app: AppConfig, screenshot_dir: Path) -> AppResult:
    """Sprawdza aplikację; nigdy nie rzuca wyjątku."""
    result = AppResult(name=app.name, url=app.url)
    secrets = [app.password]
    app_host = urlsplit(app.url).hostname or ""
    state = {"logged_in": False}

    def add_issue(issue: Issue | None) -> None:
        if issue is not None:
            issue.message = mask_secrets(issue.message, secrets)
            result.issues.append(issue)

    def record(rec: RequestRecord) -> None:
        masked = RequestRecord(
            rec.method, mask_secrets(rec.url, secrets), rec.resource_type, rec.status,
            mask_secrets(rec.error, secrets) if rec.error else None,
        )
        add_issue(classify_request(masked, app_host, state["logged_in"]))
        if not (masked.error and "ERR_ABORTED" in masked.error):
            result.failed_requests.append(masked)

    context = None
    try:
        context = browser.new_context(ignore_https_errors=False)
        page = context.new_page()

        def on_console(msg) -> None:
            if msg.type in ("error", "warning"):
                text = mask_secrets(msg.text, secrets)
                result.console_messages.append(f"{msg.type}: {text}")
                add_issue(classify_console(msg.type, text))

        def on_pageerror(err) -> None:
            add_issue(classify_page_error(mask_secrets(str(err), secrets)))

        def on_requestfailed(request: Request) -> None:
            if _is_main_document(request, page):
                return  # dostępność oceniana osobno
            record(RequestRecord(request.method, request.url, request.resource_type,
                                 None, request.failure or "nieznany błąd"))

        def on_response(response: Response) -> None:
            if response.status < 400 or _is_main_document(response.request, page):
                return
            req = response.request
            record(RequestRecord(req.method, req.url, req.resource_type, response.status, None))

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_requestfailed)
        page.on("response", on_response)

        timeout_ms = app.timeout * 1000
        start = time.monotonic()
        try:
            resp = page.goto(app.url, wait_until="load", timeout=timeout_ms)
        except Exception as e:  # błąd sieci/SSL/timeout dokumentu
            result.load_time_ms = round((time.monotonic() - start) * 1000)
            first_line = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            add_issue(Issue(Severity.ERROR, "dostępność", f"Serwer nie odpowiada: {first_line}"))
            return result
        result.load_time_ms = round((time.monotonic() - start) * 1000)

        if resp is not None and resp.status >= 400:
            add_issue(Issue(Severity.ERROR, "dostępność", f"HTTP {resp.status} {resp.status_text}".strip()))

        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass  # brak networkidle nie jest błędem

        if not page.evaluate(_HAS_CONTENT_JS):
            add_issue(Issue(Severity.ERROR, "wyświetlanie", "Pusta strona — nic się nie wyrenderowało"))

        # --- Task 5: logowanie ---
        # if app.needs_login:
        #     perform_login(page, app)   # po sukcesie: state["logged_in"] = True, ponowne sprawdzenie wyświetlania

        if result.status is Severity.ERROR:
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = screenshot_dir / f"{slugify(app.name)}.png"
            page.screenshot(full_page=True, path=path)
            result.screenshot = path
    except Exception as e:
        add_issue(Issue(Severity.ERROR, "skrypt", f"Błąd skryptu: {e}"))
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
    return result
