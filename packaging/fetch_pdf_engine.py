"""Download Chrome Headless Shell, the PDF engine bundled into the macOS and Linux apps (Windows always has Edge).

    python packaging/fetch_pdf_engine.py linux64 dist/JobPortal/pdf-engine

It reads Google's Chrome for Testing feed, downloads the current Stable build for one platform (linux64, mac-arm64, mac-x64
or win64) and unpacks it into the destination folder. File permissions and links are kept, so the program stays runnable.
Only the Python standard library is used, so CI can run it before anything else is installed."""
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

FEED = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"


def download_url(platform: str) -> tuple[str, str]:
    """The Stable version number and the zip address for one platform."""
    with urllib.request.urlopen(FEED, timeout=60) as r:
        stable = json.load(r)["channels"]["Stable"]
    for item in stable["downloads"]["chrome-headless-shell"]:
        if item["platform"] == platform:
            return stable["version"], item["url"]
    raise SystemExit(f"No Chrome Headless Shell build for '{platform}'.")


def unpack(archive: Path, dest: Path) -> None:
    """Extract the zip into dest without its top folder (chrome-headless-shell-<platform>/), keeping modes and symlinks.
    zipfile.extractall drops both, which would leave the program unable to run."""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts[1:]
            if not parts or ".." in parts:
                continue
            target = dest.joinpath(*parts)
            mode = info.external_attr >> 16
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                os.symlink(z.read(info).decode(), target)
                continue
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def trim(dest: Path) -> None:
    """Drop what printing never uses: interface translations other than US English (about 50 MB) and Linux package lists.
    Chrome falls back to en-US.pak for any system language, so PDFs still print everywhere."""
    for pak in (dest / "locales").glob("*.pak"):
        if pak.name != "en-US.pak":
            pak.unlink()
    for name in ("deb.deps", "rpm.deps"):
        (dest / name).unlink(missing_ok=True)


def main() -> None:
    """Read the platform and destination folder from the command line (the usage at the top of this file), then replace
    the folder with that platform's current Stable Chrome Headless Shell. Network calls: Google's feed and the download.
    Exits with the usage text when the arguments are wrong."""
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    platform, dest = sys.argv[1], Path(sys.argv[2])
    version, url = download_url(platform)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "engine.zip"
        with urllib.request.urlopen(url, timeout=600) as r, open(archive, "wb") as out:
            shutil.copyfileobj(r, out)
        unpack(archive, dest)
    trim(dest)
    print(f"Chrome Headless Shell {version} ({platform}) is in {dest}")


if __name__ == "__main__":
    main()
