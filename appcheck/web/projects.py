"""Moduł Projekty: repozytoria kont GitHub ze statusami (tagi), issues i językami — na żądanie."""
from __future__ import annotations

from typing import Callable, Mapping
from urllib.parse import urlsplit

from fastapi import APIRouter

from appcheck.config import ConfigError
from appcheck.github import DEFAULT_API_URL, RepoInfo, fetch_repos
from appcheck.runner import Projects, collect_projects
from appcheck.statuses import load_statuses
from appcheck.web.jobs import Job
from appcheck.web.settings import Settings

MAX_ISSUES = 30


def safe_url(url: str | None) -> str | None:
    """Tylko adresy http(s) — nic, co mogłoby wykonać kod po kliknięciu (javascript:, data: …)."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return url if parts.scheme in ("http", "https") and parts.netloc else None


def make_work(settings: Settings, env: Mapping[str, str], fetch: Callable = fetch_repos) -> Callable[[], Projects]:
    def work() -> Projects:
        if not settings.github_accounts:
            raise ConfigError("Brak kont GitHub — dopisz do .env: DASHBOARD_GITHUB=konto1,konto2")
        statuses = load_statuses(settings.statuses_path)
        return collect_projects(list(settings.github_accounts), settings.github_token, statuses,
                                api_url=env.get("GITHUB_API_URL") or DEFAULT_API_URL, fetch=fetch)
    return work


def serialize_repo(repo: RepoInfo, mask: Callable[[str], str]) -> dict:
    status = repo.status
    return {
        "name": repo.name,
        "full_name": repo.full_name,
        "html_url": safe_url(repo.html_url),
        "description": mask(repo.description) if repo.description else None,
        "app_url": safe_url(repo.app_url),
        "pushed_at": repo.pushed_at,
        "private": repo.private,
        "languages": [{"name": n, "percent": round(p, 1)} for n, p in repo.languages],
        "main_language": repo.main_language,
        "topics": repo.topics,
        "status": None if status is None else {"tag": status.tag, "label": status.label, "color": status.color},
        "issues_enabled": repo.issues_enabled,
        "issues_count": None if repo.issues is None else len(repo.issues),
        "issues": [{"number": i.number, "title": mask(i.title), "html_url": safe_url(i.html_url),
                    "created_at": i.created_at, "author": i.author}
                   for i in (repo.issues or [])[:MAX_ISSUES]],
    }


def make_router(job: Job, mask: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    def snapshot() -> dict:
        data = job.state()
        projects: Projects | None = job.result
        if projects is None:
            data["repos"] = None
        else:
            repos = [*projects.repo_of.values(), *projects.without_url]
            repos.sort(key=lambda r: r.pushed_at or "", reverse=True)
            data["repos"] = [serialize_repo(r, mask) for r in repos]
        return data

    @router.get("/api/projects")
    def projects():
        return snapshot()

    @router.post("/api/projects/refresh")
    def refresh():
        job.trigger()
        return snapshot()

    return router
