"""Punkt wejścia: sprawdza aplikacje z apps.yaml i zapisuje raporty."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from appcheck.browser_check import check_app
from appcheck.config import ConfigError, load_config
from appcheck.report import render_terminal, write_html
from appcheck.result import Severity


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sprawdza, czy aplikacje webowe działają.")
    parser.add_argument("--config", default="apps.yaml", help="plik konfiguracji (domyślnie apps.yaml)")
    parser.add_argument("--only", action="append", metavar="NAZWA", help="sprawdź tylko wskazaną aplikację (można powtarzać)")
    parser.add_argument("--headed", action="store_true", help="pokaż okno przeglądarki")
    parser.add_argument("--reports-dir", default="reports", help="katalog raportów (domyślnie reports)")
    parser.add_argument("--env-file", default=".env", help="plik z danymi logowania (domyślnie .env)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    load_dotenv(args.env_file, override=False)
    try:
        apps = load_config(Path(args.config), os.environ)
    except ConfigError as e:
        print(f"Błąd konfiguracji: {e}", file=sys.stderr)
        return 2

    if args.only:
        known = {a.name for a in apps}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            print(
                f"Błąd: nieznana aplikacja: {', '.join(unknown)}. Dostępne: {', '.join(sorted(known))}",
                file=sys.stderr,
            )
            return 2
        apps = [a for a in apps if a.name in args.only]

    started = datetime.now()
    stamp = started.strftime("%Y-%m-%d_%H-%M-%S")
    reports_dir = Path(args.reports_dir)
    screenshot_dir = reports_dir / stamp
    report_path = reports_dir / f"raport-{stamp}.html"

    results = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=not args.headed)
        except Exception as e:  # noqa: BLE001
            if "Executable doesn't exist" in str(e):
                print(
                    "Brak przeglądarki Chromium. Uruchom: python -m playwright install chromium",
                    file=sys.stderr,
                )
                return 2
            raise
        try:
            for app in apps:
                print(f"Sprawdzam: {app.name} ({app.url})…", flush=True)
                results.append(check_app(browser, app, screenshot_dir))
        finally:
            browser.close()

    print()
    print(render_terminal(results, color=sys.stdout.isatty()))
    write_html(results, report_path, started)
    print(f"\nRaport: {report_path}")
    return 1 if any(r.status is Severity.ERROR for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
