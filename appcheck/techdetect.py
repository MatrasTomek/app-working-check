"""Heurystyczne wykrywanie języków i technologii aplikacji (nagłówki, ciasteczka, sygnały ze strony).

Wynik jest wyłącznie informacyjny — nie wpływa na status aplikacji. Serwery często ukrywają
nagłówki, a np. TypeScript po kompilacji jest nieodróżnialny od JavaScriptu, więc brak
wykrycia nie oznacza braku technologii.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

FRONTEND, BACKEND, SERVER = "frontend", "backend", "serwer"

# Sonda uruchamiana w stronie: zwraca same proste wartości (bool/str/int/None).
PROBE_JS = """() => {
    const w = window, d = document, q = s => { try { return d.querySelector(s); } catch (e) { return null; } };
    const str = v => (typeof v === 'string' || typeof v === 'number') ? String(v) : null;
    const els = Array.from(d.querySelectorAll('body *')).slice(0, 3000);
    const reactEl = els.some(e => e._reactRootContainer ||
        Object.keys(e).some(k => k.startsWith('__react')));
    const vueEl = els.some(e => e.__vue_app__ || e.__vue__ ||
        e.getAttributeNames().some(n => n.startsWith('data-v-')));
    const gen = q('meta[name="generator" i]');
    const ng = q('[ng-version]');
    return {
        generator: gen ? gen.getAttribute('content') : null,
        react: !!(w.React || q('[data-reactroot]') || reactEl),
        react_version: w.React ? str(w.React.version) : null,
        next: !!(w.__NEXT_DATA__ || q('script[src*="/_next/"]')),
        nuxt: !!(w.__NUXT__ || w.$nuxt || q('script[src*="/_nuxt/"]')),
        vue: !!(w.Vue || q('[data-v-app]') || vueEl),
        vue_version: w.Vue ? str(w.Vue.version) : null,
        angular: ng ? (ng.getAttribute('ng-version') || '') : null,
        angularjs: (w.angular && w.angular.version) ? (str(w.angular.version.full) || '') : null,
        svelte: !!q('[class*="svelte-"]'),
        jquery: (w.jQuery && w.jQuery.fn) ? (str(w.jQuery.fn.jquery) || '') : null,
        blazor: !!(w.Blazor || q('script[src*="blazor."]')),
        livewire: !!w.Livewire,
        viewstate: !!q('input[name="__VIEWSTATE"]'),
        django_csrf: !!q('input[name="csrfmiddlewaretoken"]'),
        rails_csrf: !!q('meta[name="csrf-param"][content="authenticity_token"]'),
        scripts: d.scripts.length,
        styles: d.querySelectorAll('style, link[rel~="stylesheet" i]').length,
    };
}"""


@dataclass(frozen=True)
class Technology:
    name: str
    side: str  # FRONTEND / BACKEND / SERVER
    language: str | None
    evidence: str
    version: str | None = None


@dataclass
class TechProfile:
    technologies: list[Technology] = field(default_factory=list)
    frontend_languages: list[str] = field(default_factory=list)
    backend_languages: list[str] = field(default_factory=list)


# (wzorzec, nazwa, warstwa, język); pierwsza grupa wzorca (jeśli jest) to wersja
_ServerRule = tuple[str, str, str, str | None]

_SERVER_RULES: list[_ServerRule] = [
    (r"nginx(?:/([\d.]+))?", "nginx", SERVER, None),
    (r"openresty(?:/([\d.]+))?", "OpenResty", SERVER, None),
    (r"apache-coyote(?:/([\d.]+))?", "Apache Tomcat", BACKEND, "Java"),
    (r"apache(?!-coyote)(?:/([\d.]+))?", "Apache HTTP Server", SERVER, None),
    (r"microsoft-iis(?:/([\d.]+))?", "Microsoft IIS", SERVER, None),
    (r"kestrel", "ASP.NET Core (Kestrel)", BACKEND, "C#"),
    (r"litespeed", "LiteSpeed", SERVER, None),
    (r"caddy", "Caddy", SERVER, None),
    (r"cloudflare", "Cloudflare", SERVER, None),
    (r"gunicorn(?:/([\d.]+))?", "Gunicorn", BACKEND, "Python"),
    (r"uvicorn", "Uvicorn", BACKEND, "Python"),
    (r"werkzeug(?:/([\d.]+))?", "Werkzeug (Flask)", BACKEND, "Python"),
    (r"daphne", "Daphne", BACKEND, "Python"),
    (r"tornadoserver(?:/([\d.]+))?", "Tornado", BACKEND, "Python"),
    (r"jetty(?:\(([\d.]+))?", "Jetty", BACKEND, "Java"),
    (r"wildfly|jboss", "WildFly", BACKEND, "Java"),
    (r"puma", "Puma", BACKEND, "Ruby"),
    (r"phusion[ _]passenger", "Phusion Passenger", SERVER, None),
]

_POWERED_BY_RULES: list[_ServerRule] = [
    (r"php(?:/([\d.]+))?", "PHP", BACKEND, "PHP"),
    (r"asp\.net", "ASP.NET", BACKEND, "C#"),
    (r"express", "Express", BACKEND, "JavaScript"),
    (r"next\.js(?:\s+([\d.]+))?", "Next.js", BACKEND, "JavaScript"),
    (r"nuxt", "Nuxt", BACKEND, "JavaScript"),
    (r"servlet(?:/([\d.]+))?", "Java Servlet", BACKEND, "Java"),
    (r"jsf", "JavaServer Faces", BACKEND, "Java"),
    (r"undertow", "Undertow", BACKEND, "Java"),
    (r"django", "Django", BACKEND, "Python"),
    (r"flask", "Flask", BACKEND, "Python"),
    (r"phusion passenger", "Phusion Passenger", SERVER, None),
    (r"plesk", "Plesk", SERVER, None),
]

_GENERATOR_RULES: list[_ServerRule] = [
    (r"wordpress\s*([\d.]+)?", "WordPress", BACKEND, "PHP"),
    (r"drupal\s*([\d.]+)?", "Drupal", BACKEND, "PHP"),
    (r"joomla", "Joomla", BACKEND, "PHP"),
    (r"typo3", "TYPO3", BACKEND, "PHP"),
    (r"prestashop", "PrestaShop", BACKEND, "PHP"),
    (r"magento", "Magento", BACKEND, "PHP"),
    (r"woocommerce\s*([\d.]+)?", "WooCommerce", BACKEND, "PHP"),
    (r"hugo\s*([\d.]+)?", "Hugo", BACKEND, "Go"),
    (r"jekyll\s*v?([\d.]+)?", "Jekyll", BACKEND, "Ruby"),
    (r"gatsby\s*([\d.]+)?", "Gatsby", FRONTEND, "JavaScript"),
    (r"docusaurus", "Docusaurus", FRONTEND, "JavaScript"),
    (r"astro\s*v?([\d.]+)?", "Astro", FRONTEND, "JavaScript"),
    (r"wix\.com", "Wix", BACKEND, None),
]

# (wzorzec nazwy ciasteczka, nazwa, język)
_COOKIE_RULES: list[tuple[str, str, str]] = [
    (r"PHPSESSID", "PHP", "PHP"),
    (r"laravel_session", "Laravel", "PHP"),
    (r"ci_session", "CodeIgniter", "PHP"),
    (r"wordpress_.*|wp-settings-.*", "WordPress", "PHP"),
    (r"JSESSIONID", "Java (serwlety)", "Java"),
    (r"ASP\.NET_SessionId", "ASP.NET", "C#"),
    (r"\.AspNetCore\..*", "ASP.NET Core", "C#"),
    (r"csrftoken|django_language", "Django", "Python"),
    (r"connect\.sid", "Express", "JavaScript"),
    (r"rack\.session", "Rack", "Ruby"),
    (r"_[a-z0-9_]+_session", "Ruby on Rails", "Ruby"),
    (r"CFID|CFTOKEN", "ColdFusion", "CFML"),
]

# (fragment adresu zasobu, nazwa, warstwa, język)
_RESOURCE_RULES: list[tuple[str, str, str, str]] = [
    ("/wp-content/", "WordPress", BACKEND, "PHP"),
    ("/wp-includes/", "WordPress", BACKEND, "PHP"),
    ("/_next/", "Next.js", FRONTEND, "JavaScript"),
    ("/_nuxt/", "Nuxt", FRONTEND, "JavaScript"),
    ("/_framework/blazor", "Blazor", FRONTEND, "C#"),
]


def _match_rules(value: str, rules: list[_ServerRule], source: str) -> list[Technology]:
    found = []
    for pattern, name, side, language in rules:
        m = re.search(pattern, value, re.IGNORECASE)
        if m:
            version = m.group(1) if m.groups() and m.group(1) else None
            found.append(Technology(name, side, language, f"{source}: {value}", version))
    return found


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _from_headers(headers: Mapping[str, str]) -> list[Technology]:
    h = {k.lower(): v for k, v in headers.items()}
    found: list[Technology] = []
    if h.get("server"):
        found += _match_rules(h["server"], _SERVER_RULES, "nagłówek Server")
    if h.get("x-powered-by"):
        found += _match_rules(h["x-powered-by"], _POWERED_BY_RULES, "nagłówek X-Powered-By")
    if h.get("x-aspnet-version"):
        found.append(Technology("ASP.NET", BACKEND, "C#",
                                f"nagłówek X-AspNet-Version: {h['x-aspnet-version']}", h["x-aspnet-version"]))
    if h.get("x-aspnetmvc-version"):
        found.append(Technology("ASP.NET MVC", BACKEND, "C#",
                                f"nagłówek X-AspNetMvc-Version: {h['x-aspnetmvc-version']}",
                                h["x-aspnetmvc-version"]))
    if h.get("x-generator"):
        found += _match_rules(h["x-generator"], _GENERATOR_RULES, "nagłówek X-Generator")
    if "x-drupal-cache" in h or "x-drupal-dynamic-cache" in h:
        found.append(Technology("Drupal", BACKEND, "PHP", "nagłówek X-Drupal-Cache"))
    if "x-runtime" in h:
        found.append(Technology("Ruby (Rack)", BACKEND, "Ruby", "nagłówek X-Runtime"))
    return found


def _from_cookies(cookie_names: Iterable[str]) -> list[Technology]:
    found = []
    for cookie in cookie_names:
        for pattern, name, language in _COOKIE_RULES:
            if re.fullmatch(pattern, cookie):
                found.append(Technology(name, BACKEND, language, f"ciasteczko {cookie}"))
                break
    return found


def _from_signals(s: Mapping[str, object]) -> list[Technology]:
    found: list[Technology] = []

    def add(name: str, side: str, language: str | None, evidence: str, version: object = None) -> None:
        found.append(Technology(name, side, language, evidence, str(version) if version else None))

    if s.get("generator"):
        found += _match_rules(str(s["generator"]), _GENERATOR_RULES, "meta generator")
    if s.get("next"):
        add("Next.js", FRONTEND, "JavaScript", "dane __NEXT_DATA__ / skrypty /_next/")
    if s.get("nuxt"):
        add("Nuxt", FRONTEND, "JavaScript", "obiekt __NUXT__ / skrypty /_nuxt/")
    if s.get("react") or s.get("next"):
        add("React", FRONTEND, "JavaScript", "elementy renderowane przez React", s.get("react_version"))
    if s.get("vue") or s.get("nuxt"):
        add("Vue.js", FRONTEND, "JavaScript", "elementy renderowane przez Vue", s.get("vue_version"))
    if s.get("angular") is not None:
        add("Angular", FRONTEND, "TypeScript", "atrybut ng-version", s.get("angular"))
    if s.get("angularjs") is not None:
        add("AngularJS", FRONTEND, "JavaScript", "obiekt window.angular", s.get("angularjs"))
    if s.get("svelte"):
        add("Svelte", FRONTEND, "JavaScript", "klasy CSS svelte-*")
    if s.get("jquery") is not None:
        add("jQuery", FRONTEND, "JavaScript", "obiekt window.jQuery", s.get("jquery"))
    if s.get("blazor"):
        add("Blazor", FRONTEND, "C#", "obiekt window.Blazor / skrypt blazor.*.js")
    if s.get("livewire"):
        add("Laravel Livewire", BACKEND, "PHP", "obiekt window.Livewire")
    if s.get("viewstate"):
        add("ASP.NET Web Forms", BACKEND, "C#", "pole formularza __VIEWSTATE")
    if s.get("django_csrf"):
        add("Django", BACKEND, "Python", "pole formularza csrfmiddlewaretoken")
    if s.get("rails_csrf"):
        add("Ruby on Rails", BACKEND, "Ruby", "meta csrf-param = authenticity_token")
    return found


def _from_resources(resource_urls: Iterable[str]) -> tuple[list[Technology], bool]:
    found: list[Technology] = []
    wasm = False
    for url in resource_urls:
        path = url.split("?", 1)[0].lower()
        if path.endswith(".wasm"):
            wasm = True
        for fragment, name, side, language in _RESOURCE_RULES:
            if fragment in path:
                found.append(Technology(name, side, language, f"zasób {fragment}"))
    return found, wasm


def _dedupe(techs: list[Technology]) -> list[Technology]:
    """Jedna pozycja na (nazwę, warstwę); wygrywa pierwsza, ale wersja jest uzupełniana."""
    merged: dict[tuple[str, str], Technology] = {}
    for t in techs:
        key = (t.name, t.side)
        prev = merged.get(key)
        if prev is None:
            merged[key] = t
        elif prev.version is None and t.version:
            merged[key] = Technology(prev.name, prev.side, prev.language, prev.evidence, t.version)
    return list(merged.values())


def detect(
    headers: Mapping[str, str],
    cookie_names: Iterable[str],
    signals: Mapping[str, object],
    resource_urls: Iterable[str],
) -> TechProfile:
    resource_techs, wasm = _from_resources(resource_urls)
    techs = _dedupe(_from_headers(headers) + _from_cookies(cookie_names)
                    + _from_signals(signals) + resource_techs)

    frontend = ["HTML"]
    if signals.get("styles"):
        frontend.append("CSS")
    front_langs = [t.language for t in techs if t.side == FRONTEND and t.language]
    if signals.get("scripts") or front_langs:
        frontend.append("JavaScript")
    frontend += front_langs
    if wasm:
        frontend.append("WebAssembly")

    backend = [t.language for t in techs if t.side == BACKEND and t.language]
    return TechProfile(techs, _unique(frontend), _unique(backend))
