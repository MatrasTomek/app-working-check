import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
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

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/ok":
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
