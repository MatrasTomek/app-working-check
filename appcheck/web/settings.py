"""Ustawienia dashboardu z zmiennych środowiskowych (.env)."""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from appcheck.config import ConfigError

MIN_TOKEN_LENGTH = 32
DEFAULT_PORT = 8765
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_LOOPBACK_NAMES = {"localhost"}


def is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_token(token: str | None) -> str:
    if not token:
        raise ConfigError(
            "Brak DASHBOARD_TOKEN w .env. Wygeneruj token: python serve.py --gen-token "
            "i dopisz do .env: DASHBOARD_TOKEN=<token>")
    if len(token) < MIN_TOKEN_LENGTH or any(c.isspace() for c in token) or len(set(token)) < 12:
        raise ConfigError(
            f"DASHBOARD_TOKEN jest za słaby (min. {MIN_TOKEN_LENGTH} znaków, losowy, bez spacji). "
            "Wygeneruj nowy: python serve.py --gen-token")
    return token


def _parse_hosts(raw: str) -> tuple[str, ...]:
    hosts = []
    for item in raw.split(","):
        host = item.strip().lower().rstrip(".")
        if not host:
            continue
        if not _HOSTNAME.match(host):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                raise ConfigError(f"DASHBOARD_ALLOWED_HOSTS: nieprawidłowa nazwa hosta: {item.strip()!r}") from None
        hosts.append(host)
    return tuple(hosts)


def _parse_accounts(raw: str) -> tuple[str, ...]:
    accounts = tuple(a.strip() for a in raw.split(",") if a.strip())
    for a in accounts:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", a):
            raise ConfigError(f"DASHBOARD_GITHUB: nieprawidłowa nazwa konta GitHub: {a!r}")
    return accounts


@dataclass(frozen=True)
class Settings:
    token: str
    base_dir: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    github_accounts: tuple[str, ...] = ()
    github_token: str | None = None
    agents_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects")
    claude_sessions_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "sessions")
    copilot_dir: Path = field(default_factory=lambda: Path.home() / ".copilot")
    vscode_storage_dirs: tuple[Path, ...] = field(default_factory=lambda: (
        Path.home() / ".config" / "Code" / "User" / "workspaceStorage",
        Path.home() / ".vscode-server" / "data" / "User" / "workspaceStorage",
    ))
    session_ttl_seconds: int = 7 * 24 * 3600
    max_login_failures: int = 5
    lockout_seconds: int = 15 * 60

    @property
    def config_path(self) -> Path:
        return self.base_dir / "apps.yaml"

    @property
    def statuses_path(self) -> Path:
        return self.base_dir / "statuses.yaml"

    @property
    def reports_dir(self) -> Path:
        return self.base_dir / "reports"

    @classmethod
    def from_env(cls, env: Mapping[str, str], base_dir: Path) -> "Settings":
        token = validate_token(env.get("DASHBOARD_TOKEN"))
        host = (env.get("DASHBOARD_HOST") or "127.0.0.1").strip()
        if not is_loopback(host):
            raise ConfigError(
                f"DASHBOARD_HOST={host!r}: dashboard może słuchać tylko na adresie lokalnym (127.0.0.1). "
                "Dostęp z telefonu zapewnia `tailscale serve`.")
        port_raw = (env.get("DASHBOARD_PORT") or str(DEFAULT_PORT)).strip()
        if not port_raw.isdigit() or not 1024 <= int(port_raw) <= 65535:
            raise ConfigError(f"DASHBOARD_PORT={port_raw!r}: podaj liczbę 1024–65535")
        allowed = ("localhost", "127.0.0.1", *_parse_hosts(env.get("DASHBOARD_ALLOWED_HOSTS") or ""))
        agents_dir = env.get("DASHBOARD_AGENTS_DIR")
        sessions_dir = env.get("DASHBOARD_SESSIONS_DIR")
        copilot_dir = env.get("DASHBOARD_COPILOT_DIR")
        vscode_dirs = tuple(Path(p.strip()).expanduser()
                            for p in (env.get("DASHBOARD_VSCODE_STORAGE") or "").split(os.pathsep) if p.strip())
        return cls(
            token=token,
            base_dir=Path(base_dir),
            host=host,
            port=int(port_raw),
            allowed_hosts=tuple(dict.fromkeys(allowed)),
            github_accounts=_parse_accounts(env.get("DASHBOARD_GITHUB") or ""),
            github_token=env.get("GITHUB_TOKEN") or None,
            **({"agents_dir": Path(agents_dir).expanduser()} if agents_dir else {}),
            **({"claude_sessions_dir": Path(sessions_dir).expanduser()} if sessions_dir else {}),
            **({"copilot_dir": Path(copilot_dir).expanduser()} if copilot_dir else {}),
            **({"vscode_storage_dirs": vscode_dirs} if vscode_dirs else {}),
        )
