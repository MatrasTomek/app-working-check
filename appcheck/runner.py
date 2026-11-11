"""Wspólna logika sprawdzania — używana przez CLI (check.py) i dashboard (appcheck.web)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from appcheck.browser_check import check_app
from appcheck.config import AppConfig
from appcheck.github import DEFAULT_API_URL, RepoInfo, fetch_repos
from appcheck.result import AppResult
from appcheck.statuses import StatusDef, resolve_status


class RunnerError(Exception):
    """Nie udało się uruchomić Playwrighta lub przeglądarki — komunikat gotowy dla użytkownika."""


@dataclass
class Projects:
    """Repozytoria z GitHuba podzielone na aplikacje do sprawdzenia i repozytoria bez adresu."""

    apps: list[AppConfig] = field(default_factory=list)
    repo_of: dict[str, RepoInfo] = field(default_factory=dict)
    without_url: list[RepoInfo] = field(default_factory=list)


def _first_line(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


def collect_projects(
    accounts: list[str],
    token: str | None,
    statuses: list[StatusDef],
    existing: list[AppConfig] = (),
    api_url: str = DEFAULT_API_URL,
    on_account: Callable[[str], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
    fetch: Callable[..., list[RepoInfo]] = fetch_repos,
) -> Projects:
    """Pobiera repozytoria kont GitHub. Nazwa kolidująca z `existing` lub innym kontem
    dostaje postać `konto/repozytorium`. Rzuca GitHubError."""
    projects = Projects()
    taken = {a.name for a in existing}
    for account in accounts:
        if on_account:
            on_account(account)
        for repo in fetch(account, token, api_url, on_warning=on_warning):
            repo.status = resolve_status(repo.topics, statuses)
            if repo.app_url is None:
                projects.without_url.append(repo)
                continue
            name = repo.full_name if repo.name in taken else repo.name
            taken.add(name)
            projects.apps.append(AppConfig(name=name, url=repo.app_url))
            projects.repo_of[name] = repo
    return projects


def run_checks(
    apps: list[AppConfig],
    screenshot_dir: Path,
    headed: bool = False,
    repo_of: dict[str, RepoInfo] | None = None,
    on_progress: Callable[[AppConfig], None] | None = None,
) -> list[AppResult]:
    """Sprawdza aplikacje w przeglądarce Chromium. Rzuca RunnerError, gdy nie da się jej uruchomić."""
    results: list[AppResult] = []
    try:
        pw = sync_playwright().start()
    except PlaywrightError as e:
        raise RunnerError(f"Nie udało się uruchomić Playwrighta: {_first_line(e)}") from e
    try:
        try:
            browser = pw.chromium.launch(headless=not headed)
        except PlaywrightError as e:
            if "Executable doesn't exist" in str(e):
                raise RunnerError(
                    "Brak przeglądarki Chromium. Uruchom: python -m playwright install chromium") from e
            raise RunnerError(f"Nie udało się uruchomić przeglądarki: {_first_line(e)}") from e
        try:
            for app in apps:
                if on_progress:
                    on_progress(app)
                result = check_app(browser, app, screenshot_dir)
                result.repo = (repo_of or {}).get(app.name)
                results.append(result)
        finally:
            browser.close()
    finally:
        pw.stop()
    return results
