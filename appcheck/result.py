"""Model wyniku sprawdzenia aplikacji oraz pomocnicze funkcje."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, quote_plus


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


def mask_secrets(text: str, secrets: Iterable[str | None]) -> str:
    """Zastępuje sekrety (surowe i zakodowane w URL) ciągiem ``***``."""
    for secret in secrets:
        if not secret:
            continue
        # najpierw dłuższe warianty, by nie zostawić fragmentów
        variants = sorted({secret, quote(secret, safe=""), quote_plus(secret)}, key=len, reverse=True)
        for variant in variants:
            text = text.replace(variant, "***")
    return text


def slugify(name: str) -> str:
    text = name.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
