# App Dashboard — specyfikacja

Data: 2026-11-11

## Cel

Rozbudować `app-working-check` z jednorazowego skryptu CLI do aplikacji (PWA) uruchamianej na
domowym komputerze i obsługiwanej z telefonu. Trzy moduły:

1. **Serwery** — sprawdzanie aplikacji postawionych na serwerach (obecny `appcheck`: dostępność,
   wyświetlanie, logowanie, API, błędy konsoli).
2. **Projekty** — status projektów z GitHuba (obecny raport HTML: statusy z tagów, issues, CI,
   języki, ostatnie zmiany).
3. **Agenci** — jak pracują agenci Claude Code na tym komputerze.

## Założenia

- **Brak serwera.** Backend działa na domowym komputerze (WSL). Telefon jest tylko ekranem.
- **Praca wyłącznie na żądanie.** W bezczynności backend nic nie robi (żadnego harmonogramu,
  przeglądarka Playwright uruchamiana tylko na czas sprawdzenia).
- **Tryby pracy:**
  - **Odpytaj** — jednorazowe sprawdzenie wybranego modułu (lub wszystkich).
  - **Start** — tryb ciągły: odświeżanie co zadany interwał (Serwery domyślnie co 5 min,
    Projekty co 10 min, Agenci co 10 s) **tak długo, jak klient jest aktywny**.
  - **Stop** — ręczne zakończenie trybu ciągłego.
- **Tryb ciągły wygasa sam.** Klient (PWA) wysyła heartbeat co ~20 s, gdy karta jest widoczna
  (Page Visibility API). Brak heartbeatu przez 60 s = tryb ciągły wyłączony. Zamknięcie aplikacji
  lub wygaszenie ekranu telefonu zatrzymuje pracę bez dodatkowej akcji.
- **Dostęp z telefonu:** Tailscale (`tailscale serve` → HTTPS w prywatnej sieci tailnet).
  Nic nie jest wystawione do internetu. HTTPS jest wymagany do instalacji PWA.
- **Autoryzacja:** dodatkowo token dostępu (`DASHBOARD_TOKEN` w `.env`) — szczegóły w sekcji
  „Bezpieczeństwo”.
- **CLI zostaje.** `python check.py` działa jak dotychczas.

## Bezpieczeństwo (wymaganie nadrzędne)

Backend ma dostęp do haseł aplikacji (`.env`), tokenu GitHuba i sesji agentów, dlatego każdy
element jest projektowany z założeniem „nikt poza właścicielem nie może tego użyć”.

Model zagrożeń: inne urządzenia w sieci lokalnej / tailnecie, złośliwe strony otwarte w tej samej
przeglądarce (CSRF, DNS rebinding), wyciek danych przez odpowiedzi API lub logi, przejęcie
ciasteczka, zgadywanie tokenu, path traversal, nadużycie backendu do żądań w imieniu użytkownika (SSRF).

Wymagania:

1. **Sieć:** backend słucha wyłącznie na `127.0.0.1`. Adres inny niż loopback = odmowa startu.
   Dostęp z zewnątrz tylko przez `tailscale serve` (nigdy `tailscale funnel`).
2. **Token dostępu:** `DASHBOARD_TOKEN` min. 32 znaki, losowy (`python serve.py --gen-token`);
   słaby lub brakujący token = odmowa startu. Porównanie w czasie stałym (`hmac.compare_digest`).
3. **Sesja:** po zalogowaniu losowy identyfikator sesji (`secrets.token_urlsafe(32)`), trzymany
   w pamięci serwera (restart = wylogowanie), ważny 7 dni. Token nigdy nie trafia do ciasteczka.
   Ciasteczko `__Host-` z `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`. Wylogowanie unieważnia sesję.
4. **Ochrona logowania:** po 5 nieudanych próbach logowanie zablokowane na 15 minut (globalnie —
   aplikacja ma jednego użytkownika). Nieudane próby zapisywane w logu bez treści tokenu.
5. **DNS rebinding:** akceptowane wyłącznie nagłówki `Host` z listy (`localhost`, `127.0.0.1`
   i nazwy z `DASHBOARD_ALLOWED_HOSTS`, np. `komputer.tailnet.ts.net`).
6. **CSRF:** oprócz `SameSite=Strict` każde żądanie zmieniające stan (`POST`) musi mieć nagłówek
   `Origin` zgodny z dozwolonym hostem oraz nagłówek `X-Dashboard: 1`.
7. **Nagłówki odpowiedzi:** restrykcyjne CSP (`default-src 'self'`, bez `unsafe-inline`,
   `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
   `Cache-Control: no-store` dla `/api/*`, `Permissions-Policy` wyłączające zbędne API.
8. **Minimalna powierzchnia API:** wyłączone `/docs`, `/redoc`, `/openapi.json`. API nie przyjmuje
   adresów URL, ścieżek ani poleceń od klienta — sprawdza wyłącznie aplikacje z konfiguracji (brak SSRF).
   Filtry (`only`) walidowane względem listy znanych nazw.
9. **Brak wycieku sekretów:** odpowiedzi API przechodzą przez `mask_secrets` (hasła z `.env`,
   tokeny). Moduł Agenci zwraca tylko metadane (projekt, czas, stan, nazwa narzędzia) — bez treści
   wiadomości i wyników narzędzi. Token GitHuba nie opuszcza backendu.
10. **Pliki:** zrzuty ekranu serwowane tylko po nazwie z bieżącego wyniku (lista dozwolonych), z
    weryfikacją, że ścieżka po `resolve()` leży w katalogu raportów. Ostrzeżenie przy starcie,
    gdy `.env` jest czytelny dla innych użytkowników (uprawnienia inne niż `600`).
11. **Frontend:** dane wstawiane do DOM wyłącznie przez `textContent` / tworzenie elementów (nigdy
    `innerHTML` z danymi), linki zewnętrzne z `rel="noopener noreferrer"`, tylko schematy `http(s)`.
    Service worker nie cache'uje odpowiedzi `/api/*`.
12. **Zależności:** wersje przypięte w `requirements.txt`.

## Architektura

```
Telefon (PWA, Chrome) ──Tailscale HTTPS──► Windows: tailscale serve ──► WSL: FastAPI :8765
                                                                          ├─ /api/servers   (Playwright, wątek roboczy)
                                                                          ├─ /api/projects  (GitHub API, cache)
                                                                          ├─ /api/agents    (~/.claude/projects/*.jsonl)
                                                                          ├─ /api/live      (heartbeat / start / stop)
                                                                          └─ /              (statyczny frontend PWA)
```

### Backend

- FastAPI + uvicorn, punkt wejścia `serve.py`.
- Logika sprawdzania wydzielona z `check.py` do `appcheck/runner.py` — wspólna dla CLI i API.
- Każdy moduł ma stan: `idle | running`, wynik ostatniego przebiegu, czas zakończenia, błąd.
  Jednocześnie trwa najwyżej jeden przebieg danego modułu (kolejne „Odpytaj” zwraca stan bieżący,
  HTTP 409 nie jest potrzebny — klient po prostu widzi `running`).
- Playwright (sync API) uruchamiany w osobnym wątku roboczym, z własną instancją.
- Wyniki trzymane w pamięci (brak bazy danych w tym etapie). Zrzuty ekranu w `reports/`,
  serwowane przez autoryzowany endpoint.
- Agenci: odczyt końcówek plików `~/.claude/projects/<projekt>/<sesja>.jsonl` — sesja, katalog
  projektu, czas ostatniej aktywności, stan (aktywny / bezczynny / czeka na użytkownika — heurystyka
  na podstawie ostatniego wpisu), ostatnia akcja (narzędzie lub skrót wiadomości). Tylko odczyt.

### Frontend

- Statyczne HTML + CSS + vanilla JS (bez kroku budowania), mobile-first, tryb jasny/ciemny.
- Trzy zakładki: Serwery, Projekty, Agenci. Na górze: **Odpytaj**, **Start**, **Stop**, wskaźnik
  trybu i czasu ostatniego odświeżenia.
- PWA: `manifest.webmanifest`, service worker cache'ujący wyłącznie powłokę aplikacji (dane zawsze
  z sieci), ikony.
- Pierwsze wejście: formularz tokenu → cookie HttpOnly.

### Uruchamianie

- `scripts/start-dashboard.sh` (WSL) i `scripts/start-dashboard.bat` (Windows, do `shell:startup`).
- Instrukcja Tailscale w README.

## Poza zakresem (na później)

- Historia wyników / uptime (SQLite), powiadomienia, praca na zdalnym serwerze 24/7.
