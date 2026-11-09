from appcheck.result import RequestRecord, Severity
from appcheck.rules import classify_console, classify_page_error, classify_request

APP = {"app.pl"}


def rec(rt, status=None, error=None, url="https://app.pl/api/x?q=1", method="GET"):
    return RequestRecord(method, url, rt, status, error)


def test_api_500_is_error():
    i = classify_request(rec("fetch", 500, method="POST"), APP, True)
    assert i.severity is Severity.ERROR and i.message == "Backend: POST /api/x → 500"


def test_api_connection_failure_is_error():
    i = classify_request(rec("xhr", error="net::ERR_CONNECTION_REFUSED"), APP, False)
    assert i.severity is Severity.ERROR
    assert i.message == "Backend: GET /api/x → net::ERR_CONNECTION_REFUSED"


def test_api_404_is_warning():
    assert classify_request(rec("fetch", 404), APP, True).severity is Severity.WARNING


def test_api_401_before_login_ignored_after_login_warning():
    assert classify_request(rec("fetch", 401), APP, False) is None
    assert classify_request(rec("fetch", 401), APP, True).severity is Severity.WARNING


def test_aborted_ignored():
    assert classify_request(rec("fetch", error="net::ERR_ABORTED"), APP, True) is None


def test_own_script_failure_is_error_foreign_is_warning():
    assert classify_request(rec("script", 404, url="https://app.pl/main.js"), APP, True).severity is Severity.ERROR
    assert classify_request(rec("script", 404, url="https://cdn.x.com/a.js"), APP, True).severity is Severity.WARNING


def test_image_failure_is_warning():
    i = classify_request(rec("image", 404, url="https://app.pl/a.png"), APP, True)
    assert i.severity is Severity.WARNING and i.category == "zasoby"


def test_ok_request_none():
    assert classify_request(rec("fetch", 200), APP, True) is None


def test_console():
    assert classify_console("error", "boom").severity is Severity.WARNING
    assert classify_console("warning", "hmm") is None
    assert classify_page_error("TypeError: x").message.startswith("Nieobsłużony wyjątek JS")


def test_third_party_api_failure_is_warning_with_host():
    i = classify_request(rec("fetch", error="net::ERR_FAILED", url="https://api.other.com/collect?a=1"), APP, True)
    assert i.severity is Severity.WARNING and i.category == "backend"
    assert i.message == "Backend: GET api.other.com/collect → net::ERR_FAILED"
    assert classify_request(rec("xhr", 503, url="https://api.other.com/x"), APP, True).severity is Severity.WARNING


def test_sibling_subdomain_api_is_own():
    hosts = {"panel.firma.com.pl"}
    i = classify_request(rec("fetch", 500, url="https://api.firma.com.pl/x"), hosts, True)
    assert i.severity is Severity.ERROR and i.message == "Backend: GET api.firma.com.pl/x → 500"
    assert classify_request(rec("fetch", 500, url="https://firma.com.pl/x"), hosts, True).severity is Severity.WARNING
    assert classify_request(rec("fetch", 500, url="https://evilfirma.com.pl/x"), hosts, True).severity is Severity.WARNING


def test_two_label_app_host_has_no_parent():
    hosts = {"example.com"}
    assert classify_request(rec("fetch", 500, url="https://example.com/x"), hosts, True).severity is Severity.ERROR
    assert classify_request(rec("fetch", 500, url="https://api.example.com/x"), hosts, True).severity is Severity.WARNING
    assert classify_request(rec("fetch", 500, url="https://www.com/x"), hosts, True).severity is Severity.WARNING


def test_any_app_host_counts_including_final_host():
    hosts = {"example.com", "www.example.com"}
    assert classify_request(rec("fetch", 500, url="https://www.example.com/x"), hosts, True).severity is Severity.ERROR
    i = classify_request(rec("script", 404, url="https://www.example.com/main.js"), hosts, True)
    assert i.severity is Severity.ERROR


def test_ip_app_host_matches_exactly_only():
    hosts = {"10.0.0.1"}
    assert classify_request(rec("fetch", 500, url="http://10.0.0.1/x"), hosts, True).severity is Severity.ERROR
    assert classify_request(rec("fetch", 500, url="http://9.0.0.1/x"), hosts, True).severity is Severity.WARNING
