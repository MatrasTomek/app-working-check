import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from urllib.parse import parse_qs, urlsplit
import time

import pytest
from playwright.sync_api import sync_playwright

SITE_DIR = Path(__file__).parent / "site"


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def log_message(self, format, *args):  # cisza w wynikach testów
        pass

    def _send(self, status, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _github(self, path):
        """Udawane GitHub REST API pod /gh: konto „tomek” (token „dobry”), „nikt” (404), „limit” (403)."""
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        query = parse_qs(urlsplit(self.path).query)
        auth = self.headers.get("Authorization")

        def repo(name, **kw):
            return {"name": name, "full_name": f"tomek/{name}", "html_url": f"https://github.com/tomek/{name}",
                    "description": None, "homepage": None, "has_pages": False, "fork": False,
                    "archived": False, "private": False, "pushed_at": "2026-01-01T00:00:00Z", **kw}

        page1 = [
            repo("shop", homepage=f"{base}/ok.html", description="Sklep <b>internetowy</b>",
                 pushed_at="2026-11-01T10:00:00Z"),
            repo("docs", has_pages=True, pushed_at="2026-10-01T10:00:00Z"),
            repo("old", archived=True),
            repo("forked", fork=True),
        ]
        page2 = [repo("lib", description="Biblioteka")]
        languages = {"shop": {"TypeScript": 700, "CSS": 300}, "docs": {"HTML": 10},
                     "lib": {"Python": 1000}, "secret": {"Go": 5}}

        def send_json(data, status=200, headers=None):
            self._send(status, json.dumps(data).encode("utf-8"), "application/json", headers)

        if auth not in (None, "Bearer dobry"):
            return send_json({"message": "Bad credentials"}, 401)
        if path == "/gh/users/tomek":
            return send_json({"login": "tomek", "type": "User"})
        if path == "/gh/users/limit":
            return send_json({"message": "rate limit"}, 403, {"X-RateLimit-Remaining": "0"})
        if path == "/gh/user":
            return send_json({"login": "tomek"})
        if path in ("/gh/users/tomek/repos", "/gh/user/repos"):
            if query.get("page") == ["2"]:
                extra = [repo("secret", private=True)] if path == "/gh/user/repos" else []
                return send_json(page2 + extra)
            return send_json(page1, headers={"Link": f'<{base}{path}?page=2>; rel="next"'})
        if path == "/gh/repos/tomek/docs/pages":
            return send_json({"html_url": f"{base}/tech-next.html"})
        name = path.removeprefix("/gh/repos/tomek/").removesuffix("/languages")
        if path.endswith("/languages") and name in languages:
            return send_json(languages[name])
        return send_json({"message": "Not Found"}, 404)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path.startswith("/gh/"):
                self._github(path)
            elif path == "/api/ok":
                self._send(200, b'{"ok":true}', "application/json")
            elif path == "/api/500":
                self._send(500, b"error")
            elif path == "/api/404":
                self._send(404, b"not found")
            elif path == "/status/502":
                self._send(502, b"Bad Gateway")
            elif path == "/tech/php":
                self._send(200, b'<!doctype html><html><body><h1>PHP</h1></body></html>',
                           "text/html; charset=utf-8",
                           {"X-Powered-By": "PHP/8.2.1", "Server": "nginx/1.25.3",
                            "Set-Cookie": "PHPSESSID=abc123; Path=/"})
            elif path == "/redirect":
                self._send(302, headers={"Location": "/ok.html"})
            elif path == "/poll":
                time.sleep(1)
                self._send(200, b"ok")
            elif path == "/hang":
                time.sleep(4)
                self._send(200, b"late")
            elif path == "/slow-doc":
                # dokument, który nigdy się nie kończy w limicie: częściowa treść, potem cisza
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write('<!doctype html><html><head><meta charset="utf-8"></head>'
                                 '<body><h1>Częściowy dokument</h1>'.encode("utf-8"))
                self.wfile.flush()
                time.sleep(4)
            else:
                super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            if path != "/login":
                self._send(404, b"not found")
            elif form.get("user") == ["jan"] and form.get("pass") == ["sekret"]:
                self._send(302, headers={"Location": "/dashboard.html"})
            elif form.get("pass") == ["to502"]:
                self._send(302, headers={"Location": "/status/502"})
            elif form.get("pass") == ["slow"]:
                # odpowiedź strumieniowana: <body> od razu, formularz z alertem po sekundzie
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'<!doctype html><html><head><meta charset="utf-8"></head><body>')
                self.wfile.flush()
                time.sleep(1)
                page = (SITE_DIR / "login.html").read_text(encoding="utf-8")
                tail = page.split("<body>", 1)[1].replace(
                    "</body>", '<div role="alert">Nieprawidłowy login lub hasło</div></body>')
                self.wfile.write(tail.encode("utf-8"))
            else:
                body = (SITE_DIR / "login.html").read_text(encoding="utf-8").replace(
                    "</body>", '<div role="alert">Nieprawidłowy login lub hasło</div></body>')
                self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="session")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def dead_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()
