# app-working-check

Skrypt (Python + Playwright), który po kolei odwiedza produkcyjne aplikacje webowe — zwykłe
strony i aplikacje z logowaniem — i sprawdza: dostępność, wyświetlanie, logowanie, działanie
backendu (żądania API) oraz błędy w konsoli przeglądarki. Wynik to tabela w terminalu i raport HTML.

Do codziennego podglądu z telefonu służy **dashboard (PWA)** — sekcja [Dashboard](#dashboard-pwa-na-telefonie).

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
- `--github KONTO` — dołącz repozytoria konta GitHub (patrz „Aplikacje z GitHuba”).

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

## Aplikacje z GitHuba

```
python check.py --github MatrasTomek
```

Skrypt pobiera repozytoria wskazanego konta (użytkownika lub organizacji; opcję można powtarzać)
i dołącza je do aplikacji z `apps.yaml` (z `--github` plik `apps.yaml` nie jest wymagany).
Forki i repozytoria zarchiwizowane są pomijane.

- Repozytorium z adresem aplikacji — pole „Website” (About → ⚙) albo włączone GitHub Pages — jest
  sprawdzane w przeglądarce jak wpis z `apps.yaml`. Raport pokazuje dodatkowo link do repozytorium,
  opis i **języki według GitHuba** z udziałem procentowym (liczone z kodu, więc dokładniejsze niż
  wykrywanie po stronie). Gdy nazwa repozytorium powtarza się z nazwą z `apps.yaml`, w raporcie
  występuje jako `konto/repozytorium`.
- Repozytoria bez adresu trafiają do tabeli „Repozytoria bez adresu aplikacji” (nazwa, opis,
  status, tagi, języki, issues, data ostatniej zmiany, widoczność), nad nią podsumowanie statusów.
- **Status** projektu nadajesz ręcznie tagiem (topic) repozytorium: na stronie repozytorium ⚙ przy
  „About” → „Topics”. Rozpoznawane tagi (polskie bez znaków diakrytycznych):

  | status          | tagi |
  |-----------------|------|
  | 🚧 w toku       | `in-progress`, `wip`, `work-in-progress`, `in-development`, `development`, `w-toku`, `w-trakcie`, `w-realizacji` |
  | 📝 planowane    | `planned`, `todo`, `idea`, `planowane`, `pomysl`, `do-zrobienia` |
  | 🧪 prototyp     | `prototype`, `poc`, `proof-of-concept`, `prototyp`, `demo` |
  | 🟢 produkcja    | `production`, `live`, `produkcja`, `wdrozone` |
  | 🟢 aktywne      | `active`, `maintained`, `aktywne`, `utrzymywane` |
  | ✅ gotowe       | `done`, `completed`, `finished`, `gotowe`, `zakonczone`, `skonczone` |
  | ⏸ wstrzymane    | `paused`, `on-hold`, `wstrzymane` |
  | ⛔ porzucone    | `deprecated`, `abandoned`, `unmaintained`, `porzucone`, `nieaktywne` |

  Własny status: tag `status-<nazwa>`, np. `status-do-testow` → „do testow”. Pozostałe tagi
  (np. `react`) są pokazywane w kolumnie „Tagi”. Repozytorium bez tagu statusu ma „—”.
- **Issues** to liczba otwartych zgłoszeń (bez pull requestów); kliknięcie liczby rozwija pod
  wierszem listę zgłoszeń z linkami. „wyłączone” — repozytorium ma wyłączone issues.
- Wszystkie linki w raporcie otwierają się w nowej karcie.
- `--only "nazwa"` działa także dla repozytoriów.

Bez tokenu widać tylko repozytoria publiczne, a GitHub pozwala na 60 zapytań na godzinę (ok. 50
repozytoriów na uruchomienie). Z tokenem w `.env` widać też prywatne repozytoria (własne i organizacji,
do których należysz), a limit to 5000 zapytań na godzinę. Gdy limit skończy się w trakcie pobierania
szczegółów, skrypt nie przerywa pracy: dla pozostałych repozytoriów pokazuje tylko główny język
(„TypeScript (główny)”) i wypisuje ostrzeżenie.

Token dodajesz do `.env`:

```
GITHUB_TOKEN=github_pat_...
```

Token utworzysz na GitHubie: Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token; „Repository access”: All repositories; uprawnienia
„Repository permissions” (wszystkie **Read-only**): **Metadata** (dodawane automatycznie), **Pages**
i **Issues**. Uprawnienia istniejącego tokenu zmienisz na tej samej stronie (Edit) —
token pozostaje ten sam.
Błąd GitHuba (nieznane konto, zły token, przekroczony limit, brak połączenia) kończy skrypt
kodem `2`.

## Języki i technologie

Przy każdym sprawdzeniu skrypt próbuje też ustalić, w czym napisano aplikację. Terminal pokazuje
języki backendu (kolumna „Backend”), a raport HTML — języki frontendu i backendu w tabeli zbiorczej
oraz, w sekcji każdej aplikacji, listę wykrytych technologii z wersją i dowodem. Źródła:

- nagłówki HTTP dokumentu głównego: `Server`, `X-Powered-By`, `X-AspNet-Version`,
  `X-AspNetMvc-Version`, `X-Generator`, `X-Drupal-Cache`, `X-Runtime`,
- nazwy ciasteczek (bez wartości), np. `PHPSESSID` → PHP, `JSESSIONID` → Java,
  `ASP.NET_SessionId` / `.AspNetCore.*` → C#, `csrftoken` → Python (Django),
  `connect.sid` → JavaScript (Express), `_<aplikacja>_session` → Ruby (Rails),
- kod strony: `<meta name="generator">`, React, Next.js, Vue, Nuxt, Angular (`ng-version`),
  AngularJS, Svelte, jQuery, Blazor, Livewire, pola `__VIEWSTATE`, `csrfmiddlewaretoken`,
  `authenticity_token`,
- adresy zasobów: `/wp-content/`, `/_next/`, `/_nuxt/`, `/_framework/blazor`, pliki `.wasm`.

Frontend zawsze zawiera HTML, a CSS i JavaScript, gdy strona ma style lub skrypty. Wykrywanie jest
heurystyczne i tylko informacyjne — nie zmienia statusu aplikacji. Brak wykrycia nie oznacza braku
technologii: serwery produkcyjne często ukrywają nagłówki, a np. TypeScript po kompilacji wygląda
jak JavaScript (wyjątek: Angular, który jest pisany w TypeScripcie). Dla aplikacji niedostępnych
w raporcie jest „—”.

## Dashboard (PWA na telefonie)

Oprócz jednorazowego `check.py` jest dashboard — aplikacja webowa uruchamiana na Twoim komputerze
i obsługiwana z telefonu jako PWA. Trzy zakładki:

- **Serwery** — sprawdzenie aplikacji z `apps.yaml` (i repozytoriów z `DASHBOARD_GITHUB`, które mają
  adres) tak jak `check.py`: dostępność, logowanie, API, błędy konsoli, zrzuty ekranu błędów,
- **Projekty** — repozytoria z kont GitHub: status z tagów (`statuses.yaml`), issues, języki, ostatnia zmiana,
- **Agenci** — sesje Claude Code na tym komputerze (`~/.claude/projects`): pracuje / czeka na Ciebie /
  bezczynny, projekt, gałąź, ostatnie narzędzie. Pokazywane są tylko metadane — nigdy treść rozmów.

Dashboard **pracuje tylko na żądanie**:

- **Odpytaj** — jednorazowe sprawdzenie serwerów, GitHuba i agentów,
- **Start** — tryb ciągły: serwery co 5 min, projekty co 10 min, agenci co 10 s — **tylko dopóki aplikacja
  jest otwarta i widoczna**. Po zamknięciu aplikacji lub wygaszeniu ekranu telefon przestaje wysyłać sygnał
  obecności, a po 60 s serwer sam wyłącza tryb ciągły,
- **Stop** — ręczne wyłączenie trybu ciągłego.

Bez aktywnego trybu backend nic nie robi; przeglądarka do sprawdzeń startuje tylko na czas przebiegu.

### Konfiguracja

1. Zależności (raz): `pip install -r requirements.txt`.
2. Wygeneruj token dostępu i dopisz go do `.env`:

   ```
   python serve.py --gen-token
   ```

   ```
   DASHBOARD_TOKEN=<wygenerowany token>
   DASHBOARD_GITHUB=MatrasTomek
   DASHBOARD_ALLOWED_HOSTS=<komputer>.<tailnet>.ts.net
   ```

   Zmienne: `DASHBOARD_TOKEN` (wymagany, min. 32 znaki), `DASHBOARD_GITHUB` (konta GitHub, po przecinku),
   `DASHBOARD_ALLOWED_HOSTS` (nazwa hosta z Tailscale — patrz niżej), `DASHBOARD_PORT` (domyślnie `8765`),
   `DASHBOARD_AGENTS_DIR` (domyślnie `~/.claude/projects`). Token GitHuba — `GITHUB_TOKEN`, jak dla `check.py`.
3. Ogranicz dostęp do `.env`: `chmod 600 .env` (dashboard ostrzega przy starcie, gdy plik jest czytelny dla innych).

### Uruchomienie

```
scripts/start-dashboard.sh
```

Na komputerze otwórz <http://localhost:8765> i zaloguj się tokenem.

**Autostart w Windows (WSL):** w `scripts/start-dashboard.bat` ustaw `WSL_DISTRO` (`wsl -l -v`) i `REPO_DIR`,
potem Win+R → `shell:startup` i wklej tam **skrót** do tego pliku. Dashboard wystartuje w zminimalizowanym
oknie po zalogowaniu do Windows. Sprawdź w przeglądarce Windows, że <http://localhost:8765> działa
(WSL przekazuje porty `localhost` do Windows).

### Dostęp z telefonu — Tailscale

Dashboard słucha **wyłącznie na 127.0.0.1** — nie jest widoczny w sieci lokalnej ani w internecie.
Telefon łączy się przez prywatną sieć [Tailscale](https://tailscale.com) (darmowy plan wystarcza):

1. Zainstaluj Tailscale na Windows i na telefonie, zaloguj się na obu tym samym kontem.
2. W panelu Tailscale (Admin console → DNS) włącz **MagicDNS** i **HTTPS Certificates**.
3. Na Windows (PowerShell):

   ```
   tailscale serve --bg 8765
   ```

   Polecenie wypisze adres `https://<komputer>.<tailnet>.ts.net` — wpisz tę nazwę hosta do
   `DASHBOARD_ALLOWED_HOSTS` w `.env` i uruchom dashboard ponownie.
4. Na telefonie otwórz ten adres w Chrome, zaloguj się tokenem, menu ⋮ → **Zainstaluj aplikację**
   (lub „Dodaj do ekranu głównego”).

**Nigdy nie używaj `tailscale funnel`** — wystawiłby dashboard do publicznego internetu.
`tailscale serve` udostępnia go tylko Twoim urządzeniom w tailnecie.

### Bezpieczeństwo

Dashboard ma dostęp do haseł aplikacji, tokenu GitHuba i sesji agentów, więc:

- słucha tylko na `127.0.0.1` (inny adres = odmowa startu), dostęp z zewnątrz wyłącznie przez Tailscale,
- wymaga silnego tokenu (odmowa startu bez niego); po 5 błędnych próbach logowanie jest blokowane na 15 min,
- sesja to losowy identyfikator w ciasteczku `__Host-session` (HttpOnly, Secure, SameSite=Strict), ważny 7 dni,
  trzymany tylko w pamięci serwera — restart dashboardu wylogowuje wszystkie urządzenia,
- przyjmuje tylko znane nazwy hosta (ochrona przed DNS rebinding), a żądania zmieniające stan muszą mieć
  zgodny `Origin` i nagłówek `X-Dashboard` (ochrona przed CSRF),
- restrykcyjne CSP i nagłówki bezpieczeństwa, brak `/docs` i `/openapi.json`,
- API nie przyjmuje adresów ani poleceń — sprawdza tylko aplikacje z konfiguracji,
- hasła i tokeny są maskowane w odpowiedziach; z sesji agentów zwracane są tylko metadane,
- service worker na telefonie cache'uje tylko wygląd aplikacji, nigdy danych.

Szczegóły: `docs/superpowers/specs/2026-11-11-dashboard-design.md`, sekcja „Bezpieczeństwo”.

Wylogowanie: przycisk **Wyloguj**. Utrata telefonu: zmień `DASHBOARD_TOKEN` i uruchom dashboard ponownie
(unieważnia wszystkie sesje), a urządzenie usuń z tailnetu w panelu Tailscale.

## Kody wyjścia

- `0` — brak BŁĘDÓW,
- `1` — co najmniej jeden BŁĄD,
- `2` — błąd konfiguracji lub środowiska (np. zły `apps.yaml`, plik nie w UTF-8, brak zmiennych
  w `.env`, nieznana nazwa w `--only`, brak Chromium lub błąd jej uruchomienia, nie można zapisać
  raportu, błąd pobierania danych z GitHuba).

## Testy

```
python -m pytest
```

Testy używają lokalnego serwera i nie łączą się z aplikacjami produkcyjnymi.
