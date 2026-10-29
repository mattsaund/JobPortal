"""Command line entry point: `jobportal` once installed, `python -m jobportal` from the repo, or the packaged app itself
(packaging/entry.py calls main()).

  jobportal               open the app in its own window (falls back to your browser)
  jobportal --browser     open the dashboard in your default browser instead
  jobportal --server      run only the server in this terminal (Ctrl+C stops it)
  jobportal --background  run only the server, detached; the app attaches to it
  jobportal --stop        stop a server started with --server or --background
  jobportal --doctor      check that everything JobPortal needs is installed

--port and --data-dir work with every mode. They become the JOBPORTAL_PORT and JOBPORTAL_HOME environment variables, which
jobportal.core.config reads once, the first time anything imports it. That is why this module imports the rest of
JobPortal inside its functions, after main() has set those variables.

The server modes keep a PID file (the server's process number) in the cache folder, so --stop knows what to stop."""
import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from jobportal import __version__


def build_parser() -> argparse.ArgumentParser:
    """The command line options. The modes exclude each other; --port and --data-dir go with any of them."""
    p = argparse.ArgumentParser(prog="jobportal", description="JobPortal: import your resume, answer the standard job questions, "
                                "and it hunts for jobs and prepares every application.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open the dashboard in your default browser instead of a window")
    mode.add_argument("--server", action="store_true", help="run only the server in this terminal")
    mode.add_argument("--background", action="store_true", help="run only the server, detached from this terminal")
    mode.add_argument("--stop", action="store_true", help="stop a running server")
    mode.add_argument("--doctor", action="store_true", help="check Python, the ChatGPT sign-in, the PDF browser and the window toolkit")
    p.add_argument("--port", type=int, help="port for the local server (default 8788, or JOBPORTAL_PORT)")
    p.add_argument("--data-dir", help="keep the database and files here instead of the default app-data folder (or JOBPORTAL_HOME)")
    p.add_argument("--version", action="version", version=f"JobPortal {__version__}")
    return p


def _pid_file() -> Path:
    """Where the server modes record their process number: one file per data folder and port."""
    from jobportal.core.config import CACHE, PORT
    return CACHE / f"server-{PORT}.pid"


def serve() -> int:
    """--server: run the server in this process until Ctrl+C, --stop or the dashboard's Quit button. Writes the PID file
    while it runs."""
    from jobportal.app.desktop import make_server
    from jobportal.core.config import CACHE, HOST, PORT
    CACHE.mkdir(parents=True, exist_ok=True)
    pid = _pid_file()
    pid.write_text(str(os.getpid()), encoding="utf-8")
    print(f"JobPortal server on http://{HOST}:{PORT} (Ctrl+C stops it)")
    try:
        make_server().run()  # uvicorn shuts down cleanly on Ctrl+C or SIGTERM
    finally:
        pid.unlink(missing_ok=True)
    return 0


def _self_command() -> list[str]:
    """How to start JobPortal again: the packaged executable itself, or this Python running the package."""
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "jobportal"]


def background() -> int:
    """--background: start `jobportal --server` as a detached process that outlives this terminal, with its output appended
    to server.log in the cache folder. Waits up to 15 seconds for it to answer."""
    from jobportal.app.desktop import up
    from jobportal.core import osutil
    from jobportal.core.config import CACHE, HOST, PORT
    url = f"http://{HOST}:{PORT}"
    if up():
        print(f"Already running at {url}")
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    log_path = CACHE / "server.log"
    options: dict = {"stdin": subprocess.DEVNULL}
    if osutil.IS_WIN:
        # No console window, and a process group of its own so a Ctrl+C in this terminal doesn't reach it.
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True  # a session of its own, so closing the terminal doesn't stop it
    # The child inherits the environment, including JOBPORTAL_HOME from --data-dir. It gets its own copy of the log file
    # handle, so this process can close its copy right away.
    with open(log_path, "ab") as log:
        subprocess.Popen([*_self_command(), "--server", "--port", str(PORT)], stdout=log, stderr=log, **options)
    for _ in range(60):
        if up():
            print(f"JobPortal server running at {url} (log: {log_path})")
            return 0
        time.sleep(0.25)
    print(f"The server didn't come up. See {log_path}")
    return 1


def stop() -> int:
    """--stop: end the server that --server or --background started for this data folder and port. Asks it to shut down
    (SIGTERM, which on Windows ends the process at once), waits up to 15 seconds, then forces it."""
    from jobportal.app.desktop import up
    pid_path = _pid_file()
    if not up():
        # Nothing answers, so a PID file here is stale (the server crashed, or the computer restarted). Its number may belong
        # to another program by now, so the file is removed and nothing is signaled.
        pid_path.unlink(missing_ok=True)
        print("Not running.")
        return 0
    if not pid_path.exists():
        print("A server is running, but it wasn't started with --server or --background, so close it there.")
        return 0
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, OSError):  # an unreadable file, or no such process
        pid_path.unlink(missing_ok=True)
        print("Not running.")
        return 0
    for _ in range(60):
        if not up():
            break
        time.sleep(0.25)
    else:
        if hasattr(signal, "SIGKILL"):  # Windows has none, and doesn't need it
            with contextlib.suppress(OSError):  # it may have exited a moment ago
                os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print(f"Stopped (pid {pid}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the chosen mode. Returns the exit code."""
    args = build_parser().parse_args(argv)
    # These must be set before anything imports jobportal.core.config, which reads them once.
    if args.data_dir:
        os.environ["JOBPORTAL_HOME"] = str(Path(args.data_dir).expanduser().resolve())
    if args.port:
        os.environ["JOBPORTAL_PORT"] = str(args.port)
    if args.doctor:
        from jobportal.app.doctor import run
        return run()
    if args.stop:
        return stop()
    if args.background:
        return background()
    if args.server:
        return serve()
    from jobportal.app.desktop import main as desktop_main
    desktop_main(browser=args.browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
