"""`jobportal --doctor`: a quick check of everything JobPortal needs on this computer, with what to install when something is
missing.

Who calls it: app/cli.py. CI runs it after the tests, and the release build checks that its "PDF export" row says "built in".

Each row is marked "ok" (works), "MISS" (needed and missing, counted as a problem) or "opt" (optional or not set up yet,
such as the ChatGPT sign-in). The exit code is always 0; the last line says how many problems there are."""
import platform
import socket
import sys
from pathlib import Path

from jobportal import __version__
from jobportal.core import osutil


def _row(ok: bool | None, name: str, detail: str) -> str:
    """One line of the report. ok is True (ok), False (MISS) or None (optional)."""
    mark = {True: "ok  ", False: "MISS", None: "opt "}[ok]
    return f"  [{mark}] {name:<16} {detail}"


def _window_toolkit() -> tuple[bool | None, str]:
    """Whether JobPortal can open a native window here, and how (see app/desktop.py for the fallbacks)."""
    # Without a native toolkit, desktop.py opens a Chromium browser in app mode (still a window of its own), else a tab.
    browser = osutil.find_chrome()
    fallback = (f"JobPortal opens in its own window through {Path(browser).stem} app mode" if browser
                else "JobPortal opens in a browser tab (install Chrome, Edge, Chromium or Brave for a window of its own)")
    try:
        import webview  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return (True if browser else None), f"pywebview isn't importable ({e}); {fallback}"
    if osutil.IS_LINUX:
        from jobportal.app.desktop import _gui
        gui = _gui()
        if gui:
            return True, f"pywebview with {gui.upper()}"
        if getattr(sys, "frozen", False):  # the AppImage can't use the system's GTK, so the app-mode window is the plan
            return (True if browser else None), f"no native toolkit in this build; {fallback}"
        return (True if browser else None), (f"no GTK WebKit or Qt WebEngine; {fallback}. For a native window, install PyGObject "
                                             "and WebKit2GTK 4.1 (Arch: python-gobject webkit2gtk-4.1)")
    if osutil.IS_WIN:
        return True, "pywebview with Edge WebView2 (preinstalled on Windows 10 and 11)"
    return True, "pywebview with the system WebKit"


def _port_free(port: int) -> bool:
    """True when nothing accepts connections on this port on this computer."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def run() -> int:
    """Print the report: Python, the data folder (tested by writing a file), the ChatGPT sign-in, the PDF engine,
    LibreOffice, the window toolkit and the port."""
    from jobportal.ai import signin
    from jobportal.core.config import CACHE, DATA, PORT
    print(f"JobPortal {__version__} on {platform.system()} {platform.release()} ({osutil.os_name()}), Python {platform.python_version()}")
    rows, problems = [], 0
    python_ok = sys.version_info >= (3, 11)
    problems += not python_ok
    rows.append(_row(python_ok, "Python", f"{platform.python_version()} at {sys.executable}" + ("" if python_ok else " (JobPortal needs 3.11 or newer)")))

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

    status = signin.status()
    if status["signed_in"]:
        rows.append(_row(True, "ChatGPT", f"signed in as {status['email'] or status['name'] or 'your account'}"))
    else:
        rows.append(_row(None, "ChatGPT", "not signed in yet. Open JobPortal and click Continue with ChatGPT (needs a Go, Plus or Pro plan)."))

    engine = osutil.find_pdf_engine()
    if engine:
        rows.append(_row(True, "PDF export", ("built in: " if engine == osutil.bundled_pdf_engine() else "") + engine))
    else:
        problems += 1
        rows.append(_row(False, "PDF export", "needs Google Chrome, Microsoft Edge or Chromium (or set JOBPORTAL_CHROME to one)"))

    soffice = osutil.find_soffice()
    rows.append(_row(True if soffice else None, "LibreOffice", soffice or "optional: only needed to import old .doc files"))
    window_ok, window_detail = _window_toolkit()
    rows.append(_row(window_ok, "Window", window_detail))
    port_free = _port_free(PORT)
    rows.append(_row(True if port_free else None, "Port",
                     f"{PORT} " + ("is free" if port_free else "is in use (JobPortal may already be running; or use --port)")))
    print("\n".join(rows))
    print("\nEverything JobPortal needs is here." if not problems else f"\n{problems} thing(s) to fix before JobPortal can do everything.")
    return 0
