import os
import subprocess
import sys

from jobportal.app import cli
from jobportal.core import osutil


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


def test_stop_never_signals_a_stale_pid_file(monkeypatch):
    """A PID file left by a crashed server may name some other program by now, so --stop only removes it."""
    from jobportal.app import desktop
    monkeypatch.setattr(desktop, "up", lambda: False)  # nothing answers on the port
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid_file = cli._pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(bystander.pid), encoding="utf-8")
    try:
        assert cli.stop() == 0
        assert bystander.poll() is None and not pid_file.exists()
    finally:
        bystander.kill()
        bystander.wait()


def test_cli_version_and_doctor(tmp_path):
    env = {**os.environ, "JOBPORTAL_HOME": str(tmp_path)}
    out = subprocess.run([sys.executable, "-m", "jobportal", "--version"], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and "JobPortal" in out.stdout
    doc = subprocess.run([sys.executable, "-m", "jobportal", "--doctor"], capture_output=True, text=True, env=env, timeout=120)
    assert doc.returncode == 0, doc.stderr
    assert "Python" in doc.stdout and "ChatGPT" in doc.stdout and str(tmp_path) in doc.stdout


class FakeThread:
    """Stands in for the server thread: alive until the server is told to exit."""

    def __init__(self, server):
        self.server = server

    def is_alive(self):
        return not self.server.should_exit

    def join(self, timeout=None):
        pass


class FakeServer:
    should_exit = False


def test_app_window_runs_until_the_window_closes(monkeypatch):
    import threading
    import time

    from jobportal.app import desktop
    from jobportal.core import bus
    launched = []

    class Browser:  # a window that the user closes after a moment
        def __init__(self, cmd, **kw):
            launched.append(cmd)
            self.started = time.monotonic()

        def poll(self):
            return None if time.monotonic() - self.started < 0.8 else 0

        def kill(self):
            pass

    monkeypatch.setattr(desktop.osutil, "find_chrome", lambda: "chrome")
    monkeypatch.setattr(desktop.subprocess, "Popen", Browser)
    monkeypatch.setattr(desktop, "APP_WINDOW_GRACE", 0.3)
    q = bus.subscribe()  # the window's dashboard connects, then disconnects as the window closes
    threading.Timer(1.0, bus.unsubscribe, [q]).start()
    server = FakeServer()
    try:
        assert desktop.open_app_window(server, FakeThread(server))
    finally:
        bus.unsubscribe(q)
    assert server.should_exit
    assert f"--app={desktop.BASE}/?shell=app" in launched[0] and any(a.startswith("--user-data-dir=") for a in launched[0])


def test_app_window_gives_up_without_a_working_browser(monkeypatch):
    from jobportal.app import desktop

    class Crashes:
        def __init__(self, cmd, **kw):
            pass

        def poll(self):
            return 1

    server = FakeServer()
    monkeypatch.setattr(desktop.osutil, "find_chrome", lambda: None)
    assert not desktop.open_app_window(server, FakeThread(server))
    monkeypatch.setattr(desktop.osutil, "find_chrome", lambda: "chrome")
    monkeypatch.setattr(desktop.subprocess, "Popen", Crashes)
    assert not desktop.open_app_window(server, FakeThread(server)) and not server.should_exit


def test_appimage_adds_itself_to_the_app_menu(tmp_path, monkeypatch):
    from jobportal.app import desktop
    monkeypatch.setattr(desktop.osutil, "IS_LINUX", True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPIMAGE", "/home/jordan/Apps/JobPortal.AppImage")
    entry = tmp_path / "applications" / "jobportal.desktop"
    assert desktop.add_to_app_menu()
    assert 'Exec="/home/jordan/Apps/JobPortal.AppImage"' in entry.read_text(encoding="utf-8")
    assert (tmp_path / "icons" / "hicolor" / "512x512" / "apps" / "jobportal.png").is_file()
    assert not desktop.add_to_app_menu()  # already up to date
    monkeypatch.setenv("APPIMAGE", "/home/jordan/Downloads/JobPortal.AppImage")
    assert desktop.add_to_app_menu() and "Downloads" in entry.read_text(encoding="utf-8")  # the entry follows a moved file
    entry.write_text("[Desktop Entry]\nExec=/home/jordan/JobPortal/run.sh\n", encoding="utf-8")
    assert not desktop.add_to_app_menu() and "run.sh" in entry.read_text(encoding="utf-8")  # a source checkout's entry stays


def test_appimage_menu_entry_only_for_appimages(monkeypatch):
    from jobportal.app import desktop
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert not desktop.add_to_app_menu()


def test_bundled_pdf_engine_comes_first(tmp_path, monkeypatch):
    from pathlib import Path
    engine = tmp_path / "pdf-engine" / ("chrome-headless-shell.exe" if osutil.IS_WIN else "chrome-headless-shell")
    engine.parent.mkdir()
    engine.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "JobPortal"))
    monkeypatch.delenv("JOBPORTAL_CHROME", raising=False)
    assert Path(osutil.find_pdf_engine()).resolve() == engine.resolve()
    chosen = tmp_path / ("chrome.exe" if osutil.IS_WIN else "chrome")
    chosen.write_text("")
    monkeypatch.setenv("JOBPORTAL_CHROME", str(chosen))
    assert osutil.find_pdf_engine() == str(chosen)  # the user's own choice wins
