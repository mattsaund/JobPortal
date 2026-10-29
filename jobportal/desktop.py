"""JobPortal as a desktop program: the same server and dashboard in a native window (pywebview: Edge WebView2 on Windows,
WebKit on macOS, GTK or Qt on Linux). Without a native window toolkit it opens Chrome, Edge, Chromium or Brave in app mode,
which is still a window of its own. A normal browser tab is the last resort.

If a JobPortal server is already running (`jobportal --background`) the window attaches to it; otherwise the server runs inside
this process and stops when the window closes."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote

# WebKitGTK's DMA-BUF renderer paints a black window on the proprietary NVIDIA driver; the shared-memory path works everywhere.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

import uvicorn  # noqa: E402

from . import bus, osutil  # noqa: E402
from .config import CACHE, DATA, HOST, PORT, RESOURCES, STATIC  # noqa: E402

BASE = f"http://{HOST}:{PORT}"
ICON = STATIC / "icon.svg"


def up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE}/api/meta", timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def running_search() -> bool:
    try:
        return bool(json.load(urllib.request.urlopen(f"{BASE}/api/stats", timeout=2))["state"].get("running"))
    except Exception:  # noqa: BLE001
        return False


class Bridge:
    """Methods the dashboard calls as window.pywebview.api.* for things a browser tab would do on its own."""

    def __init__(self):
        self._window = None

    def open_external(self, url: str) -> bool:
        if not re.match(r"^(https?://|mailto:)", url or "", re.I):
            return False
        return osutil.open_url(url)

    def save_file(self, path: str) -> dict:
        """Download one of JobPortal's own exports (/api/...) and save it where the user picks."""
        import webview
        if not (path or "").startswith("/api/"):
            return {"ok": False, "error": "not a JobPortal file"}
        try:
            with urllib.request.urlopen(BASE + path, timeout=300) as r:
                data, disp = r.read(), r.headers.get("Content-Disposition", "")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        m = re.search(r"filename\*=utf-8''([^;]+)", disp, re.I) or re.search(r'filename="?([^";]+)"?', disp)
        name = unquote(m.group(1)) if m else Path(path).name
        downloads = Path.home() / "Downloads"
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=str(downloads if downloads.exists() else Path.home()),
                                                 save_filename=name)
        if not picked:
            return {"ok": False, "cancelled": True}
        dest = Path(picked if isinstance(picked, str) else picked[0])
        dest.write_bytes(data)
        return {"ok": True, "path": str(dest)}

    def notify(self, title: str, body: str = "") -> None:
        osutil.notify(title, body, ICON if osutil.IS_LINUX else None)


def make_server() -> uvicorn.Server:
    """The app object is passed directly (not an import string) and optional speedups are off, so a packaged build needs
    nothing beyond what it bundles. The app keeps a handle so the dashboard's Quit button can stop it."""
    from .main import app
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", timeout_graceful_shutdown=5,
                                           loop="asyncio", http="h11", ws="none"))
    app.state.server = server
    return server


def start_server() -> tuple[uvicorn.Server | None, threading.Thread | None]:
    """Run the server on a background thread unless one is already listening on the port."""
    if up():
        return None, None
    server = make_server()
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(120):
        if up():
            break
        if not thread.is_alive():
            raise SystemExit(f"JobPortal's server couldn't start on port {PORT}. Is another program using it? Try --port 8790.")
        time.sleep(0.25)
    return server, thread


def stop_server(server, thread) -> None:
    if server:
        server.should_exit = True
        thread.join(timeout=20)


def open_in_browser(server, thread) -> None:
    osutil.open_url(f"{BASE}/")
    if not server:
        print(f"JobPortal is already running at {BASE}. Opened it in your browser.")
        return
    print(f"JobPortal is running at {BASE} (opened in your browser). Quit it from Settings, or press Ctrl+C here.")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(server, thread)


APP_WINDOW_WAIT = 30  # seconds for the app window to load the dashboard (a new browser profile starts slowly)
APP_WINDOW_GRACE = 3  # seconds with no dashboard connected, after the browser exits, before JobPortal quits


def open_app_window(server, thread) -> bool:
    """A window of its own without a native toolkit: Chrome, Edge, Chromium or Brave in app mode (no tabs or address bar),
    with a separate profile so it runs apart from the user's own browser. JobPortal quits when the window closes.
    Returns False when no such browser is installed or the window never opened."""
    browser = osutil.find_chrome()
    if not browser:
        return False
    profile = CACHE / "app-window"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [browser, f"--app={BASE}/?shell=app", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
           "--window-size=1480,940", *(["--class=jobportal"] if osutil.IS_LINUX else [])]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **osutil.popen_flags())
    except OSError:
        return False
    if not server:  # attached to a server that's already running, so opening the window is all there is to do
        return True
    deadline = time.monotonic() + APP_WINDOW_WAIT
    while not bus.listeners():  # the dashboard connects to /api/events once the window has loaded it
        if proc.poll() not in (None, 0) or time.monotonic() > deadline or not thread.is_alive():
            if proc.poll() is None:
                proc.kill()
            return False
        time.sleep(0.25)
    print("JobPortal is open in its own window. Closing the window quits it.")
    quiet_since = None
    while thread.is_alive():
        if proc.poll() is None or bus.listeners():
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= APP_WINDOW_GRACE:
            break
        time.sleep(0.25)
    stop_server(server, thread)
    return True


def open_without_toolkit(server, thread) -> None:
    if not open_app_window(server, thread):
        open_in_browser(server, thread)


APPIMAGE_MARK = "X-JobPortal-AppImage=true"


def _exec_arg(path: str) -> str:
    """Quote a path for a desktop entry's Exec key. The spec unescapes it twice: once as a string value, then as Exec quoting."""
    out = path.replace("\\", "\\\\\\\\")
    for ch in '"`$':
        out = out.replace(ch, "\\\\" + ch)
    return '"' + out.replace("%", "%%") + '"'


def add_to_app_menu() -> bool:
    """Running as an AppImage: add JobPortal to the Linux app menu, or point the entry at the AppImage again if it moved.
    An entry made for a source checkout (packaging/linux/install-desktop-entry.sh) is left alone. True when it wrote one."""
    appimage = os.environ.get("APPIMAGE")
    if not (osutil.IS_LINUX and appimage):
        return False
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    entry = share / "applications" / "jobportal.desktop"
    icon = share / "icons" / "hicolor" / "scalable" / "apps" / "jobportal.svg"
    old = entry.read_text(encoding="utf-8") if entry.is_file() else None
    if old is not None and APPIMAGE_MARK not in old:
        return False
    template = (RESOURCES / "jobportal.desktop").read_text(encoding="utf-8")
    text = template.replace("@EXEC@", _exec_arg(appimage)).rstrip("\n") + f"\n{APPIMAGE_MARK}\n"
    if text == old and icon.is_file():
        return False
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICON, icon)
        entry.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def _gui() -> str | None:
    """Pick pywebview's backend: GTK or Qt on Linux; the platform default (WebView2, Cocoa) elsewhere."""
    if not osutil.IS_LINUX:
        return None
    try:
        import gi
        for v in ("4.1", "4.0"):
            try:
                gi.require_version("WebKit2", v)
                return "gtk"
            except ValueError:
                continue
    except ImportError:
        pass
    try:
        import qtpy  # noqa: F401
        return "qt"
    except ImportError:
        return None


def main(browser: bool = False) -> None:
    if add_to_app_menu():
        print("Added JobPortal to your app menu.")
    server, thread = start_server()
    if browser:
        return open_in_browser(server, thread)
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        print(f"No native window available ({e}).")
        return open_without_toolkit(server, thread)
    gui = _gui()
    if osutil.IS_LINUX and gui is None:
        print("No native window toolkit found (GTK WebKit or Qt WebEngine).")
        return open_without_toolkit(server, thread)
    if gui == "gtk":
        try:
            from gi.repository import GLib
            GLib.set_prgname("jobportal")  # matches StartupWMClass in jobportal.desktop so the dock groups the window
            GLib.set_application_name("JobPortal")
        except Exception:  # noqa: BLE001
            pass

    bridge = Bridge()
    window = webview.create_window("JobPortal", f"{BASE}/", js_api=bridge, width=1480, height=940, min_size=(1024, 680),
                                   background_color="#0c0d10", text_select=True)
    bridge._window = window

    def on_closing():
        if server and running_search():
            return window.create_confirmation_dialog("Quit JobPortal?", "A search is running. Quitting stops it; progress so far is saved.")
        return True

    window.events.closing += on_closing
    storage = DATA / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(gui=gui, private_mode=False, storage_path=str(storage),
                      **({"icon": str(ICON)} if osutil.IS_LINUX and ICON.exists() else {}))
    except Exception as e:  # noqa: BLE001 (missing WebView2 runtime, broken toolkit...)
        print(f"Couldn't open a native window ({e}).")
        return open_without_toolkit(server, thread)
    stop_server(server, thread)
