"""Model wyniku sprawdzenia aplikacji oraz pomocnicze funkcje."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


class Severity(IntEnum):
    OK = 0
    WARNING = 1
    ERROR = 2

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Severity.OK: "OK",
    Severity.WARNING: "OSTRZEŻENIE",
    Severity.ERROR: "BŁĄD",
}


@dataclass
class Issue:
    severity: Severity
    # "dostępność", "wyświetlanie", "logowanie", "backend", "zasoby", "konsola", "skrypt"
    category: str
    message: str


@dataclass
class RequestRecord:
    method: str
    url: str
    resource_type: str
    status: int | None
    error: str | None


@dataclass
class AppResult:
    name: str
    url: str
    issues: list[Issue] = field(default_factory=list)
    console_messages: list[str] = field(default_factory=list)
    failed_requests: list[RequestRecord] = field(default_factory=list)
    load_time_ms: int | None = None
    screenshot: Path | None = None

    @property
    def status(self) -> Severity:
        return max((i.severity for i in self.issues), default=Severity.OK)


def _secret_variants(secret: str) -> set[str]:
    """Postaci, w jakich sekret może trafić do URL-i, konsoli i komunikatów."""
    encoded: set[str] = set()
    # "": quote/quote_plus; "*": formularz Chromium i URL fetch; "!'()*": encodeURIComponent
    for safe in ("", "*", "!'()*"):
        q = quote(secret, safe=safe)  # quote nigdy nie koduje '~', Chromium w formularzu — tak (%7E)
        for spaced in (q, q.replace("%20", "+")):
            encoded |= {spaced, spaced.replace("~", "%7E")}
    encoded |= {re.sub(r"%[0-9A-F]{2}", lambda m: m.group().lower(), v) for v in encoded}
    return encoded | {
        secret,
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],  # JSON.stringify nie koduje znaków spoza ASCII
    }


def mask_secrets(text: str, secrets: Iterable[str | None]) -> str:
    """Zastępuje sekrety (surowe, zakodowane w URL lub w JSON) ciągiem ``***``."""
    for secret in secrets:
        if not secret:
            continue
        # najpierw dłuższe warianty, by nie zostawić fragmentów
        for variant in sorted(_secret_variants(secret), key=len, reverse=True):
            text = text.replace(variant, "***")
    return text


def slugify(name: str) -> str:
    text = name.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def screenshot_filename(name: str) -> str:
    """Nazwa pliku zrzutu: slug + krótki skrót nazwy, więc „A/B” i „A-B” nie nadpiszą się nawzajem."""
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return f"{slugify(name) or 'aplikacja'}-{digest}.png"
