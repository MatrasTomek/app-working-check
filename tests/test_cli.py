from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import BrowserType, Error

import check


def main(argv, tmp_path):
    # Sync API Playwrighta nie działa w wątku z działającą pętlą asyncio, którą
    # utrzymuje sesyjna fixtura `browser` — więc CLI uruchamiamy w osobnym wątku.
    if "--env-file" not in argv:  # nigdy nie czytaj prawdziwego .env z katalogu projektu
        argv = [*argv, "--env-file", str(tmp_path / "brak.env")]
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(check.main, argv).result()


def cfg(tmp_path, body):
    p = tmp_path / "apps.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_exit_0_when_all_ok(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r"), "--env-file", str(tmp_path / "none")], tmp_path) == 0
    report = next((tmp_path / "r").glob("raport-*.html"))
    assert f"Raport: {report.resolve()}" in capsys.readouterr().out


def test_exit_1_on_error(tmp_path, site):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")], tmp_path) == 1


def test_exit_2_on_config_error(tmp_path, capsys):
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a', login: X}\n")
    assert main(["--config", str(p), "--env-file", str(tmp_path / "none")], tmp_path) == 2
    assert "X_USER" in capsys.readouterr().err


def test_only_filters(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--only", "Ok", "--reports-dir", str(tmp_path / "r")], tmp_path) == 0


def test_only_unknown_name_exits_2(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--only", "Nie ma", "--reports-dir", str(tmp_path / "r")], tmp_path) == 2
    assert "Nie ma" in capsys.readouterr().err


def test_password_never_printed(tmp_path, site, capsys, monkeypatch):
    monkeypatch.setenv("P_USER", "jan")
    monkeypatch.setenv("P_PASS", "tajne-haslo-123")
    p = cfg(tmp_path, f"apps:\n  - {{name: P, url: '{site}/login.html', login: P}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r"), "--env-file", str(tmp_path / "none")], tmp_path) == 1
    out = capsys.readouterr()
    html = next((tmp_path / "r").glob("raport-*.html")).read_text(encoding="utf-8")
    assert "Logowanie nieudane" in html  # logowanie faktycznie się odbyło
    assert "tajne-haslo-123" not in out.out + out.err + html


# Hasło z '*', spacją, '~', '"' i polską literą: każdy z tych znaków koduje się inaczej
# w formularzu Chromium, w URL-u fetch, w encodeURIComponent i w JSON.
GET_PASSWORD = 'Ab* c~1"ł'
GET_PASSWORD_FORMS = [
    GET_PASSWORD,
    "Ab*+c%7E1%22%C5%82",    # formularz GET w Chromium
    "Ab*%20c~1%22%C5%82",    # URL fetch / encodeURIComponent
    "Ab%2A%20c~1%22%C5%82",  # urllib.parse.quote
    "Ab%2A+c~1%22%C5%82",    # urllib.parse.quote_plus
    "Ab*+c%7e1%22%c5%82",    # małe litery w kodach %
    'Ab* c~1\\"ł',          # JSON
    "Ab*+c",                 # fragmenty
    "c~1",
    "c%7E1",
]


def test_get_login_password_masked_everywhere(tmp_path, site, capsys, monkeypatch):
    monkeypatch.setenv("G_USER", "jan")
    monkeypatch.setenv("G_PASS", GET_PASSWORD)
    p = cfg(tmp_path, f"apps:\n  - {{name: Formularz GET, url: '{site}/login-get.html', login: G}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")], tmp_path) == 1  # /api/500
    out = capsys.readouterr()
    html = next((tmp_path / "r").glob("raport-*.html")).read_text(encoding="utf-8")
    # logowanie się odbyło: jesteśmy na stronie powitalnej, która wysłała żądania z hasłem
    assert "Formularz GET" in html and "welcome.html?user=jan&amp;pass=***" in html
    assert "/api/500?user=jan&amp;pass=***" in html and "raw=***" in html and "enc=***" in html
    assert "pass&quot;:&quot;***" in html  # JSON w konsoli
    text = out.out + out.err + html
    for form in GET_PASSWORD_FORMS:
        assert form not in text, form
        assert form.replace('"', "&quot;") not in html, form


def test_exit_2_on_non_utf8_config(tmp_path, capsys):
    p = tmp_path / "apps.yaml"
    p.write_bytes("apps:\n  - {name: Księgowość, url: 'https://a'}\n".encode("cp1250"))
    assert main(["--config", str(p)], tmp_path) == 2
    assert "UTF-8" in capsys.readouterr().err


def test_exit_2_on_utf16_env_file(tmp_path, capsys):
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a'}\n")
    env = tmp_path / ".env"
    env.write_text("A_USER=jan\n", encoding="utf-16")
    assert main(["--config", str(p), "--env-file", str(env)], tmp_path) == 2
    err = capsys.readouterr().err
    assert ".env: plik nie jest zapisany w UTF-8" in err and "Traceback" not in err


def _failing_launch(message):
    def launch(self, *a, **kw):
        raise Error(message)
    return launch


def test_exit_2_on_browser_launch_failure(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(BrowserType, "launch", _failing_launch("BrowserType.launch: Target crashed\nszczegóły"))
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a'}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")], tmp_path) == 2
    err = capsys.readouterr().err
    assert "Nie udało się uruchomić przeglądarki: BrowserType.launch: Target crashed" in err


def test_exit_2_when_chromium_missing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(BrowserType, "launch", _failing_launch(
        "BrowserType.launch: Executable doesn't exist at C:\\x\\chrome.exe\n╔════╗"))
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a'}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")], tmp_path) == 2
    assert capsys.readouterr().err.strip() == (
        "Brak przeglądarki Chromium. Uruchom: python -m playwright install chromium")


def test_exit_2_when_report_cannot_be_written(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    blocker = tmp_path / "plik"
    blocker.write_text("to nie katalog", encoding="utf-8")
    assert main(["--config", str(p), "--reports-dir", str(blocker)], tmp_path) == 2
    assert "Nie można zapisać raportu" in capsys.readouterr().err


def test_default_paths_relative_to_script_dir():
    import check as cli

    args = cli._parse_args([])
    base = Path(cli.__file__).resolve().parent
    assert (args.config, args.env_file, args.reports_dir) == (
        base / "apps.yaml", base / ".env", base / "reports")
    explicit = cli._parse_args(["--config", "x.yaml", "--env-file", "e", "--reports-dir", "r"])
    assert (explicit.config, explicit.env_file, explicit.reports_dir) == (Path("x.yaml"), Path("e"), Path("r"))
