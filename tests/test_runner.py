from concurrent.futures import ThreadPoolExecutor

import pytest
from playwright.sync_api import BrowserType, Error

from appcheck.config import AppConfig
from appcheck.github import RepoInfo
from appcheck.result import Severity
from appcheck.runner import RunnerError, collect_projects, run_checks
from appcheck.statuses import StatusDef


def _repo(account, name, app_url=None, topics=()):
    return RepoInfo(name=name, full_name=f"{account}/{name}", html_url=f"https://github.com/{account}/{name}",
                    app_url=app_url, topics=list(topics))


def _fake_fetch(data):
    def fetch(account, token, api_url, on_warning=None):
        return data[account]
    return fetch


def test_collect_projects_splits_and_resolves_names():
    data = {
        "a": [_repo("a", "shop", "https://shop"), _repo("a", "lib", topics=["wip"])],
        "b": [_repo("b", "shop", "https://shop-b"), _repo("b", "cfg", "https://cfg")],
    }
    statuses = [StatusDef(tag="wip", label="W toku", color="#000000")]
    seen = []
    p = collect_projects(["a", "b"], None, statuses, existing=[AppConfig(name="cfg", url="https://x")],
                         on_account=seen.append, fetch=_fake_fetch(data))
    assert seen == ["a", "b"]
    assert [a.name for a in p.apps] == ["shop", "b/shop", "b/cfg"]
    assert p.repo_of["b/shop"].full_name == "b/shop"
    assert [r.name for r in p.without_url] == ["lib"]
    assert p.without_url[0].status.label == "W toku"


def _in_thread(fn, *a, **kw):
    # sync API Playwrighta nie działa w wątku z pętlą asyncio sesyjnej fixtury `browser`
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *a, **kw).result()


def test_run_checks_reports_progress(tmp_path, site):
    apps = [AppConfig(name="Ok", url=f"{site}/ok.html"), AppConfig(name="Zle", url=f"{site}/status/502")]
    seen = []
    results = _in_thread(run_checks, apps, tmp_path, on_progress=lambda a: seen.append(a.name))
    assert seen == ["Ok", "Zle"]
    assert [r.status for r in results] == [Severity.OK, Severity.ERROR]


@pytest.mark.parametrize("message, expected", [
    ("BrowserType.launch: Executable doesn't exist at /x", "Brak przeglądarki Chromium"),
    ("BrowserType.launch: Target crashed\nszczegóły", "Nie udało się uruchomić przeglądarki: BrowserType.launch: Target crashed"),
])
def test_run_checks_launch_failure(tmp_path, monkeypatch, message, expected):
    def launch(self, *a, **kw):
        raise Error(message)
    monkeypatch.setattr(BrowserType, "launch", launch)
    with pytest.raises(RunnerError, match=expected):
        _in_thread(run_checks, [AppConfig(name="A", url="https://a")], tmp_path)
