"""Wczytywanie i walidacja konfiguracji (apps.yaml + zmienne środowiskowe)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """Błąd konfiguracji; komunikat po polsku, gotowy do pokazania użytkownikowi."""


@dataclass
class AppConfig:
    name: str
    url: str
    username: str | None = None
    password: str | None = None
    user_selector: str | None = None
    pass_selector: str | None = None
    submit_selector: str | None = None
    timeout: int = 30

    @property
    def needs_login(self) -> bool:
        return self.password is not None


def _not_utf8(path: Path) -> ConfigError:
    return ConfigError(f"{path.name}: plik nie jest zapisany w UTF-8 — zapisz go jako UTF-8")


def load_env_file(path: Path) -> None:
    """Wczytuje zmienne z pliku .env (bez nadpisywania istniejących); brak pliku nie jest błędem."""
    path = Path(path)
    try:
        # utf-8-sig: Notatnik i PowerShell 7 potrafią dopisać BOM
        load_dotenv(path, override=False, encoding="utf-8-sig")
    except UnicodeDecodeError:  # np. UTF-16 z `>` w PowerShell 5.1
        raise _not_utf8(path) from None
    except OSError as e:
        raise ConfigError(f"Nie można odczytać pliku {path}: {e}") from None


def load_config(path: Path, env: Mapping[str, str]) -> list[AppConfig]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError(f"Nie znaleziono pliku konfiguracji: {path}") from None
    except UnicodeDecodeError:
        raise _not_utf8(path) from None
    except OSError as e:
        raise ConfigError(f"Nie można odczytać pliku {path}: {e}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: niepoprawny YAML ({e})") from None

    entries = data.get("apps") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path.name}: brak aplikacji (oczekiwana niepusta lista 'apps')")

    apps: list[AppConfig] = []
    seen: set[str] = set()
    for pos, entry in enumerate(entries, start=1):
        app = _parse_app(pos, entry, env)
        if app.name in seen:
            raise ConfigError(f"{app.name}: nazwa aplikacji powtarza się w konfiguracji")
        seen.add(app.name)
        apps.append(app)
    return apps


def _parse_app(pos: int, entry: object, env: Mapping[str, str]) -> AppConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"pozycja {pos}: wpis aplikacji musi być mapą (name, url, ...)")
    name = entry.get("name")
    label = str(name) if name else f"pozycja {pos}"
    if not name:
        raise ConfigError(f"{label}: brak pola 'name'")
    url = entry.get("url")
    if not url:
        raise ConfigError(f"{label} (pozycja {pos}): brak pola 'url'")
    url = str(url)
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{label}: url musi zaczynać się od http:// lub https://")

    timeout = entry.get("timeout", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError(f"{label}: 'timeout' musi być dodatnią liczbą całkowitą (sekundy)")

    username = password = None
    prefix = entry.get("login")
    if prefix:
        prefix = str(prefix)
        for suffix in ("USER", "PASS"):
            var = f"{prefix}_{suffix}"
            if not env.get(var):
                raise ConfigError(f"{label}: brak zmiennej {var} w .env")
        username, password = env[f"{prefix}_USER"], env[f"{prefix}_PASS"]

    return AppConfig(
        name=str(name),
        url=url,
        username=username,
        password=password,
        user_selector=entry.get("user_selector"),
        pass_selector=entry.get("pass_selector"),
        submit_selector=entry.get("submit_selector"),
        timeout=timeout,
    )
