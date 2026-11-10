"""Pobieranie listy repozytoriów konta GitHub (użytkownika lub organizacji) przez REST API.

Dla każdego repozytorium: opis, języki z udziałem procentowym (liczone przez GitHub z kodu)
oraz adres działającej aplikacji — pole „Website” albo GitHub Pages. Bez zależności spoza
biblioteki standardowej.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote

DEFAULT_API_URL = "https://api.github.com"
_TIMEOUT = 30


class GitHubError(Exception):
    """Błąd pobierania danych z GitHuba; komunikat po polsku, gotowy do pokazania użytkownikowi."""


@dataclass
class CiRun:
    """Ostatnie uruchomienie GitHub Actions na głównej gałęzi."""
    status: str  # queued / in_progress / completed / …
    conclusion: str | None  # success / failure / cancelled / … (gdy completed)
    workflow: str
    html_url: str
    created_at: str  # RRRR-MM-DD


@dataclass
class IssueInfo:
    number: int
    title: str
    html_url: str
    created_at: str  # RRRR-MM-DD
    author: str | None = None


@dataclass
class RepoInfo:
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    app_url: str | None = None
    pushed_at: str | None = None  # RRRR-MM-DD
    private: bool = False
    languages: list[tuple[str, float]] = field(default_factory=list)  # (język, %), malejąco
    main_language: str | None = None  # główny język z listy repozytoriów (bez dodatkowych zapytań)
    details: bool = False  # czy pobrano CI i issues (False — limit zapytań)
    ci: CiRun | None = None  # None — brak uruchomień CI albo brak dostępu (patrz ci_known)
    ci_known: bool = False  # False — nie udało się sprawdzić (brak uprawnienia Actions w tokenie)
    issues_enabled: bool = True
    issues: list[IssueInfo] | None = None  # None — brak dostępu (uprawnienie Issues w tokenie)


def format_languages(languages: list[tuple[str, float]], limit: int = 6) -> str:
    shown = [f"{lang} {pct:.0f}%" for lang, pct in languages if pct >= 0.5][:limit]
    return ", ".join(shown) or "—"


_CI_LABELS = {
    "success": "✅ sukces",
    "failure": "❌ błąd",
    "timed_out": "❌ przekroczony czas",
    "startup_failure": "❌ błąd uruchomienia",
    "cancelled": "⏹ anulowano",
    "action_required": "⚠️ wymaga akcji",
    "skipped": "— pominięto",
    "neutral": "— neutralny",
    "stale": "— nieaktualny",
}
_CI_PENDING = {"queued": "⏳ w kolejce", "in_progress": "⏳ w toku", "waiting": "⏳ czeka",
               "requested": "⏳ w kolejce", "pending": "⏳ w kolejce"}


def ci_label(repo: RepoInfo) -> str:
    if not repo.details:
        return "—"
    if not repo.ci_known:
        return "brak dostępu"
    if repo.ci is None:
        return "brak CI"
    if repo.ci.status != "completed":
        return _CI_PENDING.get(repo.ci.status, f"⏳ {repo.ci.status}")
    return _CI_LABELS.get(repo.ci.conclusion or "", repo.ci.conclusion or "zakończono")


def issues_label(repo: RepoInfo) -> str:
    if not repo.details:
        return "—"
    if not repo.issues_enabled:
        return "wyłączone"
    if repo.issues is None:
        return "brak dostępu"
    return str(len(repo.issues))


def repo_languages_text(repo: RepoInfo) -> str:
    if repo.languages:
        return format_languages(repo.languages)
    if repo.main_language:
        return f"{repo.main_language} (główny)"
    return "—"


class _Client:
    def __init__(self, api_url: str, token: str | None):
        self.api_url = api_url.rstrip("/")
        self.token = token

    def _open(self, url: str):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "app-working-check",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=_TIMEOUT)
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise GitHubError(f"Nie można połączyć się z GitHub API ({self.api_url}): {reason}") from None

    def _http_error(self, e: urllib.error.HTTPError) -> GitHubError:
        if e.code == 401:
            return GitHubError("GitHub odrzucił GITHUB_TOKEN (HTTP 401) — sprawdź token w .env")
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            hint = "" if self.token else " — dodaj GITHUB_TOKEN do .env (limit 5000 zapytań/h)"
            return _RateLimitError(f"Przekroczono limit zapytań GitHub API{hint}")
        return _StatusError(e.code, f"GitHub API: HTTP {e.code} dla {e.url}")

    def get(self, path: str):
        with self._open(f"{self.api_url}{path}") as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_all(self, path: str) -> list:
        """Wszystkie strony listy (nagłówek Link: rel="next")."""
        items: list = []
        url: str | None = f"{self.api_url}{path}"
        while url:
            with self._open(url) as resp:
                items += json.loads(resp.read().decode("utf-8"))
                m = re.search(r'<([^>]+)>;\s*rel="next"', resp.headers.get("Link") or "")
                url = m.group(1) if m else None
        return items


class _RateLimitError(GitHubError):
    pass


class _StatusError(GitHubError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _list_path(client: _Client, account: str) -> str:
    try:
        owner = client.get(f"/users/{quote(account)}")
    except _StatusError as e:
        if e.status == 404:
            raise GitHubError(f"Nie znaleziono konta GitHub: {account}") from None
        raise
    if client.token:
        me = client.get("/user")
        if str(me.get("login", "")).lower() == account.lower():
            return "/user/repos?affiliation=owner&per_page=100"  # także prywatne
        if owner.get("type") == "Organization":
            return f"/orgs/{quote(account)}/repos?type=all&per_page=100"
    return f"/users/{quote(account)}/repos?type=owner&per_page=100"


def _app_url(client: _Client, repo: dict, details: bool) -> str | None:
    homepage = (repo.get("homepage") or "").strip()
    if homepage:
        return homepage if homepage.startswith(("http://", "https://")) else f"https://{homepage}"
    if not repo.get("has_pages"):
        return None
    try:
        if not details:
            raise _StatusError(0, "pominięte po przekroczeniu limitu")
        pages = client.get(f"/repos/{repo['full_name']}/pages")
        if pages.get("html_url"):
            return pages["html_url"]
    except _StatusError:
        pass
    owner = repo["full_name"].split("/", 1)[0].lower()
    if repo["name"].lower() == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo['name']}/"


def _languages(client: _Client, full_name: str) -> list[tuple[str, float]]:
    data = client.get(f"/repos/{full_name}/languages")
    total = sum(data.values())
    if not total:
        return []
    return sorted(((lang, n * 100 / total) for lang, n in data.items()), key=lambda x: -x[1])


def _ci(client: _Client, repo: dict) -> tuple[CiRun | None, bool]:
    """(ostatnie uruchomienie CI, czy udało się sprawdzić)."""
    branch = quote(repo.get("default_branch") or "main")
    try:
        data = client.get(f"/repos/{repo['full_name']}/actions/runs?per_page=1&branch={branch}")
    except _StatusError:
        return None, False
    runs = data.get("workflow_runs") or []
    if not runs:
        return None, True
    run = runs[0]
    return CiRun(
        status=run.get("status") or "",
        conclusion=run.get("conclusion"),
        workflow=run.get("name") or run.get("display_title") or "",
        html_url=run.get("html_url") or "",
        created_at=(run.get("created_at") or "")[:10],
    ), True


def _issues(client: _Client, repo: dict) -> list[IssueInfo] | None:
    try:
        items = client.get_all(f"/repos/{repo['full_name']}/issues?state=open&per_page=100")
    except _StatusError:
        return None
    return [
        IssueInfo(
            number=i["number"],
            title=i.get("title") or "",
            html_url=i.get("html_url") or "",
            created_at=(i.get("created_at") or "")[:10],
            author=(i.get("user") or {}).get("login"),
        )
        for i in items if "pull_request" not in i  # API issues zwraca też pull requesty
    ]


def fetch_repos(account: str, token: str | None = None, api_url: str = DEFAULT_API_URL,
                on_warning: Callable[[str], None] | None = None) -> list[RepoInfo]:
    """Repozytoria konta (bez forków i zarchiwizowanych), od ostatnio zmienianego.

    Gdy limit zapytań skończy się dopiero przy szczegółach (języki, GitHub Pages), zwraca dane
    częściowe — główny język z listy repozytoriów — i zgłasza ostrzeżenie przez ``on_warning``.
    """
    client = _Client(api_url, token)
    raw = [r for r in client.get_all(_list_path(client, account))
           if not r.get("fork") and not r.get("archived")]
    raw.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    details = True
    repos = []
    for r in raw:
        languages: list[tuple[str, float]] = []
        ci, ci_known, issues = None, False, None
        issues_enabled = r.get("has_issues", True)
        try:
            app_url = _app_url(client, r, details)
            if details:
                languages = _languages(client, r["full_name"])
                ci, ci_known = _ci(client, r)
                issues = _issues(client, r) if issues_enabled else []
        except _RateLimitError as e:
            if details and on_warning:
                on_warning(f"{e}; dla pozostałych repozytoriów pokazano tylko główny język")
            details = False
            app_url = _app_url(client, r, details)
            languages, ci, ci_known, issues = [], None, False, None
        repos.append(RepoInfo(
            name=r["name"],
            full_name=r["full_name"],
            html_url=r["html_url"],
            description=r.get("description"),
            app_url=app_url,
            pushed_at=(r.get("pushed_at") or "")[:10] or None,
            private=bool(r.get("private")),
            languages=languages,
            main_language=r.get("language"),
            details=details,
            ci=ci,
            ci_known=ci_known,
            issues_enabled=issues_enabled,
            issues=issues,
        ))
    return repos
