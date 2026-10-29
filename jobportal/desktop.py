"""JobPortal as a desktop program: the same server and dashboard in a native window (pywebview: Edge WebView2 on Windows,
WebKit on macOS, GTK or Qt on Linux). When no native window is available it opens your default browser instead.

If a JobPortal server is already running (`jobportal --background`) the window attaches to it; otherwise the server runs inside
this process and stops when the window closes."""
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote

# WebKitGTK's DMA-BUF renderer paints a black window on the proprietary NVIDIA driver; the shared-memory path works everywhere.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

import uvicorn  # noqa: E402

from . import osutil  # noqa: E402
from .config import DATA, HOST, PORT, STATIC  # noqa: E402

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


def start_server() -> tuple[uvicorn.Server | None, threading.Thread | None]:
    """Run the server on a background thread unless one is already listening on the port."""
    if up():
        return None, None
    server = uvicorn.Server(uvicorn.Config("jobportal.main:app", host=HOST, port=PORT, log_level="warning", timeout_graceful_shutdown=5))
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
    print(f"JobPortal is running at {BASE} (opened in your browser). Press Ctrl+C here to quit.")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(server, thread)


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
    server, thread = start_server()
    if browser:
        return open_in_browser(server, thread)
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        print(f"No native window available ({e}). Opening JobPortal in your browser instead.")
        return open_in_browser(server, thread)
    gui = _gui()
    if osutil.IS_LINUX and gui is None:
        print("No native window toolkit found (GTK WebKit or Qt WebEngine). Opening JobPortal in your browser instead.\n"
              "For a window of its own, see 'Linux: native window' in the README.")
        return open_in_browser(server, thread)
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
        print(f"Couldn't open a native window ({e}). Opening JobPortal in your browser instead.")
        return open_in_browser(server, thread)
    stop_server(server, thread)
