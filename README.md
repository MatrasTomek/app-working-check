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

Jeśli PowerShell odmawia uruchomienia `activate` („running scripts is disabled on this system”),
zezwól na lokalne skrypty dla swojego konta:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

albo pomiń aktywację i wywołuj Pythona ze środowiska bezpośrednio, np.
`.venv\Scripts\python check.py` (i `.venv\Scripts\python -m pip install -r requirements.txt`).

Linux / macOS:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Konfiguracja

Pliki `apps.yaml` i `.env` muszą być zapisane w kodowaniu **UTF-8** (w Notatniku: „Zapisz jako”
→ Kodowanie: UTF-8). Uwaga: w Windows PowerShell 5.1 przekierowanie `>` (np.
`echo PANEL_USER=jan > .env`) tworzy plik UTF-16 — skrypt zgłosi wtedy błąd konfiguracji.

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
aplikacji ze statusem BŁĄD do `reports/RRRR-MM-DD_GG-MM-SS/<nazwa>-<skrót>.png`, gdzie `<nazwa>` to
znormalizowana nazwa aplikacji („slug”: małe litery bez polskich znaków, inne znaki zamienione na
`-`), a `<skrót>` to 6 znaków wyliczonych z pełnej nazwy — np. „Panel księgowości” →
`panel-ksiegowosci-1a2b3c.png`. Dzięki skrótowi aplikacje „A/B” i „A-B” nie nadpiszą sobie zrzutów. Pełna ścieżka raportu jest wypisywana
na końcu (`Raport: ...`).

Domyślne `apps.yaml`, `.env` i `reports/` są szukane w katalogu skryptu (obok `check.py`),
niezależnie od katalogu, z którego go uruchomisz. Ścieżki podane jawnie w opcjach są liczone
względem bieżącego katalogu.

## Statusy

Status aplikacji to najgorszy ze statusów jej problemów.

- **OK** — brak problemów.
- **OSTRZEŻENIE** — `console.error` lub nieobsłużony wyjątek JS, odpowiedź 4xx z API,
  odpowiedź 5xx / zerwane żądanie do API **innej domeny** (np. analityka, widżety zewnętrzne),
  nieudany zasób inny niż skrypt z tej samej domeny (obrazy, CSS, fonty, skrypty zewnętrzne),
  strona nie zakończyła ładowania w limicie `timeout` (dokument się wczytał, ale wisi jakiś
  zasób — np. obraz lub skrypt zewnętrzny; pozostałe sprawdzenia są wykonywane dalej).
- **BŁĄD** — strona niedostępna (DNS, połączenie, SSL, timeout dokumentu), HTTP ≥ 400 dokumentu
  głównego — także po przekierowaniu przez JavaScript lub po zalogowaniu, pusta strona, nieudane
  logowanie lub brak formularza, odpowiedź 5xx / zerwane żądanie do API aplikacji, nieudany skrypt
  z tej samej domeny, błąd skryptu.

API „aplikacji” to żądania do tej samej domeny co `url` (lub host, na który przekierował adres
startowy), łącznie z jej subdomenami — np. dla `panel.firma.com.pl` także `api.firma.com.pl`
i `firma.com.pl`, a dla `example.com` także `api.example.com`. Domenę wyznacza lista sufiksów
publicznych (Public Suffix List), więc `sklep.com.pl` nie jest „tą samą domeną” co `firma.com.pl`,
a `app2.herokuapp.com` co `app1.herokuapp.com`. Adresy IP i `localhost` muszą zgadzać się dokładnie.

## Kody wyjścia

- `0` — brak BŁĘDÓW,
- `1` — co najmniej jeden BŁĄD,
- `2` — błąd konfiguracji lub środowiska (np. zły `apps.yaml`, plik nie w UTF-8, brak zmiennych
  w `.env`, nieznana nazwa w `--only`, brak Chromium lub błąd jej uruchomienia, nie można zapisać
  raportu).

## Testy

```
python -m pytest
```

Testy używają lokalnego serwera i nie łączą się z aplikacjami produkcyjnymi.
