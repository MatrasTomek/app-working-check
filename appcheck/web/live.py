"""Tryb ciągły: cykliczne przebiegi tylko wtedy, gdy klient (PWA) jest aktywny i wysyła heartbeat.

Bez heartbeatu przez `HEARTBEAT_TIMEOUT` sekund tryb wyłącza się sam, a wątek pętli kończy pracę —
w bezczynności backend nic nie robi.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from appcheck.web.jobs import Job

HEARTBEAT_TIMEOUT = 60
MIN_INTERVAL, MAX_INTERVAL = 60, 3600
DEFAULT_INTERVALS = {"servers": 300, "projects": 600}


class LiveMode:
    def __init__(self, jobs: dict[str, Job], clock: Callable[[], float] = time.monotonic,
                 run_thread: bool = True, tick_seconds: float = 1.0):
        self._jobs = jobs
        self._clock = clock
        self._run_thread = run_thread
        self._tick_seconds = tick_seconds
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.enabled = False
        self.intervals = dict(DEFAULT_INTERVALS)
        self._last_heartbeat = 0.0
        self._last_run: dict[str, float] = {}

    def start(self, intervals: dict[str, int] | None = None) -> None:
        with self._lock:
            self.intervals = {**DEFAULT_INTERVALS, **(intervals or {})}
            self.enabled = True
            self._last_heartbeat = self._clock()
            self._last_run = {}  # pierwszy tick uruchamia wszystko od razu
        self.tick()
        if self._thread is not None and self._thread.is_alive() and self._wake.is_set():
            self._thread.join(self._tick_seconds + 1)  # poprzednia pętla właśnie się kończy (Stop → Start)
        if self._run_thread and (self._thread is None or not self._thread.is_alive()):
            self._wake.clear()
            self._thread = threading.Thread(target=self._loop, name="live-mode", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self.enabled = False
        self._wake.set()

    def heartbeat(self) -> bool:
        with self._lock:
            if self.enabled:
                self._last_heartbeat = self._clock()
            return self.enabled

    def tick(self) -> None:
        to_trigger = []
        with self._lock:
            if not self.enabled:
                return
            now = self._clock()
            if now - self._last_heartbeat > HEARTBEAT_TIMEOUT:
                self.enabled = False  # klient zniknął (zamknięta aplikacja, wygaszony ekran)
                return
            for name, interval in self.intervals.items():
                last = self._last_run.get(name)
                if name in self._jobs and (last is None or now - last >= interval):
                    self._last_run[name] = now
                    to_trigger.append(self._jobs[name])
        for job in to_trigger:
            job.trigger()

    def _loop(self) -> None:
        while self.enabled:
            self.tick()
            if self._wake.wait(self._tick_seconds):
                break

    def state(self) -> dict:
        with self._lock:
            expires_in = (max(0, int(HEARTBEAT_TIMEOUT - (self._clock() - self._last_heartbeat)))
                          if self.enabled else None)
            return {"enabled": self.enabled, "intervals": dict(self.intervals), "expires_in": expires_in}


class StartBody(BaseModel):
    servers_interval: int = Field(DEFAULT_INTERVALS["servers"], ge=MIN_INTERVAL, le=MAX_INTERVAL)
    projects_interval: int = Field(DEFAULT_INTERVALS["projects"], ge=MIN_INTERVAL, le=MAX_INTERVAL)


def make_router(live: LiveMode) -> APIRouter:
    router = APIRouter()

    @router.get("/api/live")
    def state():
        return live.state()

    @router.post("/api/live/start")
    def start(body: StartBody | None = None):
        body = body or StartBody()
        live.start({"servers": body.servers_interval, "projects": body.projects_interval})
        return live.state()

    @router.post("/api/live/stop")
    def stop():
        live.stop()
        return live.state()

    @router.post("/api/live/heartbeat")
    def heartbeat():
        live.heartbeat()
        return live.state()

    return router
