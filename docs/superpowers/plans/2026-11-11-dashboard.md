# App Dashboard — plan wdrożenia

Specyfikacja: `docs/superpowers/specs/2026-11-11-dashboard-design.md`

## Zasady pracy (obowiązują każdy task)

1. Start z aktualnego `main`: `git checkout main && git pull`.
2. Gałąź: `DA-XX-krotki-opis` (np. `DA-02-runner`).
3. TDD: najpierw test, potem kod. Przed commitem `pytest` musi przechodzić w całości.
4. Commity i tytuł PR z prefiksem `DA-XX: ...`.
5. Push gałęzi, PR do `main` (`gh pr create`) i merge PR (`gh pr merge --squash --delete-branch`).
6. Po merge: `git checkout main && git pull`, usunięcie lokalnej gałęzi, następny task.
   Na GitHubie nie zostaje otwarty PR z tej serii.
7. Każdy task sprawdzany względem sekcji „Bezpieczeństwo” specyfikacji — wymagania dotyczące
   zmienianego kodu mają testy.

---

## DA-01: Specyfikacja i plan

- Pliki: `docs/superpowers/specs/2026-11-11-dashboard-design.md`, ten plan.
- Bez zmian w kodzie. Pierwszy PR — rozgrzewka dla agenta-recenzenta.

## DA-02: Wydzielenie logiki do `appcheck/runner.py`

- Nowy moduł `appcheck/runner.py`:
  - `collect_projects(accounts, token, api_url, statuses, on_warning) -> (apps_from_repos, repo_of, repos_without_url)`
    — logika z pętli `--github` w `check.py` (w tym rozwiązywanie kolizji nazw).
  - `run_checks(apps, screenshot_dir, headed=False, on_progress=None) -> list[AppResult]`
    — uruchomienie Playwrighta, przeglądarki i `check_app` dla każdej aplikacji; błędy startu
    Playwrighta/Chromium jako wyjątek `RunnerError` z czytelnym komunikatem.
- `check.py` korzysta z `runner` — zachowanie CLI, komunikaty i kody wyjścia bez zmian.
- Testy: `tests/test_runner.py` (kolizje nazw, `on_progress`, `RunnerError`); istniejące
  `tests/test_cli.py` przechodzą bez modyfikacji.

## DA-03: Szkielet backendu FastAPI z autoryzacją

- Zależności: `fastapi`, `uvicorn[standard]`, `httpx` (do testów `TestClient`).
- `appcheck/web/__init__.py`, `appcheck/web/app.py` — `create_app(settings)`.
- `appcheck/web/settings.py` — `DASHBOARD_TOKEN`, host (domyślnie `127.0.0.1`), port (`8765`),
  ścieżki `apps.yaml`, `statuses.yaml`, `reports/`, konta GitHub (`DASHBOARD_GITHUB=konto1,konto2`).
- `serve.py` — uruchomienie uvicorn; `--gen-token` wypisuje nowy token; brak / słaby token lub
  host inny niż loopback = błąd startu z instrukcją; ostrzeżenie o uprawnieniach `.env`.
- `appcheck/web/security.py` — sesje w pamięci, blokada po nieudanych logowaniach, middleware:
  dozwolone `Host`, `Origin` + `X-Dashboard` dla `POST`, nagłówki bezpieczeństwa (CSP itd.).
- Autoryzacja: `POST /api/login {token}` → ciasteczko `__Host-session` (losowe id sesji);
  `POST /api/logout`; każdy `/api/*` poza `/api/login` i `/api/health` wymaga ważnej sesji.
- FastAPI bez `/docs`, `/redoc`, `/openapi.json`.
- `GET /api/health` → `{"ok": true}`.
- Testy: `tests/web/test_security.py` — każdy punkt sekcji „Bezpieczeństwo” dotyczący backendu.
- `.env.example` uzupełnione o nowe zmienne.

## DA-04: Moduł Serwery — API

- `appcheck/web/jobs.py` — generyczny `Job` (stan `idle|running`, `last_result`, `finished_at`,
  `error`, blokada: jeden przebieg naraz, uruchomienie w wątku).
- `appcheck/web/serialize.py` — `AppResult` → JSON (status, czas, problemy, technologie, repo,
  nazwa pliku zrzutu).
- Endpointy: `POST /api/servers/check` (uruchamia job, zwraca stan), `GET /api/servers` (stan +
  wynik), `GET /api/screenshots/{run}/{plik}` (z ochroną przed path traversal).
- Testy: job z podstawionym runnerem (bez prawdziwej przeglądarki), serializacja, traversal;
  jeden test integracyjny z lokalną stroną z `tests/site/`.

## DA-05: Moduł Projekty — API

- Endpointy: `POST /api/projects/refresh`, `GET /api/projects` — repozytoria z kont GitHub
  (status z `statuses.yaml`, issues, CI, języki, ostatnia zmiana, adres aplikacji).
- Korzysta z `Job` z DA-04 i `collect_projects` z DA-02.
- Testy: podstawiony klient GitHub (jak w `tests/test_github.py`).

## DA-06: Moduł Agenci — odczyt sesji Claude Code

- `appcheck/agents.py`:
  - skan `~/.claude/projects/*/*.jsonl` (katalog konfigurowalny), tylko pliki zmienione w
    ostatnich 24 h;
  - czytanie końcówki pliku (ostatnie ~64 KB), parsowanie wpisów JSON, ignorowanie uszkodzonych;
  - wynik na sesję: projekt (ścieżka odtworzona z nazwy katalogu / pola `cwd`), id sesji,
    ostatnia aktywność, stan (`aktywny` < 2 min, `czeka na Ciebie` — ostatni wpis to odpowiedź
    asystenta bez kolejnego narzędzia, `bezczynny`), ostatnia akcja (nazwa narzędzia lub
    pierwsze 120 znaków tekstu — bez treści wyników narzędzi).
- Endpoint: `GET /api/agents` (odczyt jest tani — bez joba).
- Testy: przykładowe pliki `.jsonl` w `tests/fixtures/agents/`.

## DA-07: Tryb ciągły (Start / Stop / heartbeat)

- `appcheck/web/live.py` — `LiveMode`: `start(intervals)`, `stop()`, `heartbeat()`, wątek
  pętli uruchamiający joby Serwery/Projekty co interwał tylko gdy tryb włączony i ostatni
  heartbeat < 60 s; po wygaśnięciu tryb przechodzi w `off`.
- Endpointy: `POST /api/live/start`, `POST /api/live/stop`, `POST /api/live/heartbeat`,
  `GET /api/live`.
- Testy: wstrzykiwany zegar (bez `sleep`), wygasanie, brak przebiegów po `stop`.

## DA-08: Frontend — dashboard

- `appcheck/web/static/index.html`, `app.css`, `app.js` — serwowane przez FastAPI.
- Ekran tokenu, trzy zakładki, przyciski Odpytaj / Start / Stop, wskaźnik trybu, czas
  odświeżenia, karty aplikacji (status, problemy, zrzut), tabela projektów z filtrowaniem
  statusem, lista agentów.
- Heartbeat tylko przy widocznej karcie (`visibilitychange`).
- Mobile-first (od 360 px), tryb jasny/ciemny.
- Testy: test Playwright na lokalnym serwerze (logowanie tokenem, przełączanie zakładek,
  Odpytaj z podstawionym runnerem).

## DA-09: PWA

- `manifest.webmanifest`, ikony (192, 512, maskable), `sw.js` cache'ujący tylko powłokę;
  żądania `/api/*` zawsze z sieci.
- Test: manifest i service worker serwowane z poprawnymi typami MIME.

## DA-10: Uruchamianie i dostęp z telefonu

- `scripts/start-dashboard.sh`, `scripts/start-dashboard.bat` (`wsl.exe` → skrypt), opis dodania
  do `shell:startup`.
- README: sekcja „Dashboard” — konfiguracja `.env`, uruchomienie, Tailscale na Windows i telefonie,
  `tailscale serve --bg 8765`, instalacja PWA w Chrome. Weryfikacja przekierowania localhost
  Windows → WSL.
