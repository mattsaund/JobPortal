import os
import subprocess
import sys

from jobportal import cli, osutil


def test_os_name():
    assert osutil.os_name() in ("windows", "macos", "linux") or osutil.os_name() == sys.platform


def test_chrome_override(tmp_path, monkeypatch):
    fake = tmp_path / ("chrome.exe" if osutil.IS_WIN else "chrome")
    fake.write_text("")
    monkeypatch.setenv("JOBPORTAL_CHROME", str(fake))
    assert osutil.find_chrome() == str(fake)


def test_parser_modes():
    p = cli.build_parser()
    assert p.parse_args(["--browser"]).browser
    assert p.parse_args(["--server", "--port", "9999"]).port == 9999


def test_cli_version_and_doctor(tmp_path):
    env = {**os.environ, "JOBPORTAL_HOME": str(tmp_path)}
    out = subprocess.run([sys.executable, "-m", "jobportal", "--version"], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and "JobPortal" in out.stdout
    doc = subprocess.run([sys.executable, "-m", "jobportal", "--doctor"], capture_output=True, text=True, env=env, timeout=120)
    assert doc.returncode == 0, doc.stderr
    assert "Python" in doc.stdout and "ChatGPT" in doc.stdout and str(tmp_path) in doc.stdout
