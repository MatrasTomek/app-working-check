"""Punkt wejścia dashboardu: python serve.py (token: python serve.py --gen-token)."""
from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

from appcheck.config import ConfigError, load_env_file
from appcheck.web.settings import Settings

BASE_DIR = Path(__file__).resolve().parent


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dashboard aplikacji (PWA) — tylko na 127.0.0.1.")
    parser.add_argument("--gen-token", action="store_true", help="wypisz nowy losowy DASHBOARD_TOKEN i zakończ")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env",
                        help="plik .env (domyślnie obok serve.py)")
    return parser.parse_args(argv)


def env_file_warning(path: Path) -> str | None:
    """Ostrzeżenie, gdy .env jest czytelny dla innych użytkowników systemu (POSIX)."""
    if os.name != "posix" or not path.exists():
        return None
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"Uwaga: {path} jest dostępny dla innych użytkowników. Zalecane: chmod 600 {path}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.gen_token:
        print(secrets.token_urlsafe(32))
        return 0
    try:
        load_env_file(args.env_file)
        settings = Settings.from_env(os.environ, BASE_DIR)
    except ConfigError as e:
        print(f"Błąd konfiguracji: {e}", file=sys.stderr)
        return 2
    warning = env_file_warning(args.env_file)
    if warning:
        print(warning, file=sys.stderr)

    import uvicorn

    from appcheck.web.app import create_app

    print(f"Dashboard: http://{settings.host}:{settings.port}  (Ctrl+C — zatrzymanie)")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                server_header=False, proxy_headers=False, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
