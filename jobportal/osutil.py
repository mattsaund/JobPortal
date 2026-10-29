"""Everything that differs between Windows, macOS and Linux: opening files and links, desktop notifications,
finding Chrome / Edge / Chromium (PDF export) and LibreOffice (old .doc files), and launching Claude Code."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def os_name() -> str:
    return "windows" if IS_WIN else "macos" if IS_MAC else "linux" if IS_LINUX else sys.platform


def popen_flags() -> dict:
    """Keyword arguments that stop helper processes from flashing a console window on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def _spawn(cmd: list[str]) -> bool:
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_flags())
        return True
    except OSError:
        return False


def open_path(target: str | Path) -> bool:
    """Open a file or folder with the system's default app (Explorer, Finder, the Linux file manager)."""
    target = str(target)
    if IS_WIN:
        try:
            os.startfile(target)  # noqa: S606 (Windows only)
            return True
        except OSError:
            return False
    return _spawn(["open" if IS_MAC else "xdg-open", target])


def open_url(url: str) -> bool:
    """Open an http(s) or mailto link in the default browser or mail app."""
    return open_path(url)


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def notify(title: str, body: str = "", icon: str | Path | None = None) -> bool:
    """Best-effort desktop notification. The dashboard always shows its own toast as well."""
    title, body = (title or "")[:120], (body or "")[:300]
    if IS_LINUX and shutil.which("notify-send"):
        cmd = ["notify-send", "-a", "JobPortal"] + (["-i", str(icon)] if icon else []) + [title, body]
        return _spawn(cmd)
    if IS_MAC and shutil.which("osascript"):
        return _spawn(["osascript", "-e", f"display notification {_applescript_str(body)} with title {_applescript_str(title)}"])
    if IS_WIN:
        # A Windows toast through the built-in WinRT API, sent under PowerShell's own app id (registered on every Windows 10/11).
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f"$n = $t.GetElementsByTagName('text'); $n.Item(0).InnerText = {_ps_str(title)}; $n.Item(1).InnerText = {_ps_str(body)};"
            "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        return _spawn(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    return False


def _first_existing(paths) -> str | None:
    for p in paths:
        if p and Path(p).is_file():
            return str(p)
    return None


def _win_dirs() -> list[str]:
    return [d for d in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")) if d]


def find_chrome() -> str | None:
    """A Chromium-based browser for printing resumes to PDF: Chrome, Edge, Chromium or Brave.
    Set JOBPORTAL_CHROME to the browser's executable to choose one yourself."""
    env = os.environ.get("JOBPORTAL_CHROME")
    if env and Path(env).is_file():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                 "microsoft-edge", "microsoft-edge-stable", "msedge", "brave-browser", "brave"):
        p = shutil.which(name)
        if p:
            return p
    if IS_MAC:
        apps = ["Google Chrome.app/Contents/MacOS/Google Chrome", "Chromium.app/Contents/MacOS/Chromium",
                "Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Brave Browser.app/Contents/MacOS/Brave Browser"]
        return _first_existing(Path(root) / a for root in ("/Applications", Path.home() / "Applications") for a in apps)
    if IS_WIN:
        rel = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
               r"Chromium\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return _first_existing(Path(d) / r for r in rel for d in _win_dirs())
    return None


def find_soffice() -> str | None:
    """LibreOffice, used only to read old .doc / .pages / .wps resumes. Optional."""
    env = os.environ.get("JOBPORTAL_SOFFICE")
    if env and Path(env).is_file():
        return env
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    if IS_MAC:
        return _first_existing(["/Applications/LibreOffice.app/Contents/MacOS/soffice"])
    if IS_WIN:
        return _first_existing(Path(d) / r"LibreOffice\program\soffice.exe" for d in _win_dirs())
    return None


def find_claude(setting: str = "claude") -> str | None:
    """Path to the Claude Code CLI (`claude`), looking where its installers put it on each OS."""
    setting = (setting or "claude").strip()
    if Path(setting).is_file():
        return setting
    p = shutil.which(setting)
    if p:
        return p
    home = Path.home()
    exe = "claude.exe" if IS_WIN else "claude"
    candidates = [home / ".local" / "bin" / exe, home / ".claude" / "local" / exe]
    if IS_WIN:
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm" / "claude.cmd")
    else:
        candidates += [Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude"), home / ".npm-global" / "bin" / "claude"]
    return _first_existing(candidates)


def claude_command(setting: str = "claude") -> list[str]:
    """The argv prefix that starts Claude Code. On Windows an npm install is a .cmd shim, and cmd.exe would mangle the
    JSON arguments we pass, so the shim is bypassed and node runs Claude Code's entry script directly."""
    path = find_claude(setting) or setting or "claude"
    if IS_WIN and path.lower().endswith((".cmd", ".bat")):
        cli = Path(path).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        node = shutil.which("node")
        if cli.is_file() and node:
            return [node, str(cli)]
    return [path]
