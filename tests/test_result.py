from appcheck.result import AppResult, Issue, Severity, mask_secrets, screenshot_filename, slugify


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


def test_result_lists_not_shared():
    a, b = AppResult("a", "u"), AppResult("b", "u")
    a.console_messages.append("x")
    assert b.console_messages == []


def test_mask_secrets_chromium_form_encoding():
    # Chromium (formularz GET): '*' bez zmian, spacja jako '+', '~' jako %7E
    s = "Ab* c~1"
    assert mask_secrets("pass=Ab*+c%7E1&x=1", [s]) == "pass=***&x=1"
    assert mask_secrets("pass=Ab*%20c~1", [s]) == "pass=***"  # URL fetch / encodeURIComponent
    assert mask_secrets("pass=Ab%2a%20c%7e1", [s]) == "pass=***"  # małe litery w kodach %


def test_mask_secrets_lowercase_hex_and_json():
    s = 'p@"ł'
    assert mask_secrets("p=p%40%22%c5%82", [s]) == "p=***"
    assert mask_secrets('{"pass":"p@\\"ł"}', [s]) == '{"pass":"***"}'
    assert mask_secrets('{"pass":"p@\\"\\u0142"}', [s]) == '{"pass":"***"}'


def test_screenshot_filename_unique_for_colliding_slugs():
    a, b = screenshot_filename("A/B"), screenshot_filename("A-B")
    assert a != b
    assert a.startswith("a-b-") and a.endswith(".png")
    assert screenshot_filename("A/B") == a  # deterministyczna


def test_screenshot_filename_for_name_without_ascii():
    name = screenshot_filename("日本")
    assert name.startswith("aplikacja-") and name.endswith(".png")
