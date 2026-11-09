import pytest

from appcheck.config import AppConfig, ConfigError, load_config


def write(tmp_path, text):
    p = tmp_path / "apps.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_public_and_login_apps(tmp_path):
    p = write(tmp_path, """
apps:
  - name: Strona
    url: https://example.com
  - name: Panel
    url: https://panel.example.com/login
    login: PANEL
    timeout: 60
""")
    apps = load_config(p, {"PANEL_USER": "jan", "PANEL_PASS": "x"})
    assert apps[0] == AppConfig("Strona", "https://example.com")
    assert (apps[1].username, apps[1].password, apps[1].timeout) == ("jan", "x", 60)
    assert apps[1].needs_login and not apps[0].needs_login


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Nie znaleziono pliku"):
        load_config(tmp_path / "brak.yaml", {})


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="niepoprawny YAML"):
        load_config(write(tmp_path, "apps: [\n"), {})


def test_missing_url_names_position(tmp_path):
    with pytest.raises(ConfigError, match=r"pozycja 1.*url"):
        load_config(write(tmp_path, "apps:\n  - name: A\n"), {})


def test_bad_scheme(tmp_path):
    with pytest.raises(ConfigError, match="A.*http"):
        load_config(write(tmp_path, "apps:\n  - name: A\n    url: example.com\n"), {})


def test_duplicate_names(tmp_path):
    y = "apps:\n  - {name: A, url: 'https://a'}\n  - {name: A, url: 'https://b'}\n"
    with pytest.raises(ConfigError, match="powtarza"):
        load_config(write(tmp_path, y), {})


def test_missing_env_password(tmp_path):
    y = "apps:\n  - {name: Panel, url: 'https://a', login: PANEL}\n"
    with pytest.raises(ConfigError, match="Panel.*PANEL_PASS"):
        load_config(write(tmp_path, y), {"PANEL_USER": "jan"})


def test_empty_apps_list(tmp_path):
    with pytest.raises(ConfigError, match="brak aplikacji"):
        load_config(write(tmp_path, "apps: []\n"), {})


def test_missing_name_names_position(tmp_path):
    with pytest.raises(ConfigError, match=r"pozycja 2.*name"):
        load_config(write(tmp_path, "apps:\n  - {name: A, url: 'https://a'}\n  - {url: 'https://b'}\n"), {})


def test_default_timeout_and_selectors(tmp_path):
    y = ("apps:\n  - {name: P, url: 'https://a', login: P, user_selector: '#u',"
         " pass_selector: '#p', submit_selector: '#s'}\n")
    app = load_config(write(tmp_path, y), {"P_USER": "u", "P_PASS": "p"})[0]
    assert app.timeout == 30
    assert (app.user_selector, app.pass_selector, app.submit_selector) == ("#u", "#p", "#s")


def test_non_utf8_yaml_gives_clear_message(tmp_path):
    p = tmp_path / "apps.yaml"
    p.write_bytes("apps:\n  - {name: Księgowość, url: 'https://a'}\n".encode("cp1250"))
    with pytest.raises(ConfigError, match="apps.yaml: plik nie jest zapisany w UTF-8 — zapisz go jako UTF-8"):
        load_config(p, {})


def test_utf16_env_file_gives_clear_message(tmp_path):
    from appcheck.config import load_env_file

    p = tmp_path / ".env"
    p.write_text("P_USER=jan\nP_PASS=x\n", encoding="utf-16")  # jak `>` w PowerShell 5.1
    with pytest.raises(ConfigError, match=r"\.env: plik nie jest zapisany w UTF-8 — zapisz go jako UTF-8"):
        load_env_file(p)


def test_env_file_loaded_without_overriding(tmp_path, monkeypatch):
    from appcheck.config import load_env_file

    monkeypatch.setenv("E_USER", "z-systemu")
    monkeypatch.setenv("E_PASS", "")
    monkeypatch.delenv("E_PASS")  # monkeypatch przywróci stan po teście
    p = tmp_path / ".env"
    p.write_text("E_USER=jan\nE_PASS=ł\n", encoding="utf-8-sig")
    load_env_file(p)
    import os
    assert os.environ["E_USER"] == "z-systemu" and os.environ["E_PASS"] == "ł"
    load_env_file(tmp_path / "brak")  # brak pliku nie jest błędem
