"""JobPortal as a desktop program: starts the local server and opens the dashboard in a window of its own.

Who calls it: app/cli.py runs main() for a plain `jobportal` (and for `--browser`), and uses make_server() and up() for the
server-only modes. app/doctor.py asks _gui() which window toolkit would be used.

The window chain, best first:
  1. A native window through pywebview, which wraps the system's own web view: Edge WebView2 on Windows, WebKit on macOS,
     GTK WebKit or Qt WebEngine on Linux. The dashboard calls back into Python through the Bridge class for what a browser
     tab does on its own: saving downloads, opening links outside the window, desktop notifications.
  2. Without a native toolkit: Chrome, Edge, Chromium or Brave in app mode (a window with no tabs or address bar) on a
     profile of its own. JobPortal watches that window and quits when it closes (open_app_window).
  3. As a last resort, a normal tab in the default browser.

The server: when a JobPortal server is already listening on the port (`jobportal --background`), the window attaches to it
and leaves it running. Otherwise the server runs on a background thread in this process and stops when the window closes.

On Linux, an AppImage adds itself to the app menu the first time it runs (add_to_app_menu)."""
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

import uvicorn

from jobportal.core import bus, osutil
from jobportal.core.config import CACHE, DATA, HOST, PORT, RESOURCES, STATIC

# WebKitGTK's DMA-BUF renderer paints a black window on the proprietary NVIDIA driver; the shared-memory path works
# everywhere. It must be set before the GTK window starts, so it is set as soon as this module loads.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

BASE = f"http://{HOST}:{PORT}"
ICON = STATIC / "icon.svg"


# ---------------------------------------------------------------- the server

def up() -> bool:
    """Whether a JobPortal server answers on the port (this process's or another one's)."""
    try:
        urllib.request.urlopen(f"{BASE}/api/meta", timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def running_search() -> bool:
    """Whether the server is in the middle of a job search, so closing the window should ask first."""
    try:
        return bool(json.load(urllib.request.urlopen(f"{BASE}/api/stats", timeout=2))["state"].get("running"))
    except Exception:  # noqa: BLE001
        return False


def make_server() -> uvicorn.Server:
    """The uvicorn server for the dashboard, not yet started.

    The app object is passed directly (not an import string), and uvicorn's optional speedups (uvloop, httptools,
    websockets) are switched off, so a packaged build needs nothing beyond what it bundles. timeout_graceful_shutdown stops
    the shutdown from waiting forever on the dashboard's live event stream, which never ends by itself. The app keeps a
    handle on the server so the dashboard's Quit button (/api/quit) can stop it."""
    from jobportal.web.server import app
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", timeout_graceful_shutdown=5,
                                           loop="asyncio", http="h11", ws="none"))
    app.state.server = server
    return server


def start_server() -> tuple[uvicorn.Server | None, threading.Thread | None]:
    """Run the server on a background thread, unless one already answers on the port. Returns (server, thread), or
    (None, None) when attaching to a server that is already running. Waits up to 30 seconds for the new server to answer,
    and exits with a message when its thread dies first (usually because another program holds the port)."""
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
    """Tell our server to finish and wait up to 20 seconds for it. Does nothing when attached to another process's server."""
    if server:
        server.should_exit = True
        thread.join(timeout=20)


# ---------------------------------------------------------------- the native window's bridge

class Bridge:
    """Methods the dashboard calls as window.pywebview.api.* in the native window (see web/static/js/core.js), for things a
    browser tab would do by itself. pywebview hands JavaScript every public method, and walks into public attributes too,
    so the window handle stays in _window: names that start with "_" are skipped, and the page never gets the window."""

    def __init__(self):
        self._window = None  # set by main() once the window exists

    def open_external(self, url: str) -> bool:
        """Open a web or mail link in the default browser or mail app instead of inside the window."""
        if not re.match(r"^(https?://|mailto:)", url or "", re.I):
            return False
        return osutil.open_url(url)

    def save_file(self, path: str) -> dict:
        """Download one of JobPortal's own exports (a /api/... path) and save it where the user picks in a Save dialog.
        Returns {"ok": True, "path"}, {"ok": False, "cancelled": True} or {"ok": False, "error"}."""
        import webview
        if not (path or "").startswith("/api/"):
            return {"ok": False, "error": "not a JobPortal file"}
        try:
            with urllib.request.urlopen(BASE + path, timeout=300) as r:
                data, disposition = r.read(), r.headers.get("Content-Disposition", "")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        # The server names the file in Content-Disposition: filename*=utf-8''... (percent-encoded) when the name has
        # non-ASCII letters, else filename="...".
        m = re.search(r"filename\*=utf-8''([^;]+)", disposition, re.I) or re.search(r'filename="?([^";]+)"?', disposition)
        name = unquote(m.group(1)) if m else Path(path).name
        downloads = Path.home() / "Downloads"
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=str(downloads if downloads.exists() else Path.home()),
                                                 save_filename=name)
        if not picked:
            return {"ok": False, "cancelled": True}
        dest = Path(picked if isinstance(picked, str) else picked[0])  # some platforms return a list of one path
        dest.write_bytes(data)
        return {"ok": True, "path": str(dest)}

    def notify(self, title: str, body: str = "") -> None:
        """A desktop notification. Linux's notify-send needs the icon passed in; Windows and macOS use the app's own."""
        osutil.notify(title, body, ICON if osutil.IS_LINUX else None)


# ---------------------------------------------------------------- windows without a native toolkit

def open_in_browser(server, thread) -> None:
    """Open the dashboard in the default browser. When this process owns the server, keep running until the server stops
    (Quit in Settings) or Ctrl+C."""
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
    """A window of its own without a native toolkit: Chrome, Edge, Chromium or Brave in app mode (no tabs or address bar).
    When this process owns the server, block until the window closes, then stop the server. Returns False when no such
    browser is installed or the window never loaded the dashboard, so the caller can fall back to a browser tab.

    How the window is watched: the dashboard keeps a live event stream open (/api/events), so bus.listeners() tells whether
    a window shows it. JobPortal quits once the browser process has exited and no dashboard has been connected for
    APP_WINDOW_GRACE seconds. The grace period covers a page reload, and the case where the browser handed the window to an
    already running copy of itself and exited right away."""
    browser = osutil.find_chrome()  # an installed browser: the PDF engine bundled with the app is headless and has no window
    if not browser:
        return False
    # A profile of its own makes the window a separate browser process, apart from the user's own browser, so its exit
    # means the window closed. ?shell=app tells the dashboard to send links to the default browser and to warn before
    # closing during a search. --class matches StartupWMClass in jobportal.desktop, so Linux docks group the window.
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
    # Wait for the dashboard to connect. A browser that exits with an error code, or takes too long, counts as no window.
    # Exit code 0 is fine: the browser may have passed the window to a copy of itself that already runs this profile.
    deadline = time.monotonic() + APP_WINDOW_WAIT
    while not bus.listeners():
        if proc.poll() not in (None, 0) or time.monotonic() > deadline or not thread.is_alive():
            if proc.poll() is None:
                proc.kill()
            return False
        time.sleep(0.25)
    print("JobPortal is open in its own window. Closing the window quits it.")
    quiet_since = None  # when the browser was first seen gone with no dashboard connected
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
    """The fallbacks when there is no native window: an app-mode browser window, else a normal browser tab."""
    if not open_app_window(server, thread):
        open_in_browser(server, thread)


# ---------------------------------------------------------------- Linux app menu (AppImage)

# The last line of every menu entry this code writes. Entries without it were made by someone else (by hand, or by
# packaging/linux/install-desktop-entry.sh for a source checkout) and are never touched.
APPIMAGE_MARK = "X-JobPortal-AppImage=true"


def _exec_arg(path: str) -> str:
    """Quote a path for a desktop entry's Exec key. The desktop entry spec unescapes the value twice: first as a string
    value, where a doubled backslash stands for one, then by the Exec quoting rules, where a double quote, backtick, dollar
    sign or backslash inside double quotes needs a backslash in front. So a backslash in the path is written four times.
    A percent sign starts a field code (like %f), so a literal one is written twice."""
    out = path.replace("\\", "\\\\\\\\")
    for ch in '"`$':
        out = out.replace(ch, "\\\\" + ch)
    return '"' + out.replace("%", "%%") + '"'


def add_to_app_menu() -> bool:
    """When running as an AppImage on Linux, add JobPortal to the app menu, or point the entry at the AppImage again if the
    file moved. Writes ~/.local/share/applications/jobportal.desktop (from resources/jobportal.desktop) and copies the icon
    into the icon theme. Returns True when it wrote something."""
    appimage = os.environ.get("APPIMAGE")  # set by the AppImage runtime to the .AppImage file's path
    if not (osutil.IS_LINUX and appimage):
        return False
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    entry = share / "applications" / "jobportal.desktop"
    icon = share / "icons" / "hicolor" / "scalable" / "apps" / "jobportal.svg"
    try:
        old = entry.read_text(encoding="utf-8") if entry.is_file() else None
    except (OSError, UnicodeDecodeError):
        return False  # an entry this code can't read isn't one it wrote, so leave it alone
    if old is not None and APPIMAGE_MARK not in old:
        return False
    template = (RESOURCES / "jobportal.desktop").read_text(encoding="utf-8")
    text = template.replace("@EXEC@", _exec_arg(appimage)).rstrip("\n") + f"\n{APPIMAGE_MARK}\n"
    if text == old and icon.is_file():
        return False  # already up to date
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICON, icon)
        entry.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- the native window

def _gui() -> str | None:
    """Pick pywebview's backend. On Linux: "gtk" when GTK's WebKit bindings are installed (WebKit2 4.1, or the older 4.0),
    else "qt" when Qt bindings are, else None (no native window). Elsewhere None, which means the platform default
    (WebView2 on Windows, WebKit on macOS)."""
    if not osutil.IS_LINUX:
        return None
    try:
        import gi
        for version in ("4.1", "4.0"):
            try:
                gi.require_version("WebKit2", version)  # raises ValueError when that version isn't installed
                return "gtk"
            except ValueError:
                continue
    except ImportError:
        pass
    try:
        import qtpy  # noqa: F401 (pywebview's Qt backend runs on qtpy)
        return "qt"
    except ImportError:
        return None


def main(browser: bool = False) -> None:
    """Start JobPortal: the server (or attach to a running one), then the best window available; see the module docstring.
    browser=True skips the window and opens a browser tab. Returns when JobPortal should exit."""
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
    # The dark background avoids a white flash before the dashboard paints. pywebview blocks text selection unless asked.
    window = webview.create_window("JobPortal", f"{BASE}/", js_api=bridge, width=1480, height=940, min_size=(1024, 680),
                                   background_color="#0c0d10", text_select=True)
    bridge._window = window

    def on_closing():
        """Returning False keeps the window open. Only ask when closing would stop our own server in mid-search."""
        if server and running_search():
            return window.create_confirmation_dialog("Quit JobPortal?", "A search is running. Quitting stops it; progress so far is saved.")
        return True

    window.events.closing += on_closing
    # A storage folder (with private mode off) keeps the dashboard's saved settings, such as the alerts switch, between runs.
    storage = DATA / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    try:
        # Blocks until the window closes. Linux window managers take the icon from here; Windows and macOS use the app's.
        webview.start(gui=gui, private_mode=False, storage_path=str(storage),
                      **({"icon": str(ICON)} if osutil.IS_LINUX and ICON.exists() else {}))
    except Exception as e:  # noqa: BLE001 (missing WebView2 runtime, broken toolkit...)
        print(f"Couldn't open a native window ({e}).")
        return open_without_toolkit(server, thread)
    stop_server(server, thread)
