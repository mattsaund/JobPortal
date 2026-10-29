"""Command line entry point: `jobportal` once installed, or `python -m jobportal` from the repo.

  jobportal               open the app in its own window (falls back to your browser)
  jobportal --browser     open the dashboard in your default browser instead
  jobportal --server      run only the server in this terminal (Ctrl+C stops it)
  jobportal --background  run only the server, detached; the app attaches to it
  jobportal --stop        stop a server started with --server or --background
  jobportal --doctor      check that everything JobPortal needs is installed"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobportal", description="JobPortal: import your resume, answer the standard job questions, "
                                "and it hunts for jobs and prepares every application.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open the dashboard in your default browser instead of a window")
    mode.add_argument("--server", action="store_true", help="run only the server in this terminal")
    mode.add_argument("--background", action="store_true", help="run only the server, detached from this terminal")
    mode.add_argument("--stop", action="store_true", help="stop a running server")
    mode.add_argument("--doctor", action="store_true", help="check Python, Claude Code, the PDF browser and the window toolkit")
    p.add_argument("--port", type=int, help="port for the local server (default 8788, or JOBPORTAL_PORT)")
    p.add_argument("--data-dir", help="keep the database and files here instead of the default app-data folder (or JOBPORTAL_HOME)")
    p.add_argument("--version", action="version", version=f"JobPortal {__version__}")
    return p


def _pid_file() -> Path:
    from .config import CACHE, PORT
    return CACHE / f"server-{PORT}.pid"


def serve() -> int:
    import uvicorn
    from .config import CACHE, HOST, PORT
    CACHE.mkdir(parents=True, exist_ok=True)
    pid = _pid_file()
    pid.write_text(str(os.getpid()), encoding="utf-8")
    print(f"JobPortal server on http://{HOST}:{PORT} (Ctrl+C stops it)")
    try:
        uvicorn.run("jobportal.main:app", host=HOST, port=PORT, log_level="warning", timeout_graceful_shutdown=5)
    finally:
        pid.unlink(missing_ok=True)
    return 0


def background() -> int:
    from . import osutil
    from .config import CACHE, HOST, PORT
    from .desktop import up
    url = f"http://{HOST}:{PORT}"
    if up():
        print(f"Already running at {url}")
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    log = open(CACHE / "server.log", "ab")  # noqa: SIM115 (handed to the child process)
    kw: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if osutil.IS_WIN:
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "jobportal", "--server", "--port", str(PORT)], env=dict(os.environ), **kw)
    for _ in range(60):
        if up():
            print(f"JobPortal server running at {url} (log: {CACHE / 'server.log'})")
            return 0
        time.sleep(0.25)
    print(f"The server didn't come up. See {CACHE / 'server.log'}")
    return 1


def stop() -> int:
    from .desktop import up
    pid_path = _pid_file()
    if not pid_path.exists():
        print("Not running." if not up() else "A server is running, but it wasn't started with --server or --background, so close it there.")
        return 0
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError, OSError):
        pid_path.unlink(missing_ok=True)
        print("Not running.")
        return 0
    for _ in range(60):
        if not up():
            break
        time.sleep(0.25)
    else:
        if hasattr(signal, "SIGKILL"):
            os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print(f"Stopped (pid {pid}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # These must be set before anything imports jobportal.config, which reads them once.
    if args.data_dir:
        os.environ["JOBPORTAL_HOME"] = str(Path(args.data_dir).expanduser().resolve())
    if args.port:
        os.environ["JOBPORTAL_PORT"] = str(args.port)
    if args.doctor:
        from .doctor import run
        return run()
    if args.stop:
        return stop()
    if args.background:
        return background()
    if args.server:
        return serve()
    from .desktop import main as desktop_main
    desktop_main(browser=args.browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
