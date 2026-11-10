"""Punkt wejścia: sprawdza aplikacje z apps.yaml i zapisuje raporty."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from appcheck.browser_check import check_app
from appcheck.config import AppConfig, ConfigError, load_config, load_env_file
from appcheck.github import DEFAULT_API_URL, GitHubError, RepoInfo, fetch_repos
from appcheck.statuses import load_statuses, resolve_status
from appcheck.report import render_terminal, write_html
from appcheck.result import Severity

BASE_DIR = Path(__file__).resolve().parent  # domyślne pliki obok skryptu, niezależnie od katalogu bieżącego


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sprawdza, czy aplikacje webowe działają.")
    parser.add_argument("--config", type=Path, default=BASE_DIR / "apps.yaml",
                        help="plik konfiguracji (domyślnie apps.yaml obok check.py)")
    parser.add_argument("--only", action="append", metavar="NAZWA", help="sprawdź tylko wskazaną aplikację (można powtarzać)")
    parser.add_argument("--headed", action="store_true", help="pokaż okno przeglądarki")
    parser.add_argument("--reports-dir", type=Path, default=BASE_DIR / "reports",
                        help="katalog raportów (domyślnie reports obok check.py)")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env",
                        help="plik z danymi logowania (domyślnie .env obok check.py)")
    parser.add_argument("--statuses", type=Path, default=BASE_DIR / "statuses.yaml",
                        help="lista statusów projektów (domyślnie statuses.yaml obok check.py)")
    parser.add_argument("--github", action="append", metavar="KONTO",
                        help="dołącz repozytoria konta GitHub (użytkownika lub organizacji); można powtarzać")
    return parser.parse_args(argv)


def _first_line(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


def _setup_console() -> None:
    if sys.platform != "win32":
        return
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    os.system("")  # włącza obsługę kolorów ANSI (ENABLE_VIRTUAL_TERMINAL_PROCESSING) w konsoli Windows


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_console()

    try:
        load_env_file(args.env_file)
        if args.github and not Path(args.config).exists():
            apps = []  # z --github plik konfiguracji nie jest wymagany
        else:
            apps = load_config(args.config, os.environ)
        statuses = load_statuses(args.statuses) if args.github else []
    except ConfigError as e:
        print(f"Błąd konfiguracji: {e}", file=sys.stderr)
        return 2

    repo_of: dict[str, RepoInfo] = {}
    repos_without_url: list[RepoInfo] = []
    for account in args.github or []:
        print(f"Pobieram repozytoria GitHub: {account}…", flush=True)
        try:
            repos = fetch_repos(account, os.environ.get("GITHUB_TOKEN") or None,
                                os.environ.get("GITHUB_API_URL") or DEFAULT_API_URL,
                                on_warning=lambda msg: print(f"Uwaga: {msg}", file=sys.stderr))
        except GitHubError as e:
            print(f"Błąd GitHub: {e}", file=sys.stderr)
            return 2
        for repo in repos:
            repo.status = resolve_status(repo.topics, statuses)
            if repo.app_url is None:
                repos_without_url.append(repo)
                continue
            name = repo.name
            if any(a.name == name for a in apps):  # kolizja z apps.yaml lub innym kontem
                name = repo.full_name
            apps.append(AppConfig(name=name, url=repo.app_url))
            repo_of[name] = repo
    if args.github and not apps and not repos_without_url:
        print("Brak repozytoriów do pokazania (pomijane są forki i repozytoria zarchiwizowane).",
              file=sys.stderr)
        return 2

    if args.only:
        known = {a.name for a in apps} | {r.name for r in repos_without_url}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            print(
                f"Błąd: nieznana aplikacja: {', '.join(unknown)}. Dostępne: {', '.join(sorted(known))}",
                file=sys.stderr,
            )
            return 2
        apps = [a for a in apps if a.name in args.only]
        repos_without_url = [r for r in repos_without_url if r.name in args.only]

    started = datetime.now()
    stamp = started.strftime("%Y-%m-%d_%H-%M-%S")
    reports_dir = args.reports_dir.resolve()
    screenshot_dir = reports_dir / stamp
    report_path = reports_dir / f"raport-{stamp}.html"

    results = []
    try:
        pw = sync_playwright().start()
    except PlaywrightError as e:
        print(f"Nie udało się uruchomić Playwrighta: {_first_line(e)}", file=sys.stderr)
        return 2
    try:
        try:
            browser = pw.chromium.launch(headless=not args.headed)
        except PlaywrightError as e:
            if "Executable doesn't exist" in str(e):
                print("Brak przeglądarki Chromium. Uruchom: python -m playwright install chromium",
                      file=sys.stderr)
            else:
                print(f"Nie udało się uruchomić przeglądarki: {_first_line(e)}", file=sys.stderr)
            return 2
        try:
            for app in apps:
                print(f"Sprawdzam: {app.name} ({app.url})…", flush=True)
                result = check_app(browser, app, screenshot_dir)
                result.repo = repo_of.get(app.name)
                results.append(result)
        finally:
            browser.close()
    finally:
        pw.stop()

    print()
    print(render_terminal(results, color=sys.stdout.isatty(), repos_without_url=repos_without_url))
    try:
        write_html(results, report_path, started, repos_without_url, statuses)
    except OSError as e:
        print(f"\nNie można zapisać raportu {report_path}: {e}", file=sys.stderr)
        return 2
    print(f"\nRaport: {report_path}")
    return 1 if any(r.status is Severity.ERROR for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
