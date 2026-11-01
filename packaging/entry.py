"""Entry point for the packaged JobPortal app. PyInstaller builds the executable from this file (see jobportal.spec); from
source, `jobportal` and `python -m jobportal` start at jobportal/app/cli.py instead.

Before handing over to the command line it fixes two things that only differ in the packaged app: a windowed program has
no console to print to, and on Linux the bundle's own library path would leak into the programs JobPortal starts.

It must not import jobportal.core.config before cli.main() runs, because config reads JOBPORTAL_HOME once and --data-dir
sets that variable. So _log_streams works out the cache folder by itself, with the same rules as config (and cli.main()
for --data-dir)."""
import multiprocessing
import os
import sys
from pathlib import Path


def _data_dir() -> str | None:
    """The data folder from --data-dir on the command line (as "--data-dir PATH" or "--data-dir=PATH"), else from
    JOBPORTAL_HOME, else None. Read by hand, because argparse only runs later, in cli.main()."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--data-dir" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--data-dir="):
            return arg.split("=", 1)[1]
    return os.environ.get("JOBPORTAL_HOME")


def _log_streams() -> None:
    """When the app starts without a console (a windowed app on Windows, for example), sys.stdout and sys.stderr are None
    and the first print would crash. Send output to app.log in the cache folder instead: DATA/cache with a data folder
    given, else the system's cache folder for JobPortal, as config.CACHE has it. When that folder can't be made, output
    is thrown away rather than keeping the app from starting."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from platformdirs import user_cache_dir
    home = _data_dir()
    folder = Path(home).expanduser().resolve() / "cache" if home else Path(user_cache_dir("JobPortal", appauthor=False))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = open(folder / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 (lives as long as the app)
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
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
