"""Zadania w tle: najwyżej jeden przebieg naraz, wynik i stan do odczytu przez API."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from appcheck.config import ConfigError
from appcheck.github import GitHubError
from appcheck.runner import RunnerError

log = logging.getLogger("appcheck.web.jobs")

# Błędy z komunikatem przeznaczonym dla użytkownika; pozostałe — tylko w logu serwera.
USER_ERRORS = (ConfigError, GitHubError, RunnerError)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Job:
    def __init__(self, name: str, work: Callable[[], Any], mask: Callable[[str], str] = lambda s: s):
        self.name = name
        self._work = work
        self._mask = mask
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.running = False
        self.result: Any = None
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.error: str | None = None

    def trigger(self) -> bool:
        """Uruchamia przebieg w tle; False, gdy poprzedni jeszcze trwa."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.started_at = _now()
            self._thread = threading.Thread(target=self._run, name=f"job-{self.name}", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _run(self) -> None:
        error = None
        result = None
        try:
            result = self._work()
        except USER_ERRORS as e:
            error = self._mask(str(e))
        except Exception:  # noqa: BLE001 — szczegóły (mogą zawierać dane) tylko w logu
            log.exception("Zadanie %s zakończone błędem", self.name)
            error = "Błąd wewnętrzny — szczegóły w logu serwera"
        with self._lock:
            if error is None:
                self.result = result
            self.error = error
            self.finished_at = _now()
            self.running = False

    def state(self) -> dict:
        with self._lock:
            return {"state": "running" if self.running else "idle", "started_at": self.started_at,
                    "finished_at": self.finished_at, "error": self.error}
