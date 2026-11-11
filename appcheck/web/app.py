"""Aplikacja FastAPI dashboardu."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from appcheck.web.security import (
    SESSION_COOKIE, LoginThrottle, SessionStore, make_security_middleware, tokens_equal,
)
from appcheck.web.settings import Settings

log = logging.getLogger("appcheck.web")


class LoginBody(BaseModel):
    token: str = Field(min_length=1, max_length=512)


def create_app(settings: Settings, sessions: SessionStore | None = None,
               throttle: LoginThrottle | None = None) -> FastAPI:
    app = FastAPI(title="App Dashboard", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = sessions or SessionStore(settings.session_ttl_seconds)
    throttle = throttle or LoginThrottle(settings.max_login_failures, settings.lockout_seconds)
    app.state.settings = settings
    app.state.sessions = sessions
    app.middleware("http")(make_security_middleware(settings.allowed_hosts, sessions))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # bez domyślnych szczegółów FastAPI — te powtarzają przesłane dane (np. token)
        return JSONResponse({"error": "Nieprawidłowe dane żądania"}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request):
        wait = throttle.retry_after()
        if wait:
            return JSONResponse({"error": "Zbyt wiele nieudanych prób. Spróbuj później."},
                                status_code=429, headers={"Retry-After": str(wait)})
        if not tokens_equal(body.token, settings.token):
            throttle.failure()
            log.warning("Nieudane logowanie do dashboardu (klient %s)",
                        request.client.host if request.client else "?")
            return JSONResponse({"error": "Nieprawidłowy token"}, status_code=401)
        throttle.success()
        response = JSONResponse({"ok": True})
        response.set_cookie(SESSION_COOKIE, sessions.create(), max_age=settings.session_ttl_seconds,
                            path="/", secure=True, httponly=True, samesite="strict")
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        sessions.revoke(request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/api/session")
    def session():
        return {"authenticated": True}

    return app
