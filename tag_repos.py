"""Nadaje repozytoriom tagi statusu z tagi-repo.txt (przez GitHub CLI `gh`) i usuwa z pliku obsłużone linie.

Linia pliku:  nazwa-repo: tag1, tag2   # komentarz
Tagi muszą być na liście w statuses.yaml. Inne tagi statusu, których repozytorium nie powinno
mieć, są usuwane — tagi spoza statuses.yaml (np. react) zostają nietknięte.

Użycie:
    python tag_repos.py --dry-run     # tylko pokaż, co zostanie zrobione
    python tag_repos.py               # wykonaj
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from appcheck.config import ConfigError
from appcheck.statuses import load_statuses

BASE_DIR = Path(__file__).resolve().parent


def parse_line(line: str) -> tuple[str, list[str]] | None:
    """(repozytorium, tagi) albo None dla komentarza, pustej linii i linii bez tagów."""
    body = line.split("#", 1)[0]
    if ":" not in body:
        return None
    name, tags = body.split(":", 1)
    tags_list = list(dict.fromkeys(t for t in re.split(r"[,\s]+", tags.strip()) if t))
    return (name.strip(), tags_list) if name.strip() and tags_list else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nadaje repozytoriom tagi statusu z pliku.")
    parser.add_argument("--file", type=Path, default=BASE_DIR / "tagi-repo.txt")
    parser.add_argument("--statuses", type=Path, default=BASE_DIR / "statuses.yaml")
    parser.add_argument("--owner", default="MatrasTomek", help="konto GitHub (domyślnie MatrasTomek)")
    parser.add_argument("--dry-run", action="store_true", help="tylko pokaż polecenia, nic nie zmieniaj")
    args = parser.parse_args(argv)

    try:
        status_tags = [s.tag for s in load_statuses(args.statuses)]
    except ConfigError as e:
        print(f"Błąd konfiguracji: {e}", file=sys.stderr)
        return 2
    lines = args.file.read_text(encoding="utf-8").splitlines(keepends=True)

    todo, problems = [], []
    for idx, line in enumerate(lines):
        parsed = parse_line(line)
        if parsed is None:
            continue
        name, tags = parsed
        unknown = [t for t in tags if t not in status_tags]
        if unknown:
            problems.append(f"linia {idx + 1} ({name}): nieznany tag {', '.join(unknown)}")
        else:
            todo.append((idx, name, tags))
    if problems:
        print("Popraw plik (tagi muszą być w statuses.yaml):", *problems, sep="\n  ", file=sys.stderr)
        return 2
    if not todo:
        print("Brak linii z tagami — nic do zrobienia.")
        return 0

    if not args.dry_run:
        if shutil.which("gh") is None:
            print("Brak programu gh (GitHub CLI).", file=sys.stderr)
            return 2
        if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
            print("gh nie jest zalogowany. Uruchom: gh auth login", file=sys.stderr)
            return 2

    done: set[int] = set()
    failed = 0
    for n, (idx, name, tags) in enumerate(todo, 1):
        remove = [t for t in status_tags if t not in tags]
        cmd = ["gh", "repo", "edit", f"{args.owner}/{name}",
               "--add-topic", ",".join(tags), "--remove-topic", ",".join(remove)]
        label = f"[{n}/{len(todo)}] {name}: {', '.join(tags)}"
        if args.dry_run:
            print(f"{label}\n    {' '.join(cmd)}")
            continue
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            done.add(idx)
            print(f"{label} — OK")
            # zapis po każdym repozytorium: przerwanie (Ctrl+C) nie zgubi postępu
            args.file.write_text("".join(l for i, l in enumerate(lines) if i not in done), encoding="utf-8")
        else:
            failed += 1
            error = (proc.stderr or proc.stdout).strip().splitlines()
            print(f"{label} — BŁĄD: {error[-1] if error else proc.returncode}", file=sys.stderr)

    if args.dry_run:
        print(f"\n{len(todo)} repozytoriów do oznaczenia (tryb --dry-run, nic nie zmieniono).")
        return 0
    print(f"\nGotowe: {len(done)} OK, {failed} błędów. Obsłużone linie usunięto z {args.file.name}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
