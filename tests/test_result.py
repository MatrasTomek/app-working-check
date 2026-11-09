from appcheck.result import AppResult, Issue, Severity, mask_secrets, slugify


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
