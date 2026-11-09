from appcheck.result import RequestRecord, Severity
from appcheck.rules import classify_console, classify_page_error, classify_request


def rec(rt, status=None, error=None, url="https://app.pl/api/x?q=1", method="GET"):
    return RequestRecord(method, url, rt, status, error)


def test_api_500_is_error():
    i = classify_request(rec("fetch", 500, method="POST"), "app.pl", True)
    assert i.severity is Severity.ERROR and i.message == "Backend: POST /api/x → 500"


def test_api_connection_failure_is_error():
    i = classify_request(rec("xhr", error="net::ERR_CONNECTION_REFUSED"), "app.pl", False)
    assert i.severity is Severity.ERROR
    assert i.message == "Backend: GET /api/x → net::ERR_CONNECTION_REFUSED"


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
    i = classify_request(rec("image", 404, url="https://app.pl/a.png"), "app.pl", True)
    assert i.severity is Severity.WARNING and i.category == "zasoby"


def test_ok_request_none():
    assert classify_request(rec("fetch", 200), "app.pl", True) is None


def test_console():
    assert classify_console("error", "boom").severity is Severity.WARNING
    assert classify_console("warning", "hmm") is None
    assert classify_page_error("TypeError: x").message.startswith("Nieobsłużony wyjątek JS")
