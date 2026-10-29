"""Everything that differs between Windows, macOS and Linux, kept in one place so the rest of the app doesn't have to care.

What's here: opening files, folders and links with the system's own apps, desktop notifications, keeping helper programs
from flashing a console window on Windows, and finding two outside programs. The PDF engine (Chrome Headless Shell bundled
with the app, or an installed Chrome, Edge, Chromium or Brave) prints resumes to PDF for documents/render.py. LibreOffice
reads old .doc files for documents/extract.py. app/doctor.py reports what was found.

Key ideas:
- Everything is best effort. Functions return False or None when something isn't available instead of raising, and the
  caller decides what to tell the user.
- Two environment variables let a user point at a program by hand: JOBPORTAL_CHROME (the PDF engine) and
  JOBPORTAL_SOFFICE (LibreOffice). A path that doesn't exist is ignored."""
import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"  # also true on 64-bit Windows
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def os_name() -> str:
    """The system's short name: "windows", "macos" or "linux" (any other system keeps its raw sys.platform name). Shown on
    the Settings page and by --doctor."""
    return "windows" if IS_WIN else "macos" if IS_MAC else "linux" if IS_LINUX else sys.platform


def popen_flags() -> dict:
    """Keyword arguments for subprocess calls that stop helper programs from flashing a console window on Windows.

    The packaged Windows app has no console of its own, so Windows opens a new console window for every console program
    it starts (Chrome printing a PDF, LibreOffice converting a file). CREATE_NO_WINDOW prevents that. Other systems need
    nothing, so the dict is empty there."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def _spawn(cmd: list[str]) -> bool:
    """Start a program in the background without waiting for it or showing its output. False if it couldn't start."""
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_flags())
        return True
    except OSError:
        return False


def open_path(target: str | Path) -> bool:
    """Open a file or folder with the system's default app (Explorer, Finder, the Linux file manager). Returns whether
    the open was started; the app itself may still fail later."""
    target = str(target)
    if IS_WIN:
        # Windows has no "open" command. os.startfile asks the Windows shell, which picks the default app.
        try:
            os.startfile(target)  # noqa: S606 (Windows only)
            return True
        except OSError:
            return False
    # macOS has the "open" command. Linux desktops share xdg-open, which works on GNOME, KDE, Xfce and others.
    return _spawn(["open" if IS_MAC else "xdg-open", target])


def open_url(url: str) -> bool:
    """Open an http(s) or mailto link in the default browser or mail app. The same system tools as open_path() handle
    links, so this just calls it; the separate name keeps calling code easy to read."""
    return open_path(url)


def _applescript_str(s: str) -> str:
    """`s` as an AppleScript string literal: in double quotes, with backslashes and double quotes escaped."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps_str(s: str) -> str:
    """`s` as a PowerShell single-quoted string literal, where a quote is escaped by doubling it."""
    return "'" + s.replace("'", "''") + "'"


def notify(title: str, body: str = "", icon: str | Path | None = None) -> bool:
    """Show a desktop notification, best effort. Returns False when this system has no way to show one. The dashboard
    shows its own toast as well, so a missing notification loses nothing. `icon` is used on Linux only."""
    title, body = (title or "")[:120], (body or "")[:300]  # notifications only show a few lines anyway
    if IS_LINUX and shutil.which("notify-send"):
        # notify-send comes with libnotify, which most Linux desktops include. -a names the app in the notification.
        cmd = ["notify-send", "-a", "JobPortal"] + (["-i", str(icon)] if icon else []) + [title, body]
        return _spawn(cmd)
    if IS_MAC and shutil.which("osascript"):
        # osascript runs AppleScript, which every Mac has built in.
        return _spawn(["osascript", "-e", f"display notification {_applescript_str(body)} with title {_applescript_str(title)}"])
    if IS_WIN:
        # A Windows toast through the built-in WinRT API, run by PowerShell. Windows only shows toasts from a registered
        # app id. JobPortal has none, so the toast is sent under PowerShell's own id, which every Windows 10 and 11 has
        # (the GUID at its start is Windows' id for the System32 folder).
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f"$n = $t.GetElementsByTagName('text'); $n.Item(0).InnerText = {_ps_str(title)}; $n.Item(1).InnerText = {_ps_str(body)};"
            "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        return _spawn(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    return False


def _env_file(name: str) -> str | None:
    """The path in environment variable `name`, when it names a file that exists."""
    path = os.environ.get(name)
    return path if path and Path(path).is_file() else None


def _first_existing(paths) -> str | None:
    """The first of `paths` that is an existing file, as a string, or None."""
    for p in paths:
        if p and Path(p).is_file():
            return str(p)
    return None


def _win_dirs() -> list[str]:
    """Where Windows programs are installed: Program Files, Program Files (x86), and the user's own AppData\\Local (where
    Chrome goes when it's installed for one user only)."""
    return [d for d in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")) if d]


def find_chrome() -> str | None:
    """An installed Chromium-based browser that can print resumes to PDF: Chrome, Edge, Chromium or Brave. Returns its
    path, or None. Set JOBPORTAL_CHROME to a browser's program file to choose one yourself."""
    chosen = _env_file("JOBPORTAL_CHROME")
    if chosen:
        return chosen
    # Linux installs browsers on the PATH under one of these names. The PATH is checked on every system, though, since
    # some Windows and Mac setups have a browser there too.
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                 "microsoft-edge", "microsoft-edge-stable", "msedge", "brave-browser", "brave"):
        p = shutil.which(name)
        if p:
            return p
    if IS_MAC:
        # Mac browsers are app bundles that are never on the PATH. The program sits inside the bundle, in Contents/MacOS.
        # Apps live in /Applications, or in ~/Applications when installed for one user.
        apps = ["Google Chrome.app/Contents/MacOS/Google Chrome", "Chromium.app/Contents/MacOS/Chromium",
                "Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Brave Browser.app/Contents/MacOS/Brave Browser"]
        return _first_existing(Path(root) / a for root in ("/Applications", Path.home() / "Applications") for a in apps)
    if IS_WIN:
        # Windows browsers aren't on the PATH either. Look in each install folder, in order of browser preference.
        rel = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
               r"Chromium\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return _first_existing(Path(d) / r for r in rel for d in _win_dirs())
    return None


def bundled_pdf_engine() -> str | None:
    """The Chrome Headless Shell shipped inside the packaged app (packaging/fetch_pdf_engine.py puts it there), or None.

    The macOS and Linux releases include it. The Windows release doesn't, because Windows always has Edge. When running
    from source there is no bundled engine, so this returns None."""
    if not getattr(sys, "frozen", False):  # PyInstaller sets sys.frozen in the packaged app
        return None
    exe_dir = Path(sys.executable).resolve().parent
    name = "chrome-headless-shell.exe" if IS_WIN else "chrome-headless-shell"
    # A Linux build (or a Windows build, if one ever bundles it) keeps the engine in pdf-engine/ next to the program.
    # A macOS app runs from JobPortal.app/Contents/MacOS but keeps the engine in Contents/Resources/pdf-engine.
    for folder in (exe_dir / "pdf-engine", exe_dir.parent / "Resources" / "pdf-engine"):
        if (folder / name).is_file():
            if IS_MAC:
                _clear_quarantine(folder)
            return str(folder / name)
    return None


@functools.cache  # once per folder per run is enough
def _clear_quarantine(folder: Path) -> None:
    """Remove macOS's quarantine flag from the bundled engine.

    macOS marks every file in a downloaded app with a quarantine flag. When the user approves JobPortal, that covers the
    app, but the engine is a separate program inside it, so Gatekeeper could still block it on the first PDF export.
    `xattr -dr` deletes the flag from the folder and everything in it. Failure is ignored: the export then shows its own
    error."""
    try:
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(folder)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def find_pdf_engine() -> str | None:
    """The program that prints resumes to PDF, or None when there is none. In order: JOBPORTAL_CHROME when it names an
    existing file, then the engine bundled with the app, then an installed Chrome, Edge, Chromium or Brave."""
    return _env_file("JOBPORTAL_CHROME") or bundled_pdf_engine() or find_chrome()


def find_soffice() -> str | None:
    """LibreOffice's program, used only to read old .doc, .pages and .wps resumes, or None. LibreOffice is optional. Set
    JOBPORTAL_SOFFICE to its program file to choose one yourself."""
    chosen = _env_file("JOBPORTAL_SOFFICE")
    if chosen:
        return chosen
    for name in ("soffice", "libreoffice"):  # the PATH names on Linux (and on other systems where it was added)
        p = shutil.which(name)
        if p:
            return p
    if IS_MAC:
        return _first_existing(["/Applications/LibreOffice.app/Contents/MacOS/soffice"])
    if IS_WIN:
        return _first_existing(Path(d) / r"LibreOffice\program\soffice.exe" for d in _win_dirs())
    return None
