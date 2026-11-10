import pytest

from appcheck.github import GitHubError, fetch_repos, format_languages


def test_lists_repos_with_languages_and_urls(site):
    repos = fetch_repos("tomek", api_url=f"{site}/gh")
    by_name = {r.name: r for r in repos}
    assert [r.name for r in repos] == ["shop", "docs", "lib"]  # bez forków i zarchiwizowanych
    assert by_name["shop"].app_url == f"{site}/ok.html"
    assert by_name["shop"].languages == [("TypeScript", 70.0), ("CSS", 30.0)]
    assert by_name["shop"].pushed_at == "2026-11-01"
    assert by_name["docs"].app_url == f"{site}/tech-next.html"  # z GitHub Pages
    assert by_name["lib"].app_url is None and by_name["lib"].description == "Biblioteka"
    assert not any(r.private for r in repos)


def test_token_owner_sees_private_repos(site):
    repos = fetch_repos("tomek", token="dobry", api_url=f"{site}/gh")
    secret = next(r for r in repos if r.name == "secret")
    assert secret.private and secret.languages == [("Go", 100.0)]


def test_unknown_account(site):
    with pytest.raises(GitHubError, match="Nie znaleziono konta GitHub: nikt"):
        fetch_repos("nikt", api_url=f"{site}/gh")


def test_bad_token(site):
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        fetch_repos("tomek", token="zly", api_url=f"{site}/gh")


def test_rate_limit_suggests_token(site):
    with pytest.raises(GitHubError, match="limit zapytań.*GITHUB_TOKEN"):
        fetch_repos("limit", api_url=f"{site}/gh")


def test_no_connection(dead_url):
    with pytest.raises(GitHubError, match="Nie można połączyć się z GitHub API"):
        fetch_repos("tomek", api_url=dead_url)


def test_format_languages():
    assert format_languages([("TypeScript", 70.4), ("CSS", 29.3), ("Shell", 0.3)]) == "TypeScript 70%, CSS 29%"
    assert format_languages([]) == "—"
