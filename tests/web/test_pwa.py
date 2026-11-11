import json

from appcheck.web.app import STATIC_DIR, create_app

from .conftest import make_client
from .test_frontend import server  # noqa: F401 — fixtura serwera uvicorn
from .conftest import TOKEN


def test_manifest_and_icons_served(settings):
    with make_client(create_app(settings, env={})) as c:
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
        manifest = r.json()
        assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
        sizes = {i["sizes"] for i in manifest["icons"]}
        assert {"192x192", "512x512"} <= sizes
        assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
        for icon in manifest["icons"]:
            got = c.get(icon["src"])
            assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]


def test_service_worker_never_touches_api():
    js = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/api/")) return;' in js
    assert not any(p.startswith("/api") for p in json.loads(js.split("const SHELL = ")[1].split(";")[0]
                                                              .replace(",\n]", "]")))


def test_service_worker_registers_and_caches_only_shell(server, browser):  # noqa: F811
    page = browser.new_page()
    page.goto(server)
    page.fill("#token", TOKEN)
    page.click("#login-form button")
    page.wait_for_selector("#app:not([hidden])")
    page.evaluate("navigator.serviceWorker.ready")
    page.reload()  # teraz żądania przechodzą przez service workera
    page.wait_for_selector("#app:not([hidden])")
    cached = page.evaluate("""async () => {
        const urls = [];
        for (const key of await caches.keys()) {
            const cache = await caches.open(key);
            for (const req of await cache.keys()) urls.push(new URL(req.url).pathname);
        }
        return urls;
    }""")
    assert "/app.js" in cached and "/" in cached
    assert not any(u.startswith("/api") for u in cached), cached
    page.close()
