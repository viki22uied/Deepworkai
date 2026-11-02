# PyInstaller recipe for the Deep Work AI app (bundled inside the .lplug4).
# Build:  pyinstaller packaging/DeepWorkAI.spec --distpath build/app --workpath build/work --noconfirm
# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SERVICE = os.path.join(ROOT, "deepworkai", "service")

hidden = collect_submodules("deepworkai", filter=lambda m: ".plugin" not in m)
# The service also imports these by bare module name (service dir on sys.path).
hidden += ["deep_restore_core", "slack_integration", "paths", "chromium_session",
           "ide_context", "secrets_store", "proc_utils", "lcd_state"]
hidden += ["win32gui", "win32con", "win32process", "win32api", "psutil", "requests", "dotenv"]

a = Analysis(
    [os.path.join(ROOT, "deepworkai", "app_main.py")],
    pathex=[ROOT, SERVICE],
    hiddenimports=hidden,
    excludes=[
        # Not used — keeps the download small
        "tkinter", "numpy", "scipy", "sklearn", "pandas", "matplotlib", "IPython", "pytest",
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml", "PyQt6.QtQuick",
        "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtDesigner",
        "PyQt6.QtBluetooth", "PyQt6.QtPositioning", "PyQt6.Qt3DCore", "PyQt6.QtCharts",
        "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets", "PyQt6.QtSvg", "PyQt6.QtXml",
        "cryptography", "OpenSSL", "pdfminer", "PIL.ImageQt",
    ],
    noarchive=False,
)
# Drop Qt pieces the app never loads (translations, image codecs, extra platform shells).
_DROP = ("translations", "imageformats", "wayland", "platformthemes", "platforminputcontexts",
         "generic", "egldeviceintegrations", "xcbglintegrations", "iconengines")
a.datas = [d for d in a.datas if not any(f"/{x}/" in d[0].replace("\\", "/") or d[0].replace("\\", "/").startswith(f"PyQt6/Qt6/{x}") for x in _DROP)]
a.binaries = [b for b in a.binaries if not any(f"plugins/{x}" in b[0].replace("\\", "/") for x in _DROP)
              and not any(n in b[0].lower() for n in ("opengl32sw", "d3dcompiler"))]   # software GL: unused

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="DeepWorkAI",
    console=False,                       # no terminal window, ever
    icon=os.path.join(SPECPATH, "DeepWorkAI.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    upx=False,                           # UPX-packed exes trigger antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="DeepWorkAI", upx=False)
