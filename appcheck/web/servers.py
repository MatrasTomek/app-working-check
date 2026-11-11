"""Moduł Serwery: sprawdzanie aplikacji z apps.yaml (i repozytoriów GitHub z adresem) na żądanie."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from appcheck.config import load_config
from appcheck.github import DEFAULT_API_URL, fetch_repos
from appcheck.result import AppResult
from appcheck.runner import collect_projects, run_checks
from appcheck.statuses import load_statuses
from appcheck.web.jobs import Job
from appcheck.web.settings import Settings

KEEP_RUNS = 5
MAX_LIST = 50
_RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
_FILE = re.compile(r"^[a-z0-9-]{1,120}\.png$")


@dataclass
class ServersRun:
    run_id: str
    results: list[AppResult]
    screenshots: set[str] = field(default_factory=set)  # nazwy plików z tego przebiegu


SECRET_SUFFIXES = ("_PASS", "_PASSWORD", "_TOKEN", "_SECRET", "_KEY")


def collect_secrets(env: Mapping[str, str]) -> list[str]:
    """Wartości (hasła aplikacji, tokeny), które nigdy nie mogą trafić do odpowiedzi API."""
    values = [v for k, v in env.items() if k.upper().endswith(SECRET_SUFFIXES)]
    return [v for v in dict.fromkeys(values) if v and len(v) >= 4]


def _prune_runs(root: Path, keep: int) -> None:
    runs = sorted(p for p in root.iterdir() if p.is_dir() and _RUN_ID.match(p.name))
    for old in runs[:-keep] if keep else runs:
        shutil.rmtree(old, ignore_errors=True)


def make_work(settings: Settings, env: Mapping[str, str],
              check_runner: Callable[..., list[AppResult]] = run_checks,
              fetch: Callable = fetch_repos) -> Callable[[], ServersRun]:
    def work() -> ServersRun:
        apps = load_config(settings.config_path, env) if settings.config_path.exists() else []
        repo_of = {}
        if settings.github_accounts:
            statuses = load_statuses(settings.statuses_path) if settings.statuses_path.exists() else []
            projects = collect_projects(list(settings.github_accounts), settings.github_token, statuses,
                                        existing=apps, api_url=env.get("GITHUB_API_URL") or DEFAULT_API_URL,
                                        fetch=fetch)
            apps = [*apps, *projects.apps]
            repo_of = projects.repo_of
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        root = settings.reports_dir / "dashboard"
        results = check_runner(apps, root / run_id, repo_of=repo_of)
        shots = {r.screenshot.name for r in results if r.screenshot}
        if root.exists():
            _prune_runs(root, KEEP_RUNS)
        return ServersRun(run_id, results, shots)
    return work


def serialize_result(r: AppResult, run_id: str, mask: Callable[[str], str]) -> dict:
    tech = r.tech
    return {
        "name": mask(r.name),
        "url": mask(r.url),
        "status": r.status.name.lower(),
        "status_label": r.status.label,
        "load_time_ms": r.load_time_ms,
        "issues": [{"severity": i.severity.name.lower(), "category": i.category, "message": mask(i.message)}
                   for i in r.issues[:MAX_LIST]],
        "console": [mask(m) for m in r.console_messages[:MAX_LIST]],
        "failed_requests": [{"method": f.method, "url": mask(f.url), "type": f.resource_type,
                             "status": f.status, "error": mask(f.error) if f.error else None}
                            for f in r.failed_requests[:MAX_LIST]],
        "tech": None if tech is None else {
            "frontend": tech.frontend_languages,
            "backend": tech.backend_languages,
            "technologies": [{"name": t.name, "version": t.version, "side": t.side}
                             for t in tech.technologies],
        },
        "repo": None if r.repo is None else {"full_name": r.repo.full_name, "html_url": r.repo.html_url},
        "screenshot": f"/api/screenshots/{run_id}/{r.screenshot.name}" if r.screenshot else None,
    }


def make_router(settings: Settings, job: Job, mask: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    def snapshot() -> dict:
        data = job.state()
        run: ServersRun | None = job.result
        if run is None:
            data["run"] = None
        else:
            apps = [serialize_result(r, run.run_id, mask) for r in run.results]
            counts = {s: sum(a["status"] == s for a in apps) for s in ("ok", "warning", "error")}
            data["run"] = {"id": run.run_id, "apps": apps, "counts": counts}
        return data

    @router.get("/api/servers")
    def servers():
        return snapshot()

    @router.post("/api/servers/check")
    def check():
        job.trigger()
        return snapshot()

    @router.get("/api/screenshots/{run_id}/{filename}")
    def screenshot(run_id: str, filename: str):
        run: ServersRun | None = job.result
        if (run is None or run_id != run.run_id or filename not in run.screenshots
                or not _RUN_ID.match(run_id) or not _FILE.match(filename)):
            return JSONResponse({"error": "Nie znaleziono"}, status_code=404)
        root = (settings.reports_dir / "dashboard").resolve()
        path = (root / run_id / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return JSONResponse({"error": "Nie znaleziono"}, status_code=404)
        return FileResponse(path, media_type="image/png")

    return router
