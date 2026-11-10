import pytest

from appcheck.github import GitHubError, fetch_repos, format_languages, repo_languages_text


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


def test_rate_limit_during_details_gives_partial_data(site, monkeypatch):
    import appcheck.github as gh

    real_open = gh._Client._open

    def limited_open(self, url):  # serwer odmawia zapytań o języki
        if url.endswith("/languages"):
            req = gh.urllib.request.Request(url, headers={"X-Test-Limit-Languages": "1"})
            try:
                return gh.urllib.request.urlopen(req, timeout=5)
            except gh.urllib.error.HTTPError as e:
                raise self._http_error(e) from None
        return real_open(self, url)

    monkeypatch.setattr(gh._Client, "_open", limited_open)
    warnings = []
    repos = fetch_repos("tomek", api_url=f"{site}/gh", on_warning=warnings.append)
    by_name = {r.name: r for r in repos}
    assert len(warnings) == 1 and "limit zapytań" in warnings[0]
    assert by_name["shop"].languages == [] and by_name["shop"].main_language == "TypeScript"
    assert by_name["shop"].app_url == f"{site}/ok.html"
    assert by_name["docs"].app_url is not None
    assert repo_languages_text(by_name["lib"]) == "Python (główny)"
    assert repo_languages_text(by_name["docs"]) == "—"


def test_ci_status_and_issues(site):
    from appcheck.github import ci_label, issues_label

    by_name = {r.name: r for r in fetch_repos("tomek", token="dobry", api_url=f"{site}/gh")}
    shop, lib, docs, secret = by_name["shop"], by_name["lib"], by_name["docs"], by_name["secret"]
    assert ci_label(shop) == "⏳ w toku" and ci_label(lib) == "❌ błąd" and ci_label(docs) == "brak CI"
    assert ci_label(secret) == "brak dostępu" and issues_label(secret) == "brak dostępu"
    assert [i.number for i in shop.issues] == [1, 3]  # bez pull requestów
    assert shop.issues[0].title == "Zgłoszenie <1>" and shop.issues[0].author == "ala"
    assert issues_label(shop) == "2" and issues_label(lib) == "0" and issues_label(docs) == "wyłączone"
