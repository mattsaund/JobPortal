"""`jobportal --doctor`: a quick check of everything JobPortal needs on this computer, with what to install when something is missing."""
import platform
import socket
import sys

from jobportal import __version__
from jobportal.core import osutil


def _row(ok: bool | None, name: str, detail: str) -> str:
    mark = {True: "ok  ", False: "MISS", None: "opt "}[ok]
    return f"  [{mark}] {name:<16} {detail}"


def _window_toolkit() -> tuple[bool | None, str]:
    try:
        import webview  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"pywebview isn't importable ({e}); JobPortal will open in your browser"
    if osutil.IS_LINUX:
        from jobportal.app.desktop import _gui
        gui = _gui()
        if gui:
            return True, f"pywebview with {gui.upper()}"
        return None, ("no GTK WebKit or Qt WebEngine; JobPortal opens in your browser. For a window: install your distro's "
                      "PyGObject + WebKit2GTK 4.1 packages, or `pip install \"pywebview[qt]\"`")
    if osutil.IS_WIN:
        return True, "pywebview with Edge WebView2 (preinstalled on Windows 10 and 11)"
    return True, "pywebview with the system WebKit"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def run() -> int:
    from jobportal.core.config import CACHE, DATA, PORT
    print(f"JobPortal {__version__} on {platform.system()} {platform.release()} ({osutil.os_name()}), Python {platform.python_version()}")
    rows, problems = [], 0
    py_ok = sys.version_info >= (3, 11)
    problems += not py_ok
    rows.append(_row(py_ok, "Python", f"{platform.python_version()} at {sys.executable}" + ("" if py_ok else " (JobPortal needs 3.11 or newer)")))

    try:
        DATA.mkdir(parents=True, exist_ok=True)
        probe = DATA / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        rows.append(_row(True, "Data folder", str(DATA)))
    except OSError as e:
        problems += 1
        rows.append(_row(False, "Data folder", f"{DATA} isn't writable: {e}"))
    rows.append(_row(True, "Cache folder", str(CACHE)))

    from jobportal.ai import signin
    st = signin.status()
    if st["signed_in"]:
        rows.append(_row(True, "ChatGPT", f"signed in as {st['email'] or st['name'] or 'your account'}"))
    else:
        rows.append(_row(None, "ChatGPT", "not signed in yet. Open JobPortal and click Continue with ChatGPT (needs a Go, Plus or Pro plan)."))
    chrome = osutil.find_pdf_engine()
    if chrome:
        rows.append(_row(True, "PDF export", ("built in: " if chrome == osutil.bundled_pdf_engine() else "") + chrome))
    else:
        problems += 1
        rows.append(_row(False, "PDF export", "needs Google Chrome, Microsoft Edge or Chromium (or set JOBPORTAL_CHROME to one)"))

    soffice = osutil.find_soffice()
    rows.append(_row(True if soffice else None, "LibreOffice", soffice or "optional: only needed to import old .doc files"))
    ok, detail = _window_toolkit()
    rows.append(_row(ok, "Window", detail))
    rows.append(_row(True if _port_free(PORT) else None, "Port", f"{PORT} " + ("is free" if _port_free(PORT) else
                                                                                 "is in use (JobPortal may already be running; or use --port)")))
    print("\n".join(rows))
    print("\nEverything JobPortal needs is here." if not problems else f"\n{problems} thing(s) to fix before JobPortal can do everything.")
    return 0
