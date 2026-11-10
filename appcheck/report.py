"""Raport z wyników: tabela w terminalu i samodzielny plik HTML."""
from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path

from appcheck.github import RepoInfo, ci_label, issues_label, repo_languages_text
from appcheck.result import AppResult, Severity

_ICONS = {Severity.OK: "✅", Severity.WARNING: "⚠️", Severity.ERROR: "❌"}
_ANSI = {Severity.OK: "\x1b[32m", Severity.WARNING: "\x1b[33m", Severity.ERROR: "\x1b[31m"}
_RESET = "\x1b[0m"
_HEADERS = ("Aplikacja", "Status", "Czas", "Problemy", "Backend")


def _status_text(result: AppResult) -> str:
    return f"{_ICONS[result.status]} {result.status.label}"


def _time_text(result: AppResult) -> str:
    if result.load_time_ms is None:
        return "—"
    return f"{result.load_time_ms / 1000:.2f} s"


def _backend_text(result: AppResult) -> str:
    if result.tech is None:
        return "—"
    return ", ".join(result.tech.backend_languages) or "nie rozpoznano"


def _languages_text(result: AppResult) -> str:
    if result.repo is not None and (result.repo.languages or result.repo.main_language):
        return f"GitHub: {repo_languages_text(result.repo)}"
    if result.tech is None:
        return "—"
    return (f"frontend: {', '.join(result.tech.frontend_languages)}; "
            f"backend: {_backend_text(result)}")


def _first_line(message: str) -> str:
    lines = message.strip().splitlines()
    if not lines:
        return ""
    return lines[0] + (" …" if len(lines) > 1 else "")


def _counts(results: list[AppResult]) -> tuple[int, int, int]:
    return tuple(sum(1 for r in results if r.status is s) for s in Severity)  # type: ignore[return-value]


def render_terminal(results: list[AppResult], color: bool = True,
                    repos_without_url: list[RepoInfo] = ()) -> str:
    rows = [
        (r.name, _status_text(r), _time_text(r), str(len(r.issues)) if r.issues else "—", _backend_text(r))
        for r in results
    ]
    widths = [max(len(x) for x in col) for col in zip(_HEADERS, *rows)]

    def line(cells: tuple[str, ...], status: Severity | None = None) -> str:
        padded = [c.ljust(w) for c, w in zip(cells, widths)]
        if color and status is not None:
            padded[1] = f"{_ANSI[status]}{padded[1]}{_RESET}"
        return "  ".join(padded)

    out = [line(_HEADERS), "  ".join("-" * w for w in widths)]
    out += [line(row, r.status) for row, r in zip(rows, results)]

    for r in results:
        if r.status is Severity.OK:
            continue
        out += ["", f"{r.name}:"]
        out += [f"  - [{i.category}] {_first_line(i.message)}" for i in r.issues]

    if repos_without_url:
        out += ["", f"Repozytoria bez adresu aplikacji ({len(repos_without_url)}):"]
        out += [f"  - {repo.name} — {repo_languages_text(repo)} · CI: {ci_label(repo)}"
                f" · issues: {issues_label(repo)}" for repo in repos_without_url]

    ok, warn, err = _counts(results)
    out += ["", f"Razem: {ok} OK, {warn} ostrzeżeń, {err} błędów"]
    return "\n".join(out)


_CSS = """
:root{--bg:#fff;--fg:#1b1f23;--muted:#6a737d;--line:#d0d7de;--card:#f6f8fa;--ok:#1a7f37;--warn:#9a6700;--err:#cf222e}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--card:#161b22;--ok:#3fb950;--warn:#d29922;--err:#f85149}}
body{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1000px;margin:0 auto;padding:16px}
.muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:16px 0}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
.s-ok{color:var(--ok)}.s-warn{color:var(--warn)}.s-err{color:var(--err)}
section.app{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 16px;margin:16px 0}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0}
img{max-width:100%;border:1px solid var(--line)}
summary{cursor:pointer;margin:8px 0}
a{color:inherit}
.issues-toggle{font:inherit;cursor:pointer;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:0 8px}
tr.issues-row td{background:var(--card)}
ul.issues{margin:4px 0;padding-left:20px}
"""
_SCRIPT = """<script>
document.addEventListener('click', function (e) {
  var b = e.target.closest('.issues-toggle');
  if (!b) return;
  var row = document.getElementById(b.dataset.target);
  row.hidden = !row.hidden;
  b.setAttribute('aria-expanded', String(!row.hidden));
  b.textContent = b.textContent.replace(/[▾▴]/, row.hidden ? '▾' : '▴');
});
</script>"""
_CLASS = {Severity.OK: "s-ok", Severity.WARNING: "s-warn", Severity.ERROR: "s-err"}


def _e(text: object) -> str:
    return html.escape(str(text))


def _link(url: str, text: str) -> str:
    """Link otwierany w nowej karcie."""
    return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(text)}</a>'


def _ci_html(repo: RepoInfo) -> str:
    label = ci_label(repo)
    if repo.ci is not None and repo.ci.html_url:
        return _link(repo.ci.html_url, label) + f' <span class="muted">{_e(repo.ci.workflow)} · {_e(repo.ci.created_at)}</span>'
    return _e(label)


def _issues_list(repo: RepoInfo) -> str:
    items = "".join(
        f"<li>{_link(i.html_url, f'#{i.number} {i.title}')} "
        f'<span class="muted">{_e(i.created_at)}{" · " + _e(i.author) if i.author else ""}</span></li>'
        for i in repo.issues or [])
    return f'<ul class="issues">{items}</ul>'


def _app_section(r: AppResult) -> str:
    parts = [
        f'<section class="app"><h2>{_e(r.name)} '
        f'<span class="{_CLASS[r.status]}">{_e(_status_text(r))}</span></h2>',
        f'<p class="muted">{_e(r.url)} · {_e(_time_text(r))}</p>',
    ]
    if r.repo is not None:
        parts.append(
            f"<p>Repozytorium: {_link(r.repo.html_url, r.repo.full_name)}"
            f"{' (prywatne)' if r.repo.private else ''}"
            f" · <strong>Języki wg GitHuba:</strong> {_e(repo_languages_text(r.repo))}"
            f" · <strong>CI:</strong> {_ci_html(r.repo)}"
            f" · <strong>Issues:</strong> {_e(issues_label(r.repo))}</p>")
        if r.repo.issues:
            parts.append(f"<details><summary>Otwarte issues ({len(r.repo.issues)})</summary>"
                         f"{_issues_list(r.repo)}</details>")
        if r.repo.description:
            parts.append(f'<p class="muted">{_e(r.repo.description)}</p>')
    if r.tech is not None:
        parts.append(
            f"<p><strong>Języki</strong> — frontend: {_e(', '.join(r.tech.frontend_languages))}; "
            f"backend: {_e(_backend_text(r))}</p>")
        if r.tech.technologies:
            rows = "".join(
                f"<tr><td>{_e(t.name)}</td><td>{_e(t.version or '')}</td><td>{_e(t.side)}</td>"
                f"<td>{_e(t.language or '')}</td><td>{_e(t.evidence)}</td></tr>"
                for t in r.tech.technologies)
            parts.append(
                f"<details><summary>Technologie ({len(r.tech.technologies)})</summary><table>"
                "<tr><th>Nazwa</th><th>Wersja</th><th>Warstwa</th><th>Język</th><th>Dowód</th></tr>"
                f"{rows}</table></details>")
    if r.issues:
        parts.append("<ul>" + "".join(
            f'<li class="{_CLASS[i.severity]}"><strong>[{_e(i.category)}]</strong> '
            f'<pre>{_e(i.message)}</pre></li>' for i in r.issues) + "</ul>")
    if r.failed_requests:
        rows = "".join(
            f"<tr><td>{_e(q.method)}</td><td>{_e(q.url)}</td><td>{_e(q.resource_type)}</td>"
            f"<td>{_e(q.status if q.status is not None else '')}</td><td>{_e(q.error or '')}</td></tr>"
            for q in r.failed_requests)
        parts.append(
            f"<details><summary>Nieudane żądania ({len(r.failed_requests)})</summary><table>"
            "<tr><th>Metoda</th><th>URL</th><th>Typ</th><th>Status</th><th>Błąd</th></tr>"
            f"{rows}</table></details>")
    if r.console_messages:
        parts.append(
            f"<details><summary>Konsola ({len(r.console_messages)})</summary>"
            f"<pre>{_e(chr(10).join(r.console_messages))}</pre></details>")
    if r.screenshot is not None:
        try:
            data = base64.b64encode(Path(r.screenshot).read_bytes()).decode("ascii")
        except OSError:
            data = None
        if data:
            parts.append(
                "<details><summary>Zrzut ekranu</summary>"
                f'<img alt="Zrzut ekranu: {_e(r.name)}" src="data:image/png;base64,{data}"></details>')
    parts.append("</section>")
    return "".join(parts)


def _repos_table(repos: list[RepoInfo]) -> str:
    if not repos:
        return ""
    rows = []
    for n, repo in enumerate(repos):
        if repo.issues:
            issues = (f'<button type="button" class="issues-toggle" aria-expanded="false" '
                      f'data-target="issues-{n}">{len(repo.issues)} ▾</button>')
        else:
            issues = _e(issues_label(repo))
        rows.append(
            f"<tr><td>{_link(repo.html_url, repo.name)}</td><td>{_e(repo.description or '')}</td>"
            f"<td>{_e(repo_languages_text(repo))}</td><td>{_ci_html(repo)}</td><td>{issues}</td>"
            f"<td>{_e(repo.pushed_at or '')}</td>"
            f"<td>{'prywatne' if repo.private else 'publiczne'}</td></tr>")
        if repo.issues:
            rows.append(f'<tr id="issues-{n}" class="issues-row" hidden><td colspan="7">'
                        f"<strong>Otwarte issues — {_e(repo.name)}</strong>{_issues_list(repo)}</td></tr>")
    return (f"<h2>Repozytoria bez adresu aplikacji ({len(repos)})</h2>"
            '<p class="muted">Repozytoria GitHub bez pola „Website” i bez GitHub Pages — '
            "nie ma czego sprawdzić w przeglądarce.</p>"
            "<table><tr><th>Repozytorium</th><th>Opis</th><th>Języki wg GitHuba</th><th>CI</th>"
            f"<th>Issues</th><th>Ostatnia zmiana</th><th>Widoczność</th></tr>{''.join(rows)}</table>")


def write_html(results: list[AppResult], path: Path, started_at: datetime,
               repos_without_url: list[RepoInfo] = ()) -> Path:
    ok, warn, err = _counts(results)
    rows = "".join(
        f'<tr><td>{_e(r.name)}</td><td class="{_CLASS[r.status]}">{_e(_status_text(r))}</td>'
        f"<td>{_e(_time_text(r))}</td><td>{len(r.issues) or '—'}</td>"
        f"<td>{_e(_languages_text(r))}</td></tr>" for r in results)
    doc = (
        '<!DOCTYPE html>\n<html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Raport sprawdzenia aplikacji</title><style>{_CSS}</style></head><body>"
        "<h1>Raport sprawdzenia aplikacji</h1>"
        f'<p class="muted">Języki i technologie są wykrywane heurystycznie (nagłówki HTTP, ciasteczka, kod strony) — brak wykrycia nie oznacza braku technologii.</p><p class="muted">Uruchomiono: {_e(started_at.strftime("%Y-%m-%d %H:%M"))}</p>'
        f"<p><strong>Razem: {ok} OK, {warn} ostrzeżeń, {err} błędów</strong></p>"
        "<table><tr><th>Aplikacja</th><th>Status</th><th>Czas</th><th>Problemy</th><th>Języki</th></tr>"
        f"{rows}</table>"
        + "".join(_app_section(r) for r in results)
        + _repos_table(list(repos_without_url))
        + _SCRIPT + "</body></html>\n"
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
