"""Reguły oceny żądań sieciowych i komunikatów konsoli."""
from __future__ import annotations

import ipaddress
from typing import Collection
from urllib.parse import urlsplit

import tldextract

from appcheck.result import Issue, RequestRecord, Severity


def _failed(rec: RequestRecord) -> bool:
    return bool(rec.error) or (rec.status is not None and rec.status >= 400)


# Lista sufiksów publicznych (PSL) wbudowana w bibliotekę — bez pobierania z sieci.
# Domeny prywatne (np. herokuapp.com, github.io) też są sufiksami: app1.herokuapp.com
# i app2.herokuapp.com to różni właściciele.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


def _registrable_domain(host: str) -> str | None:
    """Domena rejestrowalna, np. ``firma.com.pl`` dla ``panel.firma.com.pl``; ``None`` dla IP/localhost."""
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    ext = _extract(host)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}"


def _is_own_host(host: str, app_hosts: Collection[str]) -> bool:
    """Host aplikacji albo inny host w tej samej domenie rejestrowalnej (np. api.firma.com.pl)."""
    if not host:
        return False
    if host in app_hosts:
        return True
    domain = _registrable_domain(host)
    return domain is not None and any(_registrable_domain(h) == domain for h in app_hosts if h)


def classify_request(rec: RequestRecord, app_hosts: Collection[str], logged_in: bool) -> Issue | None:
    if rec.error and "ERR_ABORTED" in rec.error:
        return None
    parts = urlsplit(rec.url)
    host = parts.hostname or ""

    if rec.resource_type in {"xhr", "fetch"}:
        target = parts.path if host in app_hosts else f"{host}{parts.path}"
        if rec.error or (rec.status is not None and rec.status >= 500):
            # awaria cudzego API (analityka, widżety) nie oznacza, że aplikacja nie działa
            severity = Severity.ERROR if _is_own_host(host, app_hosts) else Severity.WARNING
            return Issue(severity, "backend", f"Backend: {rec.method} {target} → {rec.status or rec.error}")
        if rec.status in (401, 403) and not logged_in:
            return None
        if rec.status is not None and rec.status >= 400:
            return Issue(Severity.WARNING, "backend", f"Backend: {rec.method} {target} → {rec.status}")
        return None

    if not _failed(rec):
        return None
    reason = rec.status or rec.error
    if rec.resource_type == "script" and host in app_hosts:
        return Issue(Severity.ERROR, "zasoby", f"Nie załadował się skrypt aplikacji: {rec.url} → {reason}")
    return Issue(Severity.WARNING, "zasoby", f"Nie załadował się zasób ({rec.resource_type}): {rec.url} → {reason}")


def classify_console(msg_type: str, text: str) -> Issue | None:
    if msg_type == "error":
        return Issue(Severity.WARNING, "konsola", f"Błąd w konsoli: {text}")
    return None


def classify_page_error(text: str) -> Issue:
    return Issue(Severity.WARNING, "konsola", f"Nieobsłużony wyjątek JS: {text}")
