from appcheck.techdetect import BACKEND, FRONTEND, SERVER, detect


def names(profile):
    return {t.name: t for t in profile.technologies}


def test_nothing_detected_gives_only_html():
    p = detect({}, [], {}, [])
    assert p.technologies == [] and p.frontend_languages == ["HTML"] and p.backend_languages == []


def test_basic_frontend_languages():
    p = detect({}, [], {"scripts": 2, "styles": 1}, [])
    assert p.frontend_languages == ["HTML", "CSS", "JavaScript"]


def test_php_from_powered_by_with_version():
    p = detect({"X-Powered-By": "PHP/8.2.1"}, [], {}, [])
    php = names(p)["PHP"]
    assert php.version == "8.2.1" and php.side == BACKEND and "X-Powered-By" in php.evidence
    assert p.backend_languages == ["PHP"]


def test_server_header_web_server_has_no_language():
    p = detect({"server": "nginx/1.25.3"}, [], {}, [])
    assert names(p)["nginx"].version == "1.25.3" and names(p)["nginx"].side == SERVER
    assert p.backend_languages == []


def test_tomcat_is_not_apache_httpd():
    p = detect({"server": "Apache-Coyote/1.1"}, [], {}, [])
    assert set(names(p)) == {"Apache Tomcat"} and p.backend_languages == ["Java"]


def test_kestrel_and_aspnet_headers():
    p = detect({"server": "Kestrel", "x-aspnet-version": "4.0.30319"}, [], {}, [])
    assert p.backend_languages == ["C#"] and names(p)["ASP.NET"].version == "4.0.30319"


def test_cookies():
    p = detect({}, ["PHPSESSID", "_ga", "JSESSIONID", "_myapp_session", "csrftoken", "connect.sid"], {}, [])
    assert p.backend_languages == ["PHP", "Java", "Ruby", "Python", "JavaScript"]
    assert names(p)["PHP"].evidence == "ciasteczko PHPSESSID"


def test_analytics_cookie_is_not_rails():
    assert detect({}, ["_ga", "_gid", "_fbp"], {}, []).technologies == []


def test_generator_meta_wordpress():
    p = detect({}, [], {"generator": "WordPress 6.4.2"}, [])
    assert names(p)["WordPress"].version == "6.4.2" and p.backend_languages == ["PHP"]


def test_frontend_frameworks_from_signals():
    p = detect({}, [], {"angular": "17.3.0", "jquery": "3.7.1", "scripts": 3}, [])
    assert names(p)["Angular"].version == "17.3.0" and names(p)["jQuery"].version == "3.7.1"
    assert p.frontend_languages == ["HTML", "JavaScript", "TypeScript"]


def test_next_implies_react():
    p = detect({}, [], {"next": True, "scripts": 1}, [])
    assert {"Next.js", "React"} <= set(names(p))


def test_empty_version_string_is_none():
    assert names(detect({}, [], {"jquery": ""}, []))["jQuery"].version is None


def test_server_side_markers():
    p = detect({}, [], {"viewstate": True, "django_csrf": True, "rails_csrf": True}, [])
    assert p.backend_languages == ["C#", "Python", "Ruby"]


def test_resources_wordpress_and_wasm():
    p = detect({}, [], {}, ["https://a/wp-content/themes/x.css?v=1", "https://a/app.wasm"])
    assert "WordPress" in names(p) and p.frontend_languages[-1] == "WebAssembly"


def test_blazor_adds_csharp_frontend():
    p = detect({}, [], {"blazor": True}, [])
    assert p.frontend_languages == ["HTML", "JavaScript", "C#"] and names(p)["Blazor"].side == FRONTEND


def test_duplicates_merged_and_version_kept():
    p = detect({"x-powered-by": "PHP"}, ["PHPSESSID"], {}, [])
    assert [t.name for t in p.technologies] == ["PHP"]
    assert p.technologies[0].evidence == "nagłówek X-Powered-By: PHP; ciasteczko PHPSESSID"
    p = detect({"x-powered-by": "PHP", "x-generator": "Drupal 10"}, ["PHPSESSID"], {}, [])
    assert p.backend_languages == ["PHP"]
