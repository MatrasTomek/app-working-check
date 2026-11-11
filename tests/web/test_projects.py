import dataclasses

from appcheck.github import IssueInfo, RepoInfo
from appcheck.web.app import create_app
from appcheck.web.projects import safe_url

from .conftest import POST_HEADERS, TOKEN, login, make_client


def _client(settings, env=None, fetch=None):
    kw = {"fetch": fetch} if fetch else {}
    c = make_client(create_app(settings, env=env or {}, **kw))
    c.__enter__()
    assert login(c).status_code == 200
    return c


def _refresh(c):
    assert c.post("/api/projects/refresh", headers=POST_HEADERS).status_code == 200
    c.app.state.projects_job.wait(10)
    return c.get("/api/projects").json()


def test_projects_from_fake_github(settings, site):
    s = dataclasses.replace(settings, github_accounts=("tomek",))
    s.base_dir.mkdir(parents=True, exist_ok=True)
    s.statuses_path.write_text('statuses:\n  - {tag: in-progress, label: W toku, color: "#d29922"}\n',
                               encoding="utf-8")
    data = _refresh(_client(s, env={"GITHUB_API_URL": f"{site}/gh"}))
    assert data["error"] is None
    repos = {r["name"]: r for r in data["repos"]}
    assert set(repos) == {"shop", "docs", "lib"}  # forki i archiwa pominięte
    assert repos["shop"]["status"] == {"tag": "in-progress", "label": "W toku", "color": "#d29922"}
    assert repos["shop"]["app_url"].endswith("/ok.html")
    assert repos["lib"]["app_url"] is None
    assert repos["docs"]["issues_enabled"] is False


def test_requires_accounts(settings):
    data = _refresh(_client(settings))
    assert "DASHBOARD_GITHUB" in data["error"] and data["repos"] is None


def test_requires_login(settings):
    with make_client(create_app(settings, env={})) as c:
        assert c.get("/api/projects").status_code == 401
        assert c.post("/api/projects/refresh", headers=POST_HEADERS).status_code == 401


def test_dangerous_urls_dropped_and_secrets_masked(settings):
    def fetch(account, token, api_url, on_warning=None):
        return [RepoInfo(name="x", full_name="a/x", html_url="https://github.com/a/x",
                         app_url="javascript:alert(1)", description=f"opis {TOKEN}",
                         issues=[IssueInfo(1, "tytuł", "data:text/html,<script>", "2026-01-01")])]
    s = dataclasses.replace(settings, github_accounts=("a",))
    data = _refresh(_client(s, fetch=fetch))
    repo = data["repos"][0]
    assert repo["app_url"] is None and repo["issues"][0]["html_url"] is None
    assert TOKEN not in str(data)


def test_github_token_never_returned(settings):
    def fetch(account, token, api_url, on_warning=None):
        return [RepoInfo(name="x", full_name="a/x", html_url="https://github.com/a/x",
                         description=f"zawiera {token}")]
    s = dataclasses.replace(settings, github_accounts=("a",), github_token="ghp_TajnyTokenGitHuba123")
    data = _refresh(_client(s, fetch=fetch))
    assert "ghp_TajnyTokenGitHuba123" not in str(data)


def test_safe_url():
    assert safe_url("https://a.pl/x") == "https://a.pl/x"
    for bad in ("javascript:alert(1)", "data:x", "//evil", "http://", None, "vbscript:x"):
        assert safe_url(bad) is None
