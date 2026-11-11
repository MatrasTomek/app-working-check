#!/usr/bin/env bash
# Uruchamia dashboard (python serve.py) z katalogu repozytorium, z jego środowiska .venv.
# Dashboard słucha tylko na 127.0.0.1 — z telefonu łączysz się przez `tailscale serve` (README → Dashboard).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "Brak środowiska .venv w $REPO_DIR — wykonaj instalację z README." >&2
  exit 2
fi

exec .venv/bin/python serve.py "$@"
