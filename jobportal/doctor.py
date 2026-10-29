"""`jobportal --doctor`: a quick check of everything JobPortal needs on this computer, with what to install when something is missing."""
import os
import platform
import socket
import subprocess
import sys

from . import __version__, osutil


def _row(ok: bool | None, name: str, detail: str) -> str:
    mark = {True: "ok  ", False: "MISS", None: "opt "}[ok]
    return f"  [{mark}] {name:<16} {detail}"


def _claude_version(cmd: list[str]) -> str:
    try:
        out = subprocess.run([*cmd, "--version"], capture_output=True, text=True, timeout=20, **osutil.popen_flags())
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _window_toolkit() -> tuple[bool | None, str]:
    try:
        import webview  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"pywebview isn't importable ({e}); JobPortal will open in your browser"
    if osutil.IS_LINUX:
        from .desktop import _gui
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
    from .config import CACHE, DATA, PORT
    from . import settings as settings_mod
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

    try:
        claude_setting = settings_mod.get()["ai"].get("claude_bin") or "claude"
    except Exception:  # noqa: BLE001 (a broken database shouldn't stop the doctor)
        claude_setting = "claude"
    path = osutil.find_claude(claude_setting)
    if path:
        cmd = osutil.claude_command(claude_setting)
        ver = _claude_version(cmd)
        rows.append(_row(True, "Claude Code", f"{ver or 'found'} at {path}. If you haven't yet, run `claude` once in a terminal to log in."))
        if os.environ.get("ANTHROPIC_API_KEY"):
            rows.append(_row(None, "API key", "ANTHROPIC_API_KEY is set; JobPortal ignores it and uses your Claude login unless you "
                                              "turn that off in Settings -> AI"))
    else:
        problems += 1
        rows.append(_row(False, "Claude Code", "not found. Install it from https://claude.com/claude-code and run `claude` once to log in."))

    chrome = osutil.find_chrome()
    if chrome:
        rows.append(_row(True, "PDF export", chrome))
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
