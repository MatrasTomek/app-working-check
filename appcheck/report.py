"""Raport z wyników: tabela w terminalu i samodzielny plik HTML."""
from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path

from appcheck.github import RepoInfo, issues_label, repo_languages_text
from appcheck.statuses import StatusDef
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
        out += [f"  - {repo.name} — {repo_languages_text(repo)}"
                f" · status: {repo.status.label if repo.status else '—'}"
                f" · issues: {issues_label(repo)}" for repo in repos_without_url]

    ok, warn, err = _counts(results)
    out += ["", f"Razem: {ok} OK, {warn} ostrzeżeń, {err} błędów"]
    return "\n".join(out)


_CSS = """
:root{--bg:#fff;--fg:#1b1f23;--muted:#59636e;--line:#d0d7de;--card:#f6f8fa;--hover:#eef3f9;--accent:#0969da;--ok:#1a7f37;--warn:#9a6700;--err:#cf222e}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;--card:#161b22;--hover:#1c2330;--accent:#4493f8;--ok:#3fb950;--warn:#d29922;--err:#f85149}}
body{font:17px/1.55 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1500px;margin:0 auto;padding:16px 24px}
h1{font-size:30px}h2{font-size:23px}
.muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:12px 0 24px;font-size:16px}
th,td{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left;vertical-align:top}
table.sortable thead th{position:sticky;top:0;z-index:1;background:var(--card);cursor:pointer;user-select:none;white-space:nowrap;border-bottom:2px solid var(--line)}
table.sortable thead th:hover{color:var(--accent)}
table.sortable thead th::after{content:" ⇅";color:var(--muted);font-size:13px}
table.sortable thead th[aria-sort=ascending]::after{content:" ▲";color:var(--accent)}
table.sortable thead th[aria-sort=descending]::after{content:" ▼";color:var(--accent)}
table.sortable tbody:not(.issues-open) tr:first-child:hover td{background:var(--hover)}
td.desc{min-width:220px;max-width:420px}
td.nowrap{white-space:nowrap}
.filters{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:12px 0}
.filters label{display:flex;flex-direction:column;gap:2px;font-size:14px;color:var(--muted)}
.filters input,.filters select,.filters button{font:inherit;font-size:16px;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
.filters input[type=search]{min-width:260px}
.filters button{cursor:pointer}
.filters .count{margin-left:auto;font-size:15px;color:var(--muted)}
.s-ok{color:var(--ok)}.s-warn{color:var(--warn)}.s-err{color:var(--err)}
section.app{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 20px;margin:16px 0}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0}
img{max-width:100%;border:1px solid var(--line)}
summary{cursor:pointer;margin:8px 0}
a{color:var(--accent)}
.issues-toggle{font:inherit;cursor:pointer;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:1px 10px}
tr.issues-row td{background:var(--card)}
ul.issues{margin:4px 0;padding-left:20px}
.badge{display:inline-block;font-size:14px;font-weight:600;padding:2px 12px;border-radius:12px;white-space:nowrap}
.badge-none{border:1px solid var(--line);color:var(--muted);font-weight:400}
.topic{display:inline-block;font-size:13px;padding:1px 9px;margin:2px 0;border:1px solid var(--line);border-radius:10px;white-space:nowrap}
.empty{text-align:center;color:var(--muted);padding:16px}
"""
_SCRIPT = """<script>
(function () {
  var collator = new Intl.Collator('pl', {numeric: true, sensitivity: 'base'});
  function cellValue(unit, col) {
    var cell = unit.rows[0].cells[col];
    if (!cell) return '';
    return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
  }
  function compare(a, b) {
    if (a === '' || a === '—') return (b === '' || b === '—') ? 0 : 1;   // puste zawsze na końcu
    if (b === '' || b === '—') return -1;
    var na = Number(a), nb = Number(b);
    if (!isNaN(na) && !isNaN(nb)) return na - nb;
    return collator.compare(a, b);
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var headers = table.tHead.rows[0].cells;
    Array.prototype.forEach.call(headers, function (th, col) {
      th.tabIndex = 0;
      th.title = 'Kliknij, aby posortować';
      function sort() {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
        Array.prototype.forEach.call(headers, function (h) { h.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir);
        var units = Array.prototype.slice.call(table.tBodies).filter(function (b) { return !b.classList.contains('empty-body'); });
        units.sort(function (x, y) {
          var va = cellValue(x, col), vb = cellValue(y, col), empty = compare(va, vb);
          if (va === '' || vb === '' || va === '—' || vb === '—') return empty;
          return dir === 'ascending' ? empty : -empty;
        });
        units.forEach(function (u) { table.appendChild(u); });
      }
      th.addEventListener('click', sort);
      th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } });
    });
  });

  function applyFilters(box) {
    var table = document.getElementById(box.dataset.table);
    var controls = box.querySelectorAll('[data-filter]');
    var units = Array.prototype.filter.call(table.tBodies, function (b) { return !b.classList.contains('empty-body'); });
    var shown = 0;
    units.forEach(function (u) {
      var ok = Array.prototype.every.call(controls, function (c) {
        var v = c.value.trim().toLowerCase();
        if (!v) return true;
        if (c.dataset.filter === 'text') return v.split(/\\s+/).every(function (w) { return u.dataset.text.indexOf(w) !== -1; });
        if (c.dataset.filter === 'lang') return ('|' + u.dataset.lang + '|').indexOf('|' + v + '|') !== -1;
        return u.dataset[c.dataset.filter] === v;
      });
      u.hidden = !ok;
      if (ok) shown++;
    });
    box.querySelector('.count').textContent = 'Widoczne: ' + shown + ' z ' + units.length;
    var empty = table.querySelector('tbody.empty-body');
    if (empty) empty.hidden = shown > 0;
  }
  document.querySelectorAll('.filters').forEach(function (box) {
    box.addEventListener('input', function () { applyFilters(box); });
    box.querySelector('.reset').addEventListener('click', function () {
      box.querySelectorAll('[data-filter]').forEach(function (c) { c.value = ''; });
      applyFilters(box);
    });
    applyFilters(box);
  });

  document.addEventListener('click', function (e) {
    var b = e.target.closest('.issues-toggle');
    if (!b) return;
    var row = document.getElementById(b.dataset.target);
    row.hidden = !row.hidden;
    row.parentNode.classList.toggle('issues-open', !row.hidden);
    b.setAttribute('aria-expanded', String(!row.hidden));
    b.textContent = b.textContent.replace(/[▾▴]/, row.hidden ? '▾' : '▴');
  });
})();
</script>"""
_CLASS = {Severity.OK: "s-ok", Severity.WARNING: "s-warn", Severity.ERROR: "s-err"}


def _e(text: object) -> str:
    return html.escape(str(text))


def _link(url: str, text: str) -> str:
    """Link otwierany w nowej karcie."""
    return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(text)}</a>'


def _topics_html(repo: RepoInfo) -> str:
    return " ".join(f'<span class="topic">{_e(t)}</span>' for t in repo.topics)


def _badge(status: StatusDef | None, suffix: str = "") -> str:
    if status is None:
        return f'<span class="badge badge-none">bez statusu{suffix}</span>' if suffix else "—"
    return (f'<span class="badge" style="background:{status.color};color:{status.text_color}">'
            f"{_e(status.label)}{suffix}</span>")


def _status_summary(repos: list[RepoInfo], statuses: list[StatusDef]) -> str:
    """Liczba repozytoriów w każdym statusie, w kolejności z statuses.yaml; suma = liczba repozytoriów."""
    counts: dict[str | None, int] = {}
    for repo in repos:
        key = repo.status.tag if repo.status else None
        counts[key] = counts.get(key, 0) + 1
    parts = [_badge(s, f" {counts[s.tag]}") for s in statuses if counts.get(s.tag)]
    if counts.get(None):
        parts.append(_badge(None, f" {counts[None]}"))
    return " ".join(parts)


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
            f" · <strong>Status:</strong> {_badge(r.repo.status)}"
            f" · <strong>Issues:</strong> {_e(issues_label(r.repo))}</p>")
        if r.repo.issues:
            parts.append(f"<details><summary>Otwarte issues ({len(r.repo.issues)})</summary>"
                         f"{_issues_list(r.repo)}</details>")
        if r.repo.description:
            parts.append(f'<p class="muted">{_e(r.repo.description)}</p>')
        if r.repo.topics:
            parts.append(f"<p>Tagi: {_topics_html(r.repo)}</p>")
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


def _repo_langs(repo: RepoInfo) -> list[str]:
    names = [name for name, _ in repo.languages]
    return names or ([repo.main_language] if repo.main_language else [])


def _select(label: str, key: str, options: list[tuple[str, str]]) -> str:
    opts = "".join(f'<option value="{_e(v)}">{_e(t)}</option>' for v, t in options)
    return (f'<label>{_e(label)}<select data-filter="{key}"><option value="">wszystkie</option>'
            f"{opts}</select></label>")


def _filters(table_id: str, placeholder: str, selects: str = "") -> str:
    return (f'<div class="filters" data-table="{table_id}">'
            f'<label>Szukaj<input type="search" data-filter="text" placeholder="{_e(placeholder)}"></label>'
            f'{selects}<button type="button" class="reset">Wyczyść filtry</button>'
            '<span class="count"></span></div>')


def _repos_table(repos: list[RepoInfo], statuses: list[StatusDef]) -> str:
    if not repos:
        return ""
    order = {s.tag: n for n, s in enumerate(statuses)}
    rows = []
    for n, repo in enumerate(repos):
        if repo.issues:
            issues = (f'<button type="button" class="issues-toggle" aria-expanded="false" '
                      f'data-target="issues-{n}">{len(repo.issues)} ▾</button>')
        else:
            issues = _e(issues_label(repo))
        issues_sort = len(repo.issues) if repo.issues is not None else -1
        status_sort = order.get(repo.status.tag, len(order)) if repo.status else len(order) + 1
        langs = _repo_langs(repo)
        search = " ".join([repo.name, repo.description or "", " ".join(repo.topics),
                           " ".join(langs), repo.status.label if repo.status else ""]).lower()
        rows.append(
            f'<tbody data-text="{_e(search)}" data-status="{_e(repo.status.tag if repo.status else "none")}" '
            f'data-lang="{_e("|".join(langs).lower())}" '
            f'data-visibility="{"private" if repo.private else "public"}">'
            f"<tr><td>{_link(repo.html_url, repo.name)}</td><td class=\"desc\">{_e(repo.description or '')}</td>"
            f'<td data-sort="{status_sort}">{_badge(repo.status)}</td><td>{_topics_html(repo)}</td>'
            f"<td>{_e(repo_languages_text(repo))}</td><td data-sort=\"{issues_sort}\">{issues}</td>"
            f'<td class="nowrap">{_e(repo.pushed_at or "")}</td>'
            f"<td>{'prywatne' if repo.private else 'publiczne'}</td></tr>")
        if repo.issues:
            rows.append(f'<tr id="issues-{n}" class="issues-row" hidden><td colspan="8">'
                        f"<strong>Otwarte issues — {_e(repo.name)}</strong>{_issues_list(repo)}</td></tr>")
        rows.append("</tbody>")

    present = {r.status.tag for r in repos if r.status}
    status_opts = [(s.tag, s.label) for s in statuses if s.tag in present]
    if any(r.status is None for r in repos):
        status_opts.append(("none", "bez statusu"))
    lang_count: dict[str, int] = {}
    for repo in repos:
        for lang in _repo_langs(repo):
            lang_count[lang] = lang_count.get(lang, 0) + 1
    lang_opts = [(l.lower(), f"{l} ({c})") for l, c in sorted(lang_count.items(), key=lambda x: (-x[1], x[0]))]
    selects = (_select("Status", "status", status_opts) + _select("Język", "lang", lang_opts)
               + _select("Widoczność", "visibility", [("public", "publiczne"), ("private", "prywatne")]))
    return (f"<h2>Repozytoria bez adresu aplikacji ({len(repos)})</h2>"
            '<p class="muted">Repozytoria GitHub bez pola „Website” i bez GitHub Pages — '
            "nie ma czego sprawdzić w przeglądarce. Status pochodzi z tagów (topics) repozytorium "
            "według listy w statuses.yaml. Kliknij nagłówek kolumny, aby posortować.</p>"
            f"<p><strong>Statusy:</strong> {_status_summary(repos, statuses)}</p>"
            + _filters("repos", "nazwa, opis, tag, język…", selects)
            + '<table class="sortable" id="repos"><thead><tr><th>Repozytorium</th><th>Opis</th><th>Status</th>'
            "<th>Tagi</th><th>Języki wg GitHuba</th><th>Issues</th><th>Ostatnia zmiana</th><th>Widoczność</th>"
            f"</tr></thead>{''.join(rows)}"
            '<tbody class="empty-body" hidden><tr><td colspan="8" class="empty">Brak repozytoriów pasujących '
            "do filtrów</td></tr></tbody></table>")


def _apps_table(results: list[AppResult]) -> str:
    if not results:
        return ""
    sev = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.OK: 2}
    rows = "".join(
        f'<tbody data-text="{_e(" ".join([r.name, r.url, _languages_text(r)]).lower())}" '
        f'data-severity="{_CLASS[r.status]}">'
        f'<tr><td>{_e(r.name)}</td><td class="{_CLASS[r.status]}" data-sort="{sev[r.status]}">'
        f'{_e(_status_text(r))}</td>'
        f'<td data-sort="{r.load_time_ms if r.load_time_ms is not None else ""}">{_e(_time_text(r))}</td>'
        f'<td data-sort="{len(r.issues)}">{len(r.issues) or "—"}</td>'
        f"<td>{_e(_languages_text(r))}</td></tr></tbody>" for r in results)
    selects = _select("Wynik", "severity", [("s-err", "błąd"), ("s-warn", "ostrzeżenie"), ("s-ok", "OK")])
    return (_filters("apps", "nazwa, adres, język…", selects)
            + '<table class="sortable" id="apps"><thead><tr><th>Aplikacja</th><th>Status</th><th>Czas</th>'
            f"<th>Problemy</th><th>Języki</th></tr></thead>{rows}"
            '<tbody class="empty-body" hidden><tr><td colspan="5" class="empty">Brak aplikacji pasujących '
            "do filtrów</td></tr></tbody></table>")


def write_html(results: list[AppResult], path: Path, started_at: datetime,
               repos_without_url: list[RepoInfo] = (), statuses: list[StatusDef] = ()) -> Path:
    ok, warn, err = _counts(results)
    doc = (
        '<!DOCTYPE html>\n<html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Raport sprawdzenia aplikacji</title><style>{_CSS}</style></head><body>"
        "<h1>Raport sprawdzenia aplikacji</h1>"
        f'<p class="muted">Języki i technologie są wykrywane heurystycznie (nagłówki HTTP, ciasteczka, kod strony) — brak wykrycia nie oznacza braku technologii.</p><p class="muted">Uruchomiono: {_e(started_at.strftime("%Y-%m-%d %H:%M"))}</p>'
        f"<p><strong>Razem: {ok} OK, {warn} ostrzeżeń, {err} błędów</strong></p>"
        + _apps_table(results)
        + "".join(_app_section(r) for r in results)
        + _repos_table(list(repos_without_url), list(statuses))
        + _SCRIPT + "</body></html>\n"
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
