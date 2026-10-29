"""Entry point for the packaged JobPortal app (PyInstaller)."""
import multiprocessing
import os
import sys


def _log_streams() -> None:
    """A windowed app has no console. Send output to a log file instead of crashing on the first print."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from platformdirs import user_cache_dir
    home = os.environ.get("JOBPORTAL_HOME")
    folder = os.path.join(home, "cache") if home else user_cache_dir("JobPortal", appauthor=False)
    os.makedirs(folder, exist_ok=True)
    log = open(os.path.join(folder, "app.log"), "a", encoding="utf-8", buffering=1)  # noqa: SIM115 (lives as long as the app)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def _system_libraries() -> None:
    """On Linux the bundle points LD_LIBRARY_PATH at its own libraries. Programs JobPortal starts (the browser, Chrome for
    PDFs, LibreOffice) need the system's, so restore the original value. This process already loaded what it needs."""
    if not sys.platform.startswith("linux"):
        return
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _log_streams()
    _system_libraries()
    from jobportal.app.cli import main
    sys.exit(main())
