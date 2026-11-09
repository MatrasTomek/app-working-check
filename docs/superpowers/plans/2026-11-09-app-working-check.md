# app-working-check — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skrypt `python check.py`, który po kolei sprawdza produkcyjne aplikacje webowe (dostępność, wyświetlanie, logowanie, backend, konsola) i wypisuje raport w terminalu oraz HTML.

**Architecture:** Konfiguracja (`apps.yaml` + `.env`) → `config.load_config` → lista `AppConfig`. Dla każdej aplikacji `browser_check.check_app` otwiera nowy kontekst Chromium (Playwright, API synchroniczne), zbiera zdarzenia, ocenia je czystymi funkcjami z `rules.py`, loguje się przez `login.py` i zwraca `AppResult`. `report.py` renderuje wyniki; `check.py` spina całość i ustala kod wyjścia.

**Tech Stack:** Python ≥ 3.10, `playwright` (sync API, Chromium), `pyyaml`, `python-dotenv`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-09-app-working-check-design.md`

## Global Constraints

- Statusy: OK < OSTRZEŻENIE < BŁĄD; status aplikacji = najgorszy status jej problemów.
- Kody wyjścia: `0` brak BŁĘDÓW, `1` co najmniej jeden BŁĄD, `2` błąd konfiguracji lub środowiska.
- Domyślny `timeout` = 30 s; zmienne logowania: `<PREFIX>_USER`, `<PREFIX>_PASS`.
- Hasła nigdy nie trafiają do terminala ani raportu — zastępowane `***`.
- Skrypt klika wyłącznie przycisk logowania.
- Każda aplikacja w osobnym kontekście przeglądarki; aplikacje sprawdzane sekwencyjnie.
- Testy nie łączą się z internetem ani produkcją — tylko lokalny serwer testowy.
- Komunikaty dla użytkownika po polsku; identyfikatory w kodzie po angielsku.
- `.env` i `reports/` w `.gitignore` (już jest).

## Review Focus

1. **Przekierowania** (http→https, `/` → `/login`): status dokumentu głównego ocenia się na podstawie *końcowej* odpowiedzi; 301/302 po drodze to nie błąd. → test `test_redirect_is_ok` w Task 4.
2. **Strony, które nigdy nie osiągają `networkidle`** (long-polling, websockety): nie mogą dostać BŁĘDU, jeśli dokument się załadował. → test `test_never_idle_page_is_ok` w Task 4.
3. **Polskie znaki i spacje w nazwach aplikacji** w nazwach plików zrzutów (`Panel księgowości` → `panel-ksiegowosci.png`). → test `test_slugify_polish` w Task 1.
4. **Hasło ze znakami specjalnymi** pojawiające się w URL w postaci zakodowanej (`p@ss word` → `p%40ss+word` / `p%40ss%20word`): też musi być zamaskowane. → test `test_mask_secrets_url_encoded` w Task 1.
5. **Treści ze strony zawierające HTML** (`<script>` w komunikacie konsoli) muszą być escapowane w raporcie HTML. → test `test_html_escapes_page_content` w Task 6.

---

## Struktura plików

| plik | odpowiedzialność |
|------|------------------|
| `requirements.txt` | `playwright>=1.45`, `pyyaml>=6`, `python-dotenv>=1`, `pytest>=8` |
| `appcheck/__init__.py` | pusty |
| `appcheck/result.py` | `Severity`, `Issue`, `RequestRecord`, `AppResult`, `mask_secrets`, `slugify` |
| `appcheck/config.py` | `AppConfig`, `ConfigError`, `load_config` |
| `appcheck/rules.py` | czyste funkcje oceny żądań i konsoli |
| `appcheck/browser_check.py` | `check_app` — jedna aplikacja w przeglądarce |
| `appcheck/login.py` | wykrycie formularza i logowanie |
| `appcheck/report.py` | tabela terminalowa + HTML |
| `check.py` | CLI, kody wyjścia |
| `apps.yaml`, `.env.example`, `README.md` | przykład konfiguracji i instrukcja |
| `tests/conftest.py` | fixture `site` (lokalny serwer) i `browser` |
| `tests/site/*.html` | strony testowe |

---

### Task 1: Szkielet projektu i model wyniku

**Files:**
- Create: `requirements.txt`, `appcheck/__init__.py`, `appcheck/result.py`, `tests/__init__.py`
- Test: `tests/test_result.py`

**Interfaces:**
- Produces:
  - `class Severity(IntEnum)`: `OK = 0`, `WARNING = 1`, `ERROR = 2`; właściwość `label -> str` zwraca `"OK"`, `"OSTRZEŻENIE"`, `"BŁĄD"`.
  - `@dataclass Issue(severity: Severity, category: str, message: str)` — `category` jedna z: `"dostępność"`, `"wyświetlanie"`, `"logowanie"`, `"backend"`, `"zasoby"`, `"konsola"`, `"skrypt"`.
  - `@dataclass RequestRecord(method: str, url: str, resource_type: str, status: int | None, error: str | None)`
  - `@dataclass AppResult(name: str, url: str, issues: list[Issue] = [], console_messages: list[str] = [], failed_requests: list[RequestRecord] = [], load_time_ms: int | None = None, screenshot: Path | None = None)` (listy przez `field(default_factory=list)`); właściwość `status -> Severity` = max severity z `issues` albo `Severity.OK`.
  - `mask_secrets(text: str, secrets: Iterable[str | None]) -> str` — puste i `None` pomijane
  - `slugify(name: str) -> str`

- [ ] **Step 1: Utwórz środowisko**

Run: `python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m playwright install chromium` (Windows: `.venv\Scripts\...`; w Linuksie bez bibliotek systemowych dodaj `--with-deps`).
Expected: instalacja bez błędów.

- [ ] **Step 2: Napisz testy**

```python
def test_status_is_worst_issue():
    r = AppResult("a", "https://a")
    assert r.status is Severity.OK
    r.issues += [Issue(Severity.WARNING, "konsola", "x"), Issue(Severity.ERROR, "backend", "y")]
    assert r.status is Severity.ERROR

def test_severity_labels():
    assert [s.label for s in Severity] == ["OK", "OSTRZEŻENIE", "BŁĄD"]

def test_mask_secrets_plain():
    assert mask_secrets("login failed for sekret123", ["sekret123"]) == "login failed for ***"

def test_mask_secrets_url_encoded():
    s = "p@ss word"
    assert "***" in mask_secrets("https://x/?p=p%40ss+word", [s])
    assert "***" in mask_secrets("https://x/?p=p%40ss%20word", [s])
    assert "p%40ss" not in mask_secrets("https://x/?p=p%40ss%20word", [s])

def test_mask_secrets_ignores_empty():
    assert mask_secrets("abc", ["", None]) == "abc"

def test_slugify_polish():
    assert slugify("Panel księgowości") == "panel-ksiegowosci"
    assert slugify("  A/B: test!! ") == "a-b-test"
    assert slugify("Łódź") == "lodz"
```

- [ ] **Step 3: Uruchom — oczekiwany FAIL** (`ImportError`)

Run: `pytest tests/test_result.py -v`

- [ ] **Step 4: Zaimplementuj `appcheck/result.py`**

`mask_secrets`: dla każdego niepustego sekretu zastąp wartość surową oraz `urllib.parse.quote(s, safe="")` i `quote_plus(s)`. `slugify`: zamień `ł/Ł` na `l`, potem `unicodedata.normalize("NFKD")` + odrzucenie znaków niekodowalnych w ASCII, lowercase, ciągi znaków spoza `[a-z0-9]` → `-`, przytnij `-` z brzegów.

- [ ] **Step 5: Uruchom — oczekiwany PASS**

Run: `pytest tests/test_result.py -v`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt appcheck tests
git commit -m "feat: model wyniku, maskowanie haseł, slugify"
```

---

### Task 2: Wczytywanie i walidacja konfiguracji

**Files:**
- Create: `appcheck/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass AppConfig(name: str, url: str, username: str | None = None, password: str | None = None, user_selector: str | None = None, pass_selector: str | None = None, submit_selector: str | None = None, timeout: int = 30)`; właściwość `needs_login -> bool` (`password is not None`).
  - `class ConfigError(Exception)` — komunikat po polsku, gotowy do pokazania użytkownikowi.
  - `load_config(path: Path, env: Mapping[str, str]) -> list[AppConfig]` — nie czyta `.env` sam; `check.py` wywołuje `load_dotenv()` i przekazuje `os.environ`.

- [ ] **Step 1: Napisz testy** (pliki YAML przez `tmp_path`)

```python
def test_loads_public_and_login_apps(tmp_path):
    p = write(tmp_path, """
apps:
  - name: Strona
    url: https://example.com
  - name: Panel
    url: https://panel.example.com/login
    login: PANEL
    timeout: 60
""")
    apps = load_config(p, {"PANEL_USER": "jan", "PANEL_PASS": "x"})
    assert apps[0] == AppConfig("Strona", "https://example.com")
    assert (apps[1].username, apps[1].password, apps[1].timeout) == ("jan", "x", 60)
    assert apps[1].needs_login and not apps[0].needs_login

def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Nie znaleziono pliku"):
        load_config(tmp_path / "brak.yaml", {})

def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError, match="niepoprawny YAML"):
        load_config(write(tmp_path, "apps: [\n"), {})

def test_missing_url_names_position(tmp_path):
    with pytest.raises(ConfigError, match=r"pozycja 1.*url"):
        load_config(write(tmp_path, "apps:\n  - name: A\n"), {})

def test_bad_scheme(tmp_path):
    with pytest.raises(ConfigError, match="A.*http"):
        load_config(write(tmp_path, "apps:\n  - name: A\n    url: example.com\n"), {})

def test_duplicate_names(tmp_path):
    y = "apps:\n  - {name: A, url: 'https://a'}\n  - {name: A, url: 'https://b'}\n"
    with pytest.raises(ConfigError, match="powtarza"):
        load_config(write(tmp_path, y), {})

def test_missing_env_password(tmp_path):
    y = "apps:\n  - {name: Panel, url: 'https://a', login: PANEL}\n"
    with pytest.raises(ConfigError, match="Panel.*PANEL_PASS"):
        load_config(write(tmp_path, y), {"PANEL_USER": "jan"})

def test_empty_apps_list(tmp_path):
    with pytest.raises(ConfigError, match="brak aplikacji"):
        load_config(write(tmp_path, "apps: []\n"), {})
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 3: Zaimplementuj `appcheck/config.py`**

`yaml.safe_load`; pozycja aplikacji liczona od 1; komunikat błędu zawiera nazwę aplikacji, gdy jest znana, inaczej `pozycja N`. Dla `login: X` brak `X_USER` lub `X_PASS` → `ConfigError("Panel: brak zmiennej PANEL_PASS w .env")`.

- [ ] **Step 4: Uruchom — PASS**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add appcheck/config.py tests/test_config.py
git commit -m "feat: wczytywanie i walidacja apps.yaml"
```

---

### Task 3: Reguły oceny żądań i konsoli

**Files:**
- Create: `appcheck/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `Severity`, `Issue`, `RequestRecord` (Task 1).
- Produces:
  - `classify_request(rec: RequestRecord, app_host: str, logged_in: bool) -> Issue | None`
  - `classify_console(msg_type: str, text: str) -> Issue | None` — `msg_type` jak w Playwright (`"error"`, `"warning"`, …).
  - `classify_page_error(text: str) -> Issue`

Reguły (ze specyfikacji, w tej kolejności):
1. `rec.error` zawiera `ERR_ABORTED` → `None`.
2. `resource_type in {"xhr","fetch"}`: `error` lub `status >= 500` → ERROR `backend`, komunikat `f"Backend: {method} {path} → {status or error}"` (path = ścieżka URL bez query); `status in (401, 403)` i `not logged_in` → `None`; inne `status >= 400` → WARNING `backend`.
3. `resource_type == "script"` i host żądania == `app_host` i (`error` lub `status >= 400`) → ERROR `zasoby`.
4. Pozostałe z `error` lub `status >= 400` → WARNING `zasoby`.
5. Inaczej `None`.
Konsola: `"error"` → WARNING `konsola`; reszta → `None`. Page error → WARNING `konsola`, komunikat `"Nieobsłużony wyjątek JS: …"`.
Dla aplikacji bez logowania `logged_in` jest zawsze `False`, więc 401/403 z API są ignorowane.

- [ ] **Step 1: Napisz testy**

```python
def rec(rt, status=None, error=None, url="https://app.pl/api/x?q=1", method="GET"):
    return RequestRecord(method, url, rt, status, error)

def test_api_500_is_error():
    i = classify_request(rec("fetch", 500, method="POST"), "app.pl", True)
    assert i.severity is Severity.ERROR and i.message == "Backend: POST /api/x → 500"

def test_api_connection_failure_is_error():
    assert classify_request(rec("xhr", error="net::ERR_CONNECTION_REFUSED"), "app.pl", False).severity is Severity.ERROR

def test_api_404_is_warning():
    assert classify_request(rec("fetch", 404), "app.pl", True).severity is Severity.WARNING

def test_api_401_before_login_ignored_after_login_warning():
    assert classify_request(rec("fetch", 401), "app.pl", False) is None
    assert classify_request(rec("fetch", 401), "app.pl", True).severity is Severity.WARNING

def test_aborted_ignored():
    assert classify_request(rec("fetch", error="net::ERR_ABORTED"), "app.pl", True) is None

def test_own_script_failure_is_error_foreign_is_warning():
    assert classify_request(rec("script", 404, url="https://app.pl/main.js"), "app.pl", True).severity is Severity.ERROR
    assert classify_request(rec("script", 404, url="https://cdn.x.com/a.js"), "app.pl", True).severity is Severity.WARNING

def test_image_failure_is_warning():
    assert classify_request(rec("image", 404, url="https://app.pl/a.png"), "app.pl", True).severity is Severity.WARNING

def test_ok_request_none():
    assert classify_request(rec("fetch", 200), "app.pl", True) is None

def test_console():
    assert classify_console("error", "boom").severity is Severity.WARNING
    assert classify_console("warning", "hmm") is None
    assert classify_page_error("TypeError: x").message.startswith("Nieobsłużony wyjątek JS")
```

- [ ] **Step 2: Uruchom — FAIL**: `pytest tests/test_rules.py -v`
- [ ] **Step 3: Zaimplementuj `appcheck/rules.py`** (host i ścieżka przez `urllib.parse.urlsplit`)
- [ ] **Step 4: Uruchom — PASS**: `pytest tests/test_rules.py -v`
- [ ] **Step 5: Commit**

```bash
git add appcheck/rules.py tests/test_rules.py
git commit -m "feat: reguły oceny żądań sieciowych i konsoli"
```

---

### Task 4: Sprawdzenie aplikacji w przeglądarce (bez logowania) + serwer testowy

**Files:**
- Create: `appcheck/browser_check.py`, `tests/conftest.py`, `tests/site/ok.html`, `tests/site/console-error.html`, `tests/site/api500.html`, `tests/site/api404.html`, `tests/site/empty.html`, `tests/site/never-idle.html`
- Test: `tests/test_browser_check.py`

**Interfaces:**
- Consumes: `AppConfig` (Task 2), `classify_*` (Task 3), `AppResult`, `Issue`, `slugify`, `mask_secrets` (Task 1).
- Produces:
  - `check_app(browser: playwright.sync_api.Browser, app: AppConfig, screenshot_dir: Path) -> AppResult` — nigdy nie rzuca wyjątku (nieoczekiwany wyjątek → `Issue(ERROR, "skrypt", "Błąd skryptu: …")`).
  - Punkt zaczepienia dla Task 5: w `check_app`, gdy `app.needs_login`, wywołanie `perform_login(page, app)` (Task 5) — w tym tasku jeszcze nie istnieje; zostaw miejsce za krokiem wyświetlania.
  - Fixture'y w `tests/conftest.py`: `site` (session) → `str` bazowy URL `http://127.0.0.1:<port>`; `dead_url` → URL na wolnym porcie, na którym nic nie nasłuchuje; `browser` (session) → Chromium headless.

Serwer testowy: `ThreadingHTTPServer` w wątku, port 0, serwuje `tests/site/` oraz trasy dynamiczne:
`GET /api/ok` → 200 `{"ok":true}`; `GET /api/500` → 500; `GET /api/404` → 404; `GET /status/502` → 502 z treścią „Bad Gateway”; `GET /redirect` → 302 na `/ok.html`; `GET /poll` → odpowiada po 1 s 200 (dla never-idle). Trasy logowania dochodzą w Task 5.

Strony: `ok.html` (tekst „Witaj”, `fetch('/api/ok')`); `console-error.html` (`console.error('boom')` i `throw new Error('kaboom')` w `setTimeout`); `api500.html` (`fetch('/api/500')`); `api404.html` (`fetch('/api/404')`); `empty.html` (`<div id="root"></div>` + skrypt rzucający wyjątek przed renderem); `never-idle.html` (tekst + pętla `fetch('/poll')` bez końca).

Przebieg `check_app` — zgodnie ze specyfikacją, sekcja „Przebieg sprawdzenia”, kroki 1, 2, 4, 5:
- nowy `browser.new_context(ignore_https_errors=False)`; podpięcie `page.on("console")`, `"pageerror"`, `"requestfailed"`, `"response"` (status ≥ 400) zanim nastąpi `goto`; zdarzenia zapisywane do `AppResult.console_messages` / `failed_requests`, a `Issue` wyliczane przez `rules`. Flaga `logged_in` (domyślnie `False`) czytana w momencie zdarzenia.
- `resp = page.goto(app.url, wait_until="load", timeout=app.timeout*1000)`; `load_time_ms` mierzony wokół `goto`. Wyjątek Playwright → ERROR `dostępność`: komunikat zawiera „Serwer nie odpowiada” + oryginalny kod błędu (`net::ERR_...`). `resp.status >= 400` → ERROR `dostępność` `f"HTTP {status} {status_text}"`. `resp` to końcowa odpowiedź po przekierowaniach.
- `page.wait_for_load_state("networkidle", timeout=app.timeout*1000)` w `try` — timeout ignorowany.
- Wyświetlanie: `page.evaluate` zwracające `true`, gdy `document.body.innerText.trim()` niepusty lub istnieje widoczny (`offsetWidth*offsetHeight > 0`) `img, svg, canvas, input, button, video`. `false` → ERROR `wyświetlanie` „Pusta strona — nic się nie wyrenderowało”.
- Odpowiedź dokumentu głównego nie jest dodatkowo oceniana przez `classify_request` (unikamy podwójnego błędu).
- Na końcu: jeśli `status is ERROR` i strona się otworzyła → `page.screenshot(full_page=True, path=screenshot_dir/f"{slugify(name)}.png")` (katalog tworzony w razie potrzeby), ścieżka w `result.screenshot`. Kontekst zawsze zamykany (`finally`).
- Wszystkie komunikaty przepuszczane przez `mask_secrets(…, [app.password])`.

- [ ] **Step 1: Napisz `conftest.py`, strony testowe i testy**

```python
def run(browser, url, tmp_path, **kw):
    return check_app(browser, AppConfig("Test", url, timeout=kw.pop("timeout", 10), **kw), tmp_path)

def test_ok_page(browser, site, tmp_path):
    r = run(browser, f"{site}/ok.html", tmp_path)
    assert r.status is Severity.OK and r.load_time_ms is not None and r.screenshot is None

def test_redirect_is_ok(browser, site, tmp_path):
    assert run(browser, f"{site}/redirect", tmp_path).status is Severity.OK

def test_console_errors_are_warnings(browser, site, tmp_path):
    r = run(browser, f"{site}/console-error.html", tmp_path)
    assert r.status is Severity.WARNING
    msgs = " ".join(i.message for i in r.issues)
    assert "boom" in msgs and "kaboom" in msgs

def test_api_500_is_error_with_screenshot(browser, site, tmp_path):
    r = run(browser, f"{site}/api500.html", tmp_path)
    assert r.status is Severity.ERROR
    assert any(i.message == "Backend: GET /api/500 → 500" for i in r.issues)
    assert r.screenshot == tmp_path / "test.png" and r.screenshot.exists()

def test_api_404_is_warning(browser, site, tmp_path):
    assert run(browser, f"{site}/api404.html", tmp_path).status is Severity.WARNING

def test_empty_spa_is_error(browser, site, tmp_path):
    r = run(browser, f"{site}/empty.html", tmp_path)
    assert any(i.category == "wyświetlanie" for i in r.issues) and r.status is Severity.ERROR

def test_http_502_is_error(browser, site, tmp_path):
    r = run(browser, f"{site}/status/502", tmp_path)
    assert any(i.category == "dostępność" and "502" in i.message for i in r.issues)

def test_dead_server_is_error(browser, dead_url, tmp_path):
    r = run(browser, dead_url, tmp_path)
    assert r.status is Severity.ERROR
    assert any("Serwer nie odpowiada" in i.message for i in r.issues)

def test_never_idle_page_is_ok(browser, site, tmp_path):
    assert run(browser, f"{site}/never-idle.html", tmp_path, timeout=3).status is Severity.OK
```

- [ ] **Step 2: Uruchom — FAIL**: `pytest tests/test_browser_check.py -v`
- [ ] **Step 3: Zaimplementuj `appcheck/browser_check.py`** według opisu wyżej.
- [ ] **Step 4: Uruchom — PASS**: `pytest -v` (cały zestaw)
- [ ] **Step 5: Commit**

```bash
git add appcheck/browser_check.py tests
git commit -m "feat: sprawdzanie dostępności, wyświetlania, backendu i konsoli"
```

---

### Task 5: Logowanie

**Files:**
- Create: `appcheck/login.py`, `tests/site/login.html`, `tests/site/dashboard.html`, `tests/site/no-form.html`, `tests/site/login-js.html`
- Modify: `appcheck/browser_check.py` (wywołanie logowania), `tests/conftest.py` (trasy logowania)
- Test: `tests/test_login.py`

**Interfaces:**
- Consumes: `AppConfig`, `Issue`, `Severity`.
- Produces:
  - `perform_login(page: Page, app: AppConfig) -> Issue | None` — `None` = zalogowano; inaczej `Issue(ERROR, "logowanie", …)`.
  - Zmiana w `check_app`: po kroku wyświetlania, gdy `app.needs_login`: `issue = perform_login(page, app)`; `None` → `logged_in = True`, `wait_for_load_state("networkidle")` (timeout ignorowany) i ponowny test wyświetlania; inaczej dodaj issue.

Trasy testowe: `POST /login` (form `user`, `pass`): `jan`/`sekret` → 302 na `/dashboard.html`; inne → 200, strona logowania z `<div role="alert">Nieprawidłowy login lub hasło</div>`.
Strony: `login.html` (`<form method=post action=/login>` z `<input name=user type=email>`, `<input name=pass type=password>`, `<button type=submit>`); `dashboard.html` (tekst „Dashboard”); `no-form.html` (tylko tekst); `login-js.html` (pola `#e`, `#p` bez `<form>`, `<a id=go>` klik wysyła `fetch` POST i przechodzi do `/dashboard.html` — do testu selektorów z konfiguracji).

Wykrywanie (gdy brak selektorów w konfiguracji) — ze specyfikacji, krok 3: hasło = pierwszy widoczny `input[type=password]`; login = ostatni widoczny `input` typu `text`/`email`/`tel`/bez typu poprzedzający pole hasła w kolejności dokumentu (wyznacz w `page.evaluate` przez `compareDocumentPosition` i oznacz atrybutem `data-appcheck-user`); przycisk = widoczny `button[type=submit], input[type=submit], button:not([type])` w `form` pola hasła; brak → `press("Enter")` w polu hasła.
Sukces: `page.wait_for_function` (timeout `app.timeout`) aż URL ≠ URL sprzed wysłania lub brak widocznego `input[type=password]`.
Komunikaty: „Nie znaleziono formularza logowania”; „Logowanie nieudane” + `: <tekst>` z pierwszego widocznego `[role=alert], [class*=error], [class*=invalid]`, jeśli istnieje.

- [ ] **Step 1: Napisz testy**

```python
def app(url, pw="sekret", **kw):
    return AppConfig("Panel", url, username="jan", password=pw, timeout=10, **kw)

def test_login_success(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html"), tmp_path)
    assert r.status is Severity.OK

def test_login_wrong_password(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/login.html", pw="zle"), tmp_path)
    i = next(i for i in r.issues if i.category == "logowanie")
    assert i.message == "Logowanie nieudane: Nieprawidłowy login lub hasło"
    assert "zle" not in " ".join(x.message for x in r.issues)

def test_no_form(browser, site, tmp_path):
    r = check_app(browser, app(f"{site}/no-form.html"), tmp_path)
    assert any(i.message == "Nie znaleziono formularza logowania" for i in r.issues)

def test_configured_selectors(browser, site, tmp_path):
    a = app(f"{site}/login-js.html", user_selector="#e", pass_selector="#p", submit_selector="#go")
    assert check_app(browser, a, tmp_path).status is Severity.OK
```

- [ ] **Step 2: Uruchom — FAIL**: `pytest tests/test_login.py -v`
- [ ] **Step 3: Zaimplementuj `appcheck/login.py` i podłącz w `check_app`**
- [ ] **Step 4: Uruchom — PASS**: `pytest -v`
- [ ] **Step 5: Commit**

```bash
git add appcheck tests
git commit -m "feat: automatyczne logowanie przez formularz"
```

---

### Task 6: Raport w terminalu i HTML

**Files:**
- Create: `appcheck/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `AppResult`, `Severity`, `RequestRecord`.
- Produces:
  - `render_terminal(results: list[AppResult], color: bool = True) -> str` — tabela: `Aplikacja | Status | Czas | Problemy`; status z ikoną (`✅ OK`, `⚠️ OSTRZEŻENIE`, `❌ BŁĄD`), kolory ANSI tylko gdy `color`; czas jako `1.23 s` lub `—`; pod tabelą sekcje `Nazwa:` z listą `  - [KATEGORIA] komunikat` dla aplikacji ≠ OK; ostatnia linia podsumowania `Razem: X OK, Y ostrzeżeń, Z błędów`.
  - `write_html(results: list[AppResult], path: Path, started_at: datetime) -> Path` — samodzielny plik UTF-8, CSS inline, zrzuty jako `data:image/png;base64,…`, szczegóły w `<details>`; cała treść przez `html.escape`.

- [ ] **Step 1: Napisz testy**

```python
def sample():
    ok = AppResult("Strona", "https://a", load_time_ms=1230)
    bad = AppResult("Panel", "https://b", issues=[Issue(Severity.ERROR, "backend", "Backend: GET /api → 500")],
                    console_messages=["error: <script>alert(1)</script>"],
                    failed_requests=[RequestRecord("GET", "https://b/api", "fetch", 500, None)])
    return [ok, bad]

def test_terminal_table():
    out = render_terminal(sample(), color=False)
    assert "Strona" in out and "✅ OK" in out and "1.23 s" in out
    assert "❌ BŁĄD" in out and "[backend] Backend: GET /api → 500" in out
    assert "Razem: 1 OK, 0 ostrzeżeń, 1 błędów" in out
    assert "\x1b[" not in out

def test_html_written(tmp_path):
    p = write_html(sample(), tmp_path / "r.html", datetime(2026, 11, 9, 14, 30))
    t = p.read_text(encoding="utf-8")
    assert "Panel" in t and "2026-11-09 14:30" in t and "https://b/api" in t

def test_html_escapes_page_content(tmp_path):
    t = write_html(sample(), tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in t and "&lt;script&gt;" in t

def test_html_embeds_screenshot(tmp_path):
    png = tmp_path / "s.png"; png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    r = sample(); r[1].screenshot = png
    assert "data:image/png;base64," in write_html(r, tmp_path / "r.html", datetime.now()).read_text(encoding="utf-8")
```

- [ ] **Step 2: Uruchom — FAIL**: `pytest tests/test_report.py -v`
- [ ] **Step 3: Zaimplementuj `appcheck/report.py`**
- [ ] **Step 4: Uruchom — PASS**: `pytest tests/test_report.py -v`
- [ ] **Step 5: Commit**

```bash
git add appcheck/report.py tests/test_report.py
git commit -m "feat: raport terminalowy i HTML"
```

---

### Task 7: CLI, przykładowa konfiguracja i README

**Files:**
- Create: `check.py`, `apps.yaml`, `.env.example`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `ConfigError`, `check_app`, `render_terminal`, `write_html`.
- Produces: `main(argv: list[str] | None = None) -> int`; `if __name__ == "__main__": sys.exit(main())`.

Zachowanie:
- argumenty: `--config` (domyślnie `apps.yaml`), `--only NAZWA` (wielokrotne; nieznana nazwa → komunikat + `2`), `--headed`, `--reports-dir` (domyślnie `reports`), `--env-file` (domyślnie `.env`; brak pliku nie jest błędem).
- `load_dotenv(env_file, override=False)`, potem `load_config(path, os.environ)`; `ConfigError` → `print` na stderr `Błąd konfiguracji: …`, `return 2`.
- Na Windows ustaw `sys.stdout.reconfigure(encoding="utf-8")`, żeby ikony i polskie znaki się wyświetlały; kolory gdy `sys.stdout.isatty()`.
- `started = datetime.now()`; katalog zrzutów `reports/<RRRR-MM-DD_GG-MM-SS>/`; raport `reports/raport-RRRR-MM-DD_GG-MM-SS.html`.
- `sync_playwright()` → `chromium.launch(headless=not headed)`; wyjątek z „Executable doesn't exist” → stderr `Brak przeglądarki Chromium. Uruchom: python -m playwright install chromium`, `return 2`.
- Przed każdą aplikacją wypisz `Sprawdzam: <nazwa> (<url>)…`; po wszystkich `render_terminal` + `Raport: <ścieżka>`.
- `return 1` gdy którykolwiek wynik ma `Severity.ERROR`, inaczej `0`.

`apps.yaml`: jeden aktywny wpis `Przykład` z `https://example.com` (pusta lista to błąd konfiguracji) oraz zakomentowany wpis z `login: PANEL` i wszystkimi opcjonalnymi polami.
`.env.example`: `PANEL_USER=` i `PANEL_PASS=` z komentarzem o konwencji `<PREFIX>_USER/_PASS`.
`README.md` (po polsku): instalacja (venv, `pip install -r requirements.txt`, `python -m playwright install chromium`), konfiguracja, uruchomienie, znaczenie statusów i kodów wyjścia, uruchamianie testów.

- [ ] **Step 1: Napisz testy** (bez prawdziwej sieci; `site` z conftest)

```python
def cfg(tmp_path, body):
    p = tmp_path / "apps.yaml"; p.write_text(body, encoding="utf-8"); return p

def test_exit_0_when_all_ok(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r"), "--env-file", str(tmp_path / "none")]) == 0
    assert "Raport:" in capsys.readouterr().out
    assert list((tmp_path / "r").glob("raport-*.html"))

def test_exit_1_on_error(tmp_path, site):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--reports-dir", str(tmp_path / "r")]) == 1

def test_exit_2_on_config_error(tmp_path, capsys):
    p = cfg(tmp_path, "apps:\n  - {name: A, url: 'https://a', login: X}\n")
    assert main(["--config", str(p), "--env-file", str(tmp_path / "none")]) == 2
    assert "X_USER" in capsys.readouterr().err

def test_only_filters(tmp_path, site, capsys):
    p = cfg(tmp_path, f"apps:\n  - {{name: Zle, url: '{site}/status/502'}}\n  - {{name: Ok, url: '{site}/ok.html'}}\n")
    assert main(["--config", str(p), "--only", "Ok", "--reports-dir", str(tmp_path / "r")]) == 0

def test_password_never_printed(tmp_path, site, capsys, monkeypatch):
    monkeypatch.setenv("P_USER", "jan"); monkeypatch.setenv("P_PASS", "tajne-haslo-123")
    p = cfg(tmp_path, f"apps:\n  - {{name: P, url: '{site}/login.html', login: P}}\n")
    main(["--config", str(p), "--reports-dir", str(tmp_path / "r")])
    out = capsys.readouterr()
    html = next((tmp_path / "r").glob("raport-*.html")).read_text(encoding="utf-8")
    assert "tajne-haslo-123" not in out.out + out.err + html
```

- [ ] **Step 2: Uruchom — FAIL**: `pytest tests/test_cli.py -v`
- [ ] **Step 3: Zaimplementuj `check.py`, dodaj `apps.yaml`, `.env.example`, `README.md`**
- [ ] **Step 4: Uruchom cały zestaw — PASS**: `pytest -v`
- [ ] **Step 5: Ręczny test dymny**: `python check.py` z domyślnym `apps.yaml` (example.com) → tabela z `✅ OK`, kod wyjścia 0, plik w `reports/`. (Wymaga dostępu do internetu; jeśli sandbox go blokuje — zanotuj i pomiń.)
- [ ] **Step 6: Commit**

```bash
git add check.py apps.yaml .env.example README.md tests/test_cli.py
git commit -m "feat: CLI, przykładowa konfiguracja i README"
```
