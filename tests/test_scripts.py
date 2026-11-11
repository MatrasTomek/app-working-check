import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("bash") is None, reason="brak bash")
def test_start_script_syntax_and_mode():
    script = ROOT / "scripts" / "start-dashboard.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    if os.name == "posix":
        assert os.access(script, os.X_OK)


def test_bat_uses_crlf_and_starts_wsl():
    data = (ROOT / "scripts" / "start-dashboard.bat").read_bytes()
    assert b"\r\n" in data and b"wsl.exe" in data and b"start-dashboard.sh" in data


def test_readme_warns_against_funnel():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "tailscale serve --bg 8765" in readme and "Nigdy nie używaj `tailscale funnel`" in readme
