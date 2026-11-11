"""Sesje, ochrona logowania i middleware bezpieczeństwa dashboardu.

Wymagania: docs/superpowers/specs/2026-11-11-dashboard-design.md, sekcja „Bezpieczeństwo”.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("appcheck.web.security")

SESSION_COOKIE = "__Host-session"
CSRF_HEADER = "x-dashboard"
MAX_BODY_BYTES = 64 * 1024
PUBLIC_API = {"/api/login", "/api/health", "/api/session"}
SAFE_METHODS = {"GET", "HEAD"}

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
}

Clock = Callable[[], float]


def tokens_equal(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class SessionStore:
    """Sesje w pamięci (restart serwera = wylogowanie). Przechowywany jest tylko skrót id sesji."""

    def __init__(self, ttl_seconds: int, clock: Clock = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._expires: dict[str, float] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._expires[_digest(session_id)] = self._clock() + self._ttl
        return session_id

    def valid(self, session_id: str | None) -> bool:
        if not session_id or len(session_id) > 128:
            return False
        with self._lock:
            expires = self._expires.get(_digest(session_id))
            if expires is None:
                return False
            if expires <= self._clock():
                del self._expires[_digest(session_id)]
                return False
            return True

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._expires.pop(_digest(session_id), None)

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, exp in self._expires.items() if exp <= now]:
            del self._expires[key]


class LoginThrottle:
    """Po `max_failures` nieudanych próbach w oknie `lockout` logowanie jest blokowane (globalnie)."""

    def __init__(self, max_failures: int, lockout_seconds: int, clock: Clock = time.monotonic):
        self._max = max_failures
        self._lockout = lockout_seconds
        self._clock = clock
        self._failures: list[float] = []
        self._lock = threading.Lock()

    def _recent(self) -> list[float]:
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < self._lockout]
        return self._failures

    def retry_after(self) -> int:
        """0 — można próbować; inaczej liczba sekund do odblokowania."""
        with self._lock:
            recent = self._recent()
            if len(recent) < self._max:
                return 0
            return max(1, int(recent[-self._max] + self._lockout - self._clock()) + 1)

    def failure(self) -> None:
        with self._lock:
            self._recent().append(self._clock())

    def success(self) -> None:
        with self._lock:
            self._failures.clear()


def _hostname(value: str) -> str | None:
    """Nazwa hosta z nagłówka Host lub adresu Origin (bez portu), małymi literami."""
    try:
        parts = urlsplit(value if "//" in value else f"//{value}")
        host = parts.hostname
    except ValueError:
        return None
    return host.rstrip(".") if host else None


def origin_allowed(origin: str | None, allowed_hosts: tuple[str, ...]) -> bool:
    if not origin or origin == "null":
        return False
    try:
        scheme = urlsplit(origin).scheme
    except ValueError:
        return False
    return scheme in ("http", "https") and _hostname(origin) in allowed_hosts


def _deny(status: int, message: str, headers: dict[str, str] | None = None) -> Response:
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def make_security_middleware(allowed_hosts: tuple[str, ...], sessions: SessionStore):
    async def security_middleware(request: Request, call_next):
        response = await _check(request, call_next)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def _check(request: Request, call_next) -> Response:
        # DNS rebinding: tylko znane nazwy hosta
        if _hostname(request.headers.get("host", "")) not in allowed_hosts:
            return _deny(400, "Nieprawidłowy host")
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return _deny(413, "Za duże żądanie")
        if request.method not in SAFE_METHODS:
            # CSRF: zgodny Origin + własny nagłówek (wymusza preflight CORS, którego nie obsługujemy)
            if not origin_allowed(request.headers.get("origin"), allowed_hosts) \
                    or request.headers.get(CSRF_HEADER) != "1":
                return _deny(403, "Żądanie odrzucone (CSRF)")
        path = request.url.path
        if (path == "/api" or path.startswith("/api/")) and path not in PUBLIC_API:
            if not sessions.valid(request.cookies.get(SESSION_COOKIE)):
                return _deny(401, "Wymagane logowanie")
        return await call_next(request)

    return security_middleware
