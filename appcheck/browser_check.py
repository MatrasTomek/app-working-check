"""Sprawdzenie jednej aplikacji w przeglądarce: dostępność, wyświetlanie, backend, konsola."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Browser, Page, Request, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from appcheck.config import AppConfig
from appcheck.login import perform_login
from appcheck.result import AppResult, Issue, RequestRecord, Severity, mask_secrets, screenshot_filename
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


def _has_content(page: Page) -> bool:
    """Test renderowania; po nawigacji po stronie klienta (zniszczony kontekst) czeka na load i ponawia raz."""
    try:
        return page.evaluate(_HAS_CONTENT_JS)
    except Exception:
        page.wait_for_load_state("load")
        return page.evaluate(_HAS_CONTENT_JS)


def _take_screenshot(page: Page, app: AppConfig, screenshot_dir: Path, result: AppResult) -> None:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = screenshot_dir / screenshot_filename(app.name)
    page.screenshot(full_page=True, path=path)
    result.screenshot = path


def check_app(browser: Browser, app: AppConfig, screenshot_dir: Path) -> AppResult:
    """Sprawdza aplikację; nigdy nie rzuca wyjątku."""
    result = AppResult(name=app.name, url=app.url)
    secrets = [app.password]
    # host z konfiguracji + hosty dokumentu głównego aż do końca pierwszej nawigacji (przekierowania)
    app_hosts = {urlsplit(app.url).hostname or ""}
    # main_doc: ostatnia odpowiedź (Response) lub błąd (url, powód) dokumentu głównego;
    # judged: ostatni już oceniony — na starcie odpowiedź pierwszego goto
    state = {"logged_in": False, "done": False, "goto_done": False, "main_doc": None, "judged": None}

    def add_issue(issue: Issue | None) -> None:
        if issue is not None:
            issue.message = mask_secrets(issue.message, secrets)
            result.issues.append(issue)

    def record(rec: RequestRecord) -> None:
        if state["done"]:
            return
        masked = RequestRecord(
            rec.method, mask_secrets(rec.url, secrets), rec.resource_type, rec.status,
            mask_secrets(rec.error, secrets) if rec.error else None,
        )
        add_issue(classify_request(masked, app_hosts, state["logged_in"]))
        if not (masked.error and "ERR_ABORTED" in masked.error):
            result.failed_requests.append(masked)

    context = None
    try:
        timeout_ms = app.timeout * 1000
        context = browser.new_context(ignore_https_errors=False)
        context.set_default_timeout(timeout_ms)
        context.set_default_navigation_timeout(timeout_ms)
        page = context.new_page()

        def on_console(msg) -> None:
            if state["done"]:
                return
            if msg.type in ("error", "warning"):
                text = mask_secrets(msg.text, secrets)
                result.console_messages.append(f"{msg.type}: {text}")
                add_issue(classify_console(msg.type, text))

        def on_pageerror(err) -> None:
            if state["done"]:
                return
            add_issue(classify_page_error(mask_secrets(err.stack or str(err), secrets)))

        def on_requestfailed(request: Request) -> None:
            if state["done"]:
                return
            failure = request.failure or "nieznany błąd"
            if _is_main_document(request, page):  # dostępność oceniana w judge_main_document
                if "ERR_ABORTED" not in failure:
                    state["main_doc"] = (request.url, failure)
                return
            record(RequestRecord(request.method, request.url, request.resource_type, None, failure))

        def on_response(response: Response) -> None:
            if state["done"]:
                return
            if _is_main_document(response.request, page):
                if not state["goto_done"]:
                    app_hosts.add(urlsplit(response.url).hostname or "")
                state["main_doc"] = response
                return
            if response.status < 400:
                return
            req = response.request
            record(RequestRecord(req.method, req.url, req.resource_type, response.status, None))

        def judge_main_document() -> None:
            """Ocena dokumentu po nawigacji innej niż pierwsze goto (przekierowanie JS, logowanie)."""
            latest = state["main_doc"]
            if latest is None or latest is state["judged"]:
                return
            state["judged"] = latest
            if isinstance(latest, tuple):
                url, failure = latest
                message = f"Serwer nie odpowiada: {failure}"
            elif latest.status >= 400:
                url, message = latest.url, f"HTTP {latest.status} {latest.status_text}".strip()
            else:
                return
            if url != app.url:
                message += f" ({urlsplit(url).path or '/'})"
            add_issue(Issue(Severity.ERROR, "dostępność", message))

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_requestfailed)
        page.on("response", on_response)

        start = time.monotonic()
        try:
            resp = page.goto(app.url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:  # błąd sieci/SSL/timeout dokumentu
            first_line = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            add_issue(Issue(Severity.ERROR, "dostępność", f"Serwer nie odpowiada: {first_line}"))
            if isinstance(e, PlaywrightTimeout) and page.url != "about:blank":
                state["done"] = True  # strona częściowo się otworzyła — warto zobaczyć, jak wygląda
                _take_screenshot(page, app, screenshot_dir, result)
            return result
        state["goto_done"] = True
        state["judged"] = resp
        app_hosts.add(urlsplit(page.url).hostname or "")

        if resp is not None and resp.status >= 400:
            add_issue(Issue(Severity.ERROR, "dostępność", f"HTTP {resp.status} {resp.status_text}".strip()))

        try:
            page.wait_for_load_state("load", timeout=timeout_ms)
            result.load_time_ms = round((time.monotonic() - start) * 1000)
        except PlaywrightTimeout:
            # dokument jest, ale wisi zasób (obraz, skrypt zewnętrzny) — strona zwykle działa
            add_issue(Issue(Severity.WARNING, "dostępność",
                            f"Strona nie zakończyła ładowania w {app.timeout} s"))
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass  # brak networkidle nie jest błędem

        empty_page = Issue(Severity.ERROR, "wyświetlanie", "Pusta strona — nic się nie wyrenderowało")
        if not _has_content(page):
            add_issue(empty_page)
        judge_main_document()

        if app.needs_login:
            login_issue = perform_login(page, app)
            if login_issue is None:
                state["logged_in"] = True
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
                if not _has_content(page):
                    add_issue(empty_page)
            else:
                add_issue(login_issue)
            judge_main_document()

        state["done"] = True
        if result.status is Severity.ERROR:
            _take_screenshot(page, app, screenshot_dir, result)
    except Exception as e:
        add_issue(Issue(Severity.ERROR, "skrypt", f"Błąd skryptu: {e}"))
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
    return result
