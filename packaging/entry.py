"""Entry point for the packaged JobPortal app. PyInstaller builds the executable from this file (see jobportal.spec); from
source, `jobportal` and `python -m jobportal` start at jobportal/app/cli.py instead.

Before handing over to the command line it fixes two things that only differ in the packaged app: a windowed program has
no console to print to, and on Linux the bundle's own library path would leak into the programs JobPortal starts.

It must not import jobportal.core.config before cli.main() runs, because config reads JOBPORTAL_HOME once and --data-dir
sets that variable. So _log_streams finds the cache folder the same way config does, by itself."""
import multiprocessing
import os
import sys


def _log_streams() -> None:
    """When the app starts without a console (a windowed app on Windows, for example), sys.stdout and sys.stderr are None
    and the first print would crash. Send output to app.log in the cache folder instead."""
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
    """On Linux, PyInstaller's launcher points LD_LIBRARY_PATH at the bundle's own libraries and keeps the original value
    in LD_LIBRARY_PATH_ORIG (absent when there was none). Programs JobPortal starts (the browser for the app window, the PDF
    engine, LibreOffice, xdg-open) need the system's libraries, so put the original back. This process isn't affected: the
    system loader reads LD_LIBRARY_PATH only once, when a program starts."""
    if not sys.platform.startswith("linux"):
        return
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original


if __name__ == "__main__":
    # multiprocessing starts a child by running the executable again; this makes such a child do its job instead of
    # opening a second JobPortal. A frozen app must call it first.
    multiprocessing.freeze_support()
    _log_streams()
    _system_libraries()
    from jobportal.app.cli import main
    sys.exit(main())
