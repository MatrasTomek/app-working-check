# app-working-check

Skrypt (Python + Playwright), który po kolei odwiedza produkcyjne aplikacje webowe — zwykłe
strony i aplikacje z logowaniem — i sprawdza: dostępność, wyświetlanie, logowanie, działanie
backendu (żądania API) oraz błędy w konsoli przeglądarki. Wynik to tabela w terminalu i raport HTML.

## Instalacja

Windows (PowerShell / cmd):

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Linux / macOS:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Konfiguracja

### `apps.yaml`

```yaml
apps:
  - name: Strona firmowa
    url: https://example.com

  - name: Panel klienta
    url: https://panel.example.com/login
    login: PANEL
```

| pole              | wymagane | opis |
|-------------------|----------|------|
| `name`            | tak      | nazwa w raporcie, unikalna |
| `url`             | tak      | adres startowy (`http://` lub `https://`) |
| `login`           | nie      | prefiks zmiennych `<PREFIX>_USER` i `<PREFIX>_PASS` z `.env` |
| `user_selector`   | nie      | selektor CSS pola loginu (nadpisuje autowykrywanie) |
| `pass_selector`   | nie      | selektor CSS pola hasła |
| `submit_selector` | nie      | selektor CSS przycisku logowania |
| `timeout`         | nie      | limit w sekundach na ładowanie strony i logowanie, domyślnie 30 |

### `.env` (dane logowania)

Skopiuj `.env.example` do `.env` i uzupełnij. Dla `login: PANEL` skrypt czyta `PANEL_USER`
i `PANEL_PASS`:

```
PANEL_USER=jan@example.com
PANEL_PASS=tajnehaslo
```

`.env` jest w `.gitignore`. Hasła nie są wypisywane ani zapisywane w raportach.

Logowanie jest uznawane za udane dopiero wtedy, gdy pole hasła znika ze strony (lub zmienia
się adres URL). Gdy pole hasła nadal jest widoczne, wynik to BŁĄD „Logowanie nieudane”.

## Uruchomienie

```
python check.py
```

Opcje:

- `--config PLIK` — plik konfiguracji (domyślnie `apps.yaml`),
- `--only "Nazwa"` — sprawdź tylko wskazaną aplikację (można podać wielokrotnie),
- `--headed` — widoczne okno przeglądarki (diagnostyka),
- `--reports-dir KATALOG` — katalog raportów (domyślnie `reports`),
- `--env-file PLIK` — plik z danymi logowania (domyślnie `.env`; brak pliku nie jest błędem).

Raporty trafiają do `reports/`: `reports/raport-RRRR-MM-DD_GG-MM-SS.html`, a zrzuty ekranu
aplikacji ze statusem BŁĄD do `reports/RRRR-MM-DD_GG-MM-SS/<nazwa>.png`. Ścieżka raportu jest
wypisywana na końcu (`Raport: ...`).

## Statusy

Status aplikacji to najgorszy ze statusów jej problemów.

- **OK** — brak problemów.
- **OSTRZEŻENIE** — `console.error` lub nieobsłużony wyjątek JS, odpowiedź 4xx z API,
  nieudany zasób inny niż skrypt z tej samej domeny (obrazy, CSS, fonty, skrypty zewnętrzne).
- **BŁĄD** — strona niedostępna (DNS, połączenie, SSL, timeout), HTTP ≥ 400 dokumentu głównego,
  pusta strona, nieudane logowanie lub brak formularza, odpowiedź 5xx / zerwane żądanie API,
  nieudany skrypt z tej samej domeny, błąd skryptu.

## Kody wyjścia

- `0` — brak BŁĘDÓW,
- `1` — co najmniej jeden BŁĄD,
- `2` — błąd konfiguracji lub środowiska (np. zły `apps.yaml`, brak zmiennych w `.env`,
  nieznana nazwa w `--only`, brak Chromium).

## Testy

```
python -m pytest
```

Testy używają lokalnego serwera i nie łączą się z aplikacjami produkcyjnymi.
