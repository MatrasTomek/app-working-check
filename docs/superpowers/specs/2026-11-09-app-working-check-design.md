# app-working-check — specyfikacja

Data: 2026-11-09

## Cel

Skrypt uruchamiany ręcznie (np. po wdrożeniu), który po kolei odwiedza produkcyjne
aplikacje webowe — zwykłe strony oraz aplikacje z logowaniem — i raportuje, czy działają:

1. czy strona jest dostępna na hostingu/serwerze i się wyświetla,
2. jakie błędy pojawiają się w konsoli przeglądarki,
3. czy działa backend (żądania API).

Wynik: tabela w terminalu + raport HTML. Kod wyjścia `0` gdy brak BŁĘDÓW, `1` gdy jest
co najmniej jeden BŁĄD.

### Założenia

- Wszystkie aplikacje z logowaniem używają zwykłego formularza login + hasło + przycisk
  (bez SSO, bez 2FA).
- Weryfikacja „podstawowa”: bez sprawdzania konkretnych elementów, endpointów health ani
  podstron (opcjonalne selektory dotyczą tylko formularza logowania).
- Uruchamiane ręcznie; brak harmonogramu i powiadomień.

## Technologia

- Python 3 + Playwright (Chromium headless), `pyyaml`, `python-dotenv`.
- Testy: `pytest`.

## Struktura

```
app-working-check/
├── check.py              # punkt wejścia
├── apps.yaml             # lista aplikacji
├── .env                  # dane logowania (w .gitignore)
├── .env.example          # wzór bez prawdziwych haseł
├── requirements.txt
├── appcheck/
│   ├── config.py         # wczytanie i walidacja apps.yaml + .env
│   ├── browser_check.py  # sprawdzenie jednej aplikacji
│   ├── login.py          # wykrycie i wypełnienie formularza logowania
│   ├── result.py         # model wyniku i ocena statusu
│   └── report.py         # tabela w terminalu + raport HTML
├── reports/              # wygenerowane raporty i zrzuty (w .gitignore)
└── tests/
```

Moduły komunikują się przez obiekt wyniku z `result.py`. `browser_check` nie zna raportów,
`report` nie zna przeglądarki.

## Konfiguracja

### `apps.yaml`

```yaml
apps:
  - name: Strona firmowa
    url: https://example.com

  - name: Panel klienta
    url: https://panel.example.com/login
    login: PANEL              # -> PANEL_USER i PANEL_PASS z .env
```

Pola:

| pole              | wymagane | opis |
|-------------------|----------|------|
| `name`            | tak      | nazwa w raporcie, unikalna |
| `url`             | tak      | adres startowy (http/https) |
| `login`           | nie      | prefiks zmiennych `<PREFIX>_USER` i `<PREFIX>_PASS` w `.env` |
| `user_selector`   | nie      | selektor CSS pola loginu (nadpisuje autowykrywanie) |
| `pass_selector`   | nie      | selektor CSS pola hasła |
| `submit_selector` | nie      | selektor CSS przycisku logowania |
| `timeout`         | nie      | limit w sekundach na ładowanie strony / logowanie, domyślnie 30 |

### `.env`

```
PANEL_USER=jan@example.com
PANEL_PASS=tajnehaslo
```

### Walidacja (przed startem przeglądarki)

Skrypt kończy się kodem `2` z czytelnym komunikatem, gdy:
- brak pliku `apps.yaml` lub jest niepoprawnym YAML-em,
- aplikacja nie ma `name` lub `url`, `url` nie zaczyna się od `http://`/`https://`,
- nazwy aplikacji się powtarzają,
- dla `login: X` brakuje `X_USER` lub `X_PASS` w środowisku/`.env`.

Komunikat wskazuje aplikację (lub jej pozycję na liście) i brakujące pole/zmienną.

## Uruchomienie

```
python check.py [--config apps.yaml] [--only "Nazwa"] [--headed]
```

- `--only` — sprawdź tylko wskazaną aplikację (można podać wielokrotnie).
- `--headed` — widoczne okno przeglądarki (diagnostyka).
- Brak zainstalowanego Chromium → komunikat z komendą `playwright install chromium`, kod `2`.

## Przebieg sprawdzenia jednej aplikacji

Każda aplikacja dostaje nowy kontekst przeglądarki (osobne ciasteczka/sesja). Aplikacje są
sprawdzane sekwencyjnie.

Od otwarcia strony do końca sprawdzenia zbierane są: komunikaty konsoli, nieobsłużone
wyjątki JS (`pageerror`), nieudane żądania (`requestfailed`) i odpowiedzi z kodem ≥ 400.

1. **Dostępność** — `goto(url)`, następnie oczekiwanie na stan `networkidle` (do `timeout`;
   brak `networkidle` w czasie nie jest błędem, jeśli dokument się załadował).
   - błąd DNS / odmowa połączenia / błąd SSL / timeout ładowania dokumentu → BŁĄD
   - status HTTP dokumentu głównego ≥ 400 → BŁĄD (np. „HTTP 502 Bad Gateway”)
2. **Wyświetlanie** — `<body>` musi zawierać widoczny tekst lub widoczne elementy
   (img, svg, canvas, input, button). W przeciwnym razie → BŁĄD „Pusta strona”.
3. **Logowanie** (gdy ustawione `login`):
   - formularz: pole hasła = widoczny `input[type=password]`; pole loginu = ostatni widoczny
     `input` typu text/email/tel (lub bez typu) przed polem hasła w kolejności dokumentu;
     przycisk = widoczny `button[type=submit]`/`input[type=submit]` w tym samym formularzu,
     w razie braku — Enter w polu hasła. Selektory z konfiguracji mają pierwszeństwo.
   - nie znaleziono pola hasła lub loginu → BŁĄD „Nie znaleziono formularza logowania”
   - po wysłaniu: oczekiwanie (do `timeout`) aż pole hasła zniknie lub zmieni się URL,
     następnie `networkidle`. Sukces → kontynuacja (krok 2 powtarzany dla strony po zalogowaniu).
   - w przeciwnym razie → BŁĄD „Logowanie nieudane” + widoczny komunikat błędu ze strony,
     jeśli da się go znaleźć (element z rolą `alert` lub klasą zawierającą `error`/`invalid`).
4. **Backend i zasoby** (przez całą wizytę):
   - żądanie typu `xhr`/`fetch` z odpowiedzią 5xx lub zerwane (`requestfailed`) → BŁĄD
     „Backend: METODA ścieżka → status/błąd”
   - żądanie `xhr`/`fetch` z odpowiedzią 4xx → OSTRZEŻENIE; wyjątek: 401 i 403 przed
     zalogowaniem są ignorowane
   - nieudany zasób `script` pochodzący z tej samej domeny co `url` → BŁĄD
   - inne nieudane zasoby (obrazy, CSS, fonty, skrypty zewnętrzne) → OSTRZEŻENIE
   - żądania anulowane przez nawigację (`net::ERR_ABORTED`) są ignorowane
5. **Konsola**:
   - `console.error` i `pageerror` → OSTRZEŻENIE (pełna treść w raporcie)
   - `console.warning` → informacja w raporcie, bez wpływu na status

Status aplikacji = najgorszy status jej problemów: OK < OSTRZEŻENIE < BŁĄD.

Przy statusie BŁĄD zapisywany jest zrzut ekranu całej strony do
`reports/<znacznik-czasu>/<nazwa-aplikacji>.png` (jeśli strona w ogóle się otworzyła).

Mierzony jest czas ładowania strony startowej (od `goto` do `load`).

## Raport

### Terminal

Tabela: aplikacja | status (✅ OK / ⚠️ OSTRZEŻENIE / ❌ BŁĄD, kolory ANSI) | czas ładowania |
liczba problemów. Pod tabelą lista problemów dla aplikacji o statusie innym niż OK. Na końcu
ścieżka do raportu HTML.

### HTML

Plik `reports/raport-RRRR-MM-DD_GG-MM-SS.html`, samodzielny (CSS inline, zrzuty ekranu
osadzone jako data URI lub linkowane względnie). Zawiera: datę, podsumowanie liczby
OK/OSTRZEŻEŃ/BŁĘDÓW, sekcję dla każdej aplikacji z rozwijanymi szczegółami (wszystkie
problemy, komunikaty konsoli, nieudane żądania: metoda, URL, status/błąd), zrzut ekranu przy
BŁĘDZIE. Treści pochodzące ze stron są escapowane.

## Obsługa błędów skryptu

- Nieoczekiwany wyjątek podczas sprawdzania jednej aplikacji → ta aplikacja dostaje BŁĄD
  „Błąd skryptu: …”, pozostałe są sprawdzane dalej.
- Kody wyjścia: `0` — brak BŁĘDÓW, `1` — co najmniej jeden BŁĄD, `2` — błąd konfiguracji
  lub środowiska.

## Bezpieczeństwo

- `.env` i `reports/` w `.gitignore`; w repozytorium tylko `.env.example`.
- Hasła nie są wypisywane ani zapisywane; każde wystąpienie wartości hasła w treściach
  trafiających do raportu (komunikaty, URL-e) jest zastępowane `***`.
- Skrypt klika wyłącznie przycisk logowania — nie modyfikuje danych w aplikacjach.

## Testy

- Jednostkowe: walidacja konfiguracji (poprawne i błędne przypadki, brak zmiennych `.env`),
  ocena statusu z listy problemów, maskowanie haseł.
- Integracyjne: lokalny serwer HTTP uruchamiany w fixture `pytest`, ze stronami:
  działająca strona; błąd JS w konsoli; API zwracające 500; API zwracające 404; pusta
  strona SPA; formularz logowania (poprawne i błędne hasło); strona bez formularza mimo
  `login`; strona zwracająca 502; adres, na którym nic nie nasłuchuje.
  Testy nie łączą się z aplikacjami produkcyjnymi.

## Poza zakresem

Powiadomienia (e-mail/Slack/Teams), harmonogram, sprawdzanie podstron i elementów, endpointy
health, SSO i 2FA, równoległe sprawdzanie.
