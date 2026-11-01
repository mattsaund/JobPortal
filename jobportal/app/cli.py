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

The server modes keep a PID file (the server's process number) in the cache folder. It marks a server that --stop may
end; --stop asks that server to quit through its own Quit endpoint rather than signaling the number in the file."""
import argparse
import contextlib
import os
import subprocess
import sys
import time
import urllib.request
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
    while it runs. Returns 1 without touching the PID file when a server already answers on the port, so a second
    --server can't take over (and then delete) the file of the one that's running."""
    from jobportal.app.desktop import make_server, up
    from jobportal.core.config import CACHE, HOST, PORT
    if up():
        print(f"JobPortal is already running at http://{HOST}:{PORT}. Stop it first (jobportal --stop), or pick another --port.")
        return 1
    CACHE.mkdir(parents=True, exist_ok=True)
    pid, me = _pid_file(), str(os.getpid())
    pid.write_text(me, encoding="utf-8")
    print(f"JobPortal server on http://{HOST}:{PORT} (Ctrl+C stops it)")
    try:
        make_server().run()  # uvicorn shuts down cleanly on Ctrl+C or SIGTERM
    finally:
        with contextlib.suppress(OSError):
            if pid.read_text(encoding="utf-8").strip() == me:  # only this server's own file
                pid.unlink()
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


def _request_quit() -> bool:
    """Ask the server on the port to shut itself down through its own Quit endpoint (POST /api/quit). Returns whether it
    agreed. A request from here carries no Origin header, so the server's check against other sites' pages lets it in."""
    from jobportal.app.desktop import BASE
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/quit", data=b"", method="POST"), timeout=5) as reply:
            return reply.status == 200
    except (OSError, ValueError):  # refused (409: a server that can't be stopped this way), or no answer
        return False


def stop() -> int:
    """--stop: end the server that --server or --background started for this data folder and port, the way the dashboard's
    Quit button does, so it shuts down cleanly on every system (a signal ends a Windows process at once). Then the PID
    file goes. Returns 0 when it stopped or nothing was running, 1 when the server is still up.

    The process number in the PID file is never signaled. A file left by a crashed server may name another program by
    now, and the server that answers may not be the one that wrote it, so the number can't be trusted."""
    from jobportal.app.desktop import up
    pid_path = _pid_file()
    if not up():
        pid_path.unlink(missing_ok=True)  # nothing answers, so the file is stale (a crash, or a restart of the computer)
        print("Not running.")
        return 0
    if not pid_path.exists():
        print("A server is running, but it wasn't started with --server or --background, so close it there.")
        return 0
    if not _request_quit():
        print("The server on this port didn't agree to stop. Close it where it runs.")
        return 1
    for _ in range(60):  # up to 15 seconds for a clean shutdown
        if not up():
            pid_path.unlink(missing_ok=True)  # the server removes its own file; this covers one that couldn't
            print("Stopped.")
            return 0
        time.sleep(0.25)
    print("The server is still shutting down. Run --stop again in a moment.")
    return 1


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
