import threading
import time

from appcheck.web.app import create_app
from appcheck.web.live import HEARTBEAT_TIMEOUT, LiveMode

from .conftest import POST_HEADERS, login, make_client


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeJob:
    def __init__(self):
        self.runs = 0

    def trigger(self):
        self.runs += 1
        return True


def _live(clock):
    servers, projects = FakeJob(), FakeJob()
    return LiveMode({"servers": servers, "projects": projects}, clock=clock, run_thread=False), servers, projects


def test_start_runs_immediately_then_on_interval():
    clock = Clock()
    live, servers, projects = _live(clock)
    live.start({"servers": 60, "projects": 120})
    assert (servers.runs, projects.runs) == (1, 1)
    clock.now += 59; live.heartbeat(); live.tick()
    assert servers.runs == 1
    clock.now += 1; live.tick()
    assert (servers.runs, projects.runs) == (2, 1)
    clock.now += 60; live.heartbeat(); live.tick()
    assert (servers.runs, projects.runs) == (3, 2)


def test_expires_without_heartbeat():
    clock = Clock()
    live, servers, _ = _live(clock)
    live.start({"servers": 60, "projects": 600})
    clock.now += HEARTBEAT_TIMEOUT + 1
    live.tick()
    assert live.enabled is False and live.state()["expires_in"] is None
    clock.now += 600; live.tick()
    assert servers.runs == 1  # po wygaśnięciu nic się nie uruchamia
    assert live.heartbeat() is False  # heartbeat nie wznawia trybu — trzeba kliknąć Start


def test_stop_halts_runs():
    clock = Clock()
    live, servers, _ = _live(clock)
    live.start({"servers": 60, "projects": 600})
    live.stop()
    clock.now += 600; live.heartbeat(); live.tick()
    assert servers.runs == 1


def test_loop_thread_exits_after_stop():
    live = LiveMode({"servers": FakeJob()}, tick_seconds=0.01)
    live.start()
    thread = live._thread
    assert thread.is_alive()
    live.stop()
    thread.join(2)
    assert not thread.is_alive()
    assert all(t.name != "live-mode" for t in threading.enumerate())


def test_stop_then_immediate_start_keeps_loop_running():
    live = LiveMode({"servers": FakeJob()}, tick_seconds=0.05)
    live.start()
    live.stop()
    live.start()
    time.sleep(0.2)
    assert live._thread.is_alive() and live.enabled
    live.stop()
    live._thread.join(2)


def test_api(settings):
    clock = Clock()
    live, servers, projects = _live(clock)
    with make_client(create_app(settings, env={}, live=live)) as c:
        assert c.get("/api/live").status_code == 401
        assert c.post("/api/live/start", headers=POST_HEADERS).status_code == 401
        login(c)
        r = c.post("/api/live/start", json={"servers_interval": 120}, headers=POST_HEADERS)
        assert r.json()["enabled"] is True and r.json()["intervals"] == {"servers": 120, "projects": 600}
        assert servers.runs == 1
        assert c.post("/api/live/heartbeat", headers=POST_HEADERS).json()["expires_in"] == HEARTBEAT_TIMEOUT
        assert c.post("/api/live/stop", headers=POST_HEADERS).json()["enabled"] is False
        assert c.post("/api/live/start", headers=POST_HEADERS).json()["enabled"] is True  # bez treści


def test_api_rejects_bad_intervals_and_csrf(settings):
    live, _, _ = _live(Clock())
    with make_client(create_app(settings, env={}, live=live)) as c:
        login(c)
        for bad in (0, 10, 59, 3601, -5, "x"):
            assert c.post("/api/live/start", json={"servers_interval": bad},
                          headers=POST_HEADERS).status_code == 422
        assert c.post("/api/live/start", headers={"X-Dashboard": "1"}).status_code == 403
        assert live.enabled is False
