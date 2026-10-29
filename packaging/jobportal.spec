# PyInstaller spec for the JobPortal app. From the repo root: pyinstaller --noconfirm packaging/jobportal.spec
# macOS gets JobPortal.app. Windows and Linux get a JobPortal folder, which CI wraps in an installer or an AppImage.
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
APP = "JobPortal"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "jobportal" / "__init__.py").read_text(encoding="utf-8")).group(1)
ICON = str(ROOT / "packaging" / "icons" / {"win32": "jobportal.ico", "darwin": "jobportal.icns"}.get(sys.platform, "jobportal.png"))

datas = [(str(ROOT / "jobportal" / "static"), "jobportal/static"), (str(ROOT / "jobportal" / "resources"), "jobportal/resources")]
binaries = []
hiddenimports = collect_submodules("jobportal") + collect_submodules("uvicorn")
d, b, h = collect_all("webview")
datas += d
binaries += b
hiddenimports += h

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "ruff"])
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP, console=False, icon=ICON, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=APP, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{APP}.app", icon=ICON, bundle_identifier="io.github.mattsaund.jobportal",
                 info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION, "NSHighResolutionCapable": True,
                             "LSApplicationCategoryType": "public.app-category.productivity"})
