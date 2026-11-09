from concurrent.futures import ThreadPoolExecutor

import check


def main(argv):
    # Sync API Playwrighta nie działa w wątku z działającą pętlą asyncio, którą
    # utrzymuje sesyjna fixtura `browser` — więc CLI uruchamiamy w osobnym wątku.
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(check.main, argv).result()


def cfg(tmp_path, body):
    p = tmp_path / "apps.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_exit_0_when_all_ok(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r"), "--env-file", str(tmp_path / "none")]) == 0
    assert "Raport:" in capsys.readouterr().out
    assert list((tmp_path / "r").glob("raport-*.html"))


def test_exit_1_on_error(tmp_path, site):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")]) == 1


def test_exit_2_on_config_error(tmp_path, capsys):
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a', login: X}\n")
    assert main(["--config", str(p), "--env-file", str(tmp_path / "none")]) == 2
    assert "X_USER" in capsys.readouterr().err


def test_only_filters(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--only", "Ok", "--reports-dir", str(tmp_path / "r")]) == 0


def test_only_unknown_name_exits_2(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--only", "Nie ma", "--reports-dir", str(tmp_path / "r")]) == 2
    assert "Nie ma" in capsys.readouterr().err


def test_password_never_printed(tmp_path, site, capsys, monkeypatch):
    monkeypatch.setenv("P_USER", "jan")
    monkeypatch.setenv("P_PASS", "tajne-haslo-123")
    p = cfg(tmp_path, f"apps:\n  - {{name: P, url: '{site}/login.html', login: P}}\n")
    main(["--config", str(p), "--reports-dir", str(tmp_path / "r"), "--env-file", str(tmp_path / "none")])
    out = capsys.readouterr()
    html = next((tmp_path / "r").glob("raport-*.html")).read_text(encoding="utf-8")
    assert "tajne-haslo-123" not in out.out + out.err + html
