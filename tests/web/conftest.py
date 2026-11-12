import pytest
from fastapi.testclient import TestClient

from appcheck.web.app import create_app
from appcheck.web.settings import Settings

TOKEN = "T3st-t0ken-ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789"
POST_HEADERS = {"Origin": "https://localhost", "X-Dashboard": "1"}


@pytest.fixture
def settings(tmp_path):
    return Settings(token=TOKEN, base_dir=tmp_path, agents_dir=tmp_path / "agents",
                    claude_sessions_dir=tmp_path / "sessions", copilot_dir=tmp_path / "copilot",
                    vscode_storage_dirs=(tmp_path / "vscode",))


def make_client(app) -> TestClient:
    # https — ciasteczko __Host- ma flagę Secure
    return TestClient(app, base_url="https://localhost")


@pytest.fixture
def client(settings):
    with make_client(create_app(settings)) as c:
        yield c


def login(client, token=TOKEN):
    return client.post("/api/login", json={"token": token}, headers=POST_HEADERS)


@pytest.fixture
def authed(client):
    assert login(client).status_code == 200
    return client
