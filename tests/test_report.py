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
