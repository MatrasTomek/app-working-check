"""Reguły oceny żądań sieciowych i komunikatów konsoli."""
from urllib.parse import urlsplit

from appcheck.result import Issue, RequestRecord, Severity


def _failed(rec: RequestRecord) -> bool:
    return bool(rec.error) or (rec.status is not None and rec.status >= 400)


def classify_request(rec: RequestRecord, app_host: str, logged_in: bool) -> Issue | None:
    if rec.error and "ERR_ABORTED" in rec.error:
        return None
    parts = urlsplit(rec.url)

    if rec.resource_type in {"xhr", "fetch"}:
        if rec.error or (rec.status is not None and rec.status >= 500):
            return Issue(
                Severity.ERROR,
                "backend",
                f"Backend: {rec.method} {parts.path} → {rec.status or rec.error}",
            )
        if rec.status in (401, 403) and not logged_in:
            return None
        if rec.status is not None and rec.status >= 400:
            return Issue(
                Severity.WARNING,
                "backend",
                f"Backend: {rec.method} {parts.path} → {rec.status}",
            )
        return None

    if not _failed(rec):
        return None
    reason = rec.status or rec.error
    if rec.resource_type == "script" and parts.hostname == app_host:
        return Issue(Severity.ERROR, "zasoby", f"Nie załadował się skrypt aplikacji: {rec.url} → {reason}")
    return Issue(Severity.WARNING, "zasoby", f"Nie załadował się zasób ({rec.resource_type}): {rec.url} → {reason}")


def classify_console(msg_type: str, text: str) -> Issue | None:
    if msg_type == "error":
        return Issue(Severity.WARNING, "konsola", f"Błąd w konsoli: {text}")
    return None


def classify_page_error(text: str) -> Issue:
    return Issue(Severity.WARNING, "konsola", f"Nieobsłużony wyjątek JS: {text}")
