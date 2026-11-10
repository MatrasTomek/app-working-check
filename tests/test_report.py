from datetime import datetime

from appcheck.report import render_terminal, write_html
from appcheck.result import AppResult, Issue, RequestRecord, Severity


def sample():
    ok = AppResult("Strona", "https://a", load_time_ms=1230)
    bad = AppResult("Panel", "https://b", issues=[Issue(Severity.ERROR, "backend", "Backend: GET /api → 500")],
                    console_messages=["error: <script>alert(1)</script>"],
                    failed_requests=[RequestRecord("GET", "https://b/api", "fetch", 500, None)])
    return [ok, bad]


def test_terminal_table():
    out = render_terminal(sample(), color=False)
    assert "Strona" in out and "✅ OK" in out and "1.23 s" in out
    assert "❌ BŁĄD" in out and "[backend] Backend: GET /api → 500" in out
    assert "Razem: 1 OK, 0 ostrzeżeń, 1 błędów" in out
    assert "\x1b[" not in out


def test_terminal_color_adds_ansi():
    assert "\x1b[" in render_terminal(sample(), color=True)


def test_terminal_missing_time_and_multiline_message():
    r = AppResult("X", "https://x", issues=[Issue(Severity.ERROR, "skrypt", "Błąd JS\n  at foo (a.js:1)")])
    out = render_terminal([r], color=False)
    assert "—" in out
    assert "[skrypt] Błąd JS …" in out and "at foo" not in out


def test_html_written(tmp_path):
    p = write_html(sample(), tmp_path / "r.html", datetime(2026, 11, 9, 14, 30))
    t = p.read_text(encoding="utf-8")
    assert "Panel" in t and "2026-11-09 14:30" in t and "https://b/api" in t
    assert '<html lang="pl">' in t


def test_html_escapes_page_content(tmp_path):
    t = write_html(sample(), tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in t and "&lt;script&gt;" in t


def test_html_embeds_screenshot(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    r = sample()
    r[1].screenshot = png
    assert "data:image/png;base64," in write_html(r, tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")


def test_html_missing_screenshot_skipped(tmp_path):
    r = sample()
    r[1].screenshot = tmp_path / "nope.png"
    t = write_html(r, tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")
    assert "data:image/png" not in t


def with_tech():
    from appcheck.techdetect import BACKEND, TechProfile, Technology
    r = sample()
    r[0].tech = TechProfile([Technology("PHP", BACKEND, "PHP", "nagłówek X-Powered-By: PHP/8.2", "8.2")],
                            ["HTML", "CSS", "JavaScript"], ["PHP"])
    r[1].tech = TechProfile([], ["HTML"], [])
    return r


def test_terminal_shows_backend_languages():
    out = render_terminal(with_tech(), color=False)
    assert "Backend" in out and "PHP" in out and "nie rozpoznano" in out


def test_terminal_without_tech_shows_dash():
    out = render_terminal(sample(), color=False)
    assert out.splitlines()[2].rstrip().endswith("—")


def test_html_shows_languages_and_technologies(tmp_path):
    t = write_html(with_tech(), tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")
    assert "frontend: HTML, CSS, JavaScript; backend: PHP" in t
    assert "Technologie (1)" in t and "nagłówek X-Powered-By: PHP/8.2" in t
    assert "backend: nie rozpoznano" in t


def _repo_with_issues():
    from appcheck.github import CiRun, IssueInfo, RepoInfo
    return RepoInfo("lib", "t/lib", "https://github.com/t/lib", languages=[("Python", 100.0)], details=True,
                    ci=CiRun("in_progress", None, "CI", "https://github.com/t/lib/actions/runs/1", "2026-11-10"),
                    ci_known=True,
                    issues=[IssueInfo(7, "Błąd <logowania>", "https://github.com/t/lib/issues/7", "2026-11-09", "ala")])


def test_html_repos_table_ci_issues_and_new_tab_links(tmp_path):
    t = write_html([], tmp_path / "r.html", datetime.now(), [_repo_with_issues()]).read_text(encoding="utf-8")
    assert "⏳ w toku" in t and "<th>CI</th>" in t and "<th>Issues</th>" in t
    assert 'data-target="issues-0">1 ▾</button>' in t and '<tr id="issues-0" class="issues-row" hidden>' in t
    assert "#7 Błąd &lt;logowania&gt;" in t
    links = t.count("<a href=")
    assert links == 3 and t.count('target="_blank" rel="noopener noreferrer"') == links


def test_terminal_repos_ci_and_issues():
    out = render_terminal([], color=False, repos_without_url=[_repo_with_issues()])
    assert "lib — Python 100% · CI: ⏳ w toku · issues: 1" in out
