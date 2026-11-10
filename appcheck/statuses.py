"""Statusy projektów: lista tagów (topics) GitHub z nazwą i kolorem, wczytywana ze statuses.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from appcheck.config import ConfigError

_TAG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,49}")
_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class StatusDef:
    tag: str
    label: str
    color: str  # #rrggbb

    @property
    def text_color(self) -> str:
        """Czarny lub biały tekst — ten, który lepiej kontrastuje z tłem plakietki."""
        r, g, b = (int(self.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        return "#000000" if luminance > 0.179 else "#ffffff"


def resolve_status(topics: Iterable[str], statuses: list[StatusDef]) -> StatusDef | None:
    """Jeden status na repozytorium: pierwszy z listy (kolejność w pliku), którego tag ma repozytorium."""
    present = set(topics)
    return next((s for s in statuses if s.tag in present), None)


def load_statuses(path: Path) -> list[StatusDef]:
    """Wczytuje statuses.yaml; brak pliku nie jest błędem (pusta lista)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError:
        raise ConfigError(f"{path.name}: plik nie jest zapisany w UTF-8 — zapisz go jako UTF-8") from None
    except OSError as e:
        raise ConfigError(f"Nie można odczytać pliku {path}: {e}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: niepoprawny YAML ({e})") from None

    entries = data.get("statuses") if isinstance(data, dict) else None
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ConfigError(f"{path.name}: 'statuses' musi być listą")

    statuses: list[StatusDef] = []
    seen: set[str] = set()
    for pos, entry in enumerate(entries, start=1):
        where = f"{path.name}, pozycja {pos}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: wpis musi być mapą (tag, label, color)")
        tag, label, color = entry.get("tag"), entry.get("label"), entry.get("color")
        if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
            raise ConfigError(f"{where}: 'tag' musi być tagiem GitHub — małe litery, cyfry i myślniki "
                              f"(np. in-progress), otrzymano: {tag!r}")
        if tag in seen:
            raise ConfigError(f"{where}: tag '{tag}' powtarza się")
        if not isinstance(label, str) or not label.strip():
            raise ConfigError(f"{where} ({tag}): brak pola 'label'")
        if not isinstance(color, str) or not _COLOR_RE.fullmatch(color):
            raise ConfigError(f"{where} ({tag}): 'color' musi mieć postać #rrggbb, np. \"#1a7f37\" "
                              f"(w cudzysłowie), otrzymano: {color!r}")
        seen.add(tag)
        statuses.append(StatusDef(tag, label.strip(), color.lower()))
    return statuses
