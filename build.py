"""
build.py — Automated PyInstaller Builder for Hongguo Downloader
Packages the application into a standalone Windows .exe with Google Sheet License Manager.
"""

import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "HongguoDownloader"
MAIN = os.path.join(ROOT, "main.py")
ICON = os.path.join(ROOT, "icon.ico")
ICON_PNG = os.path.join(ROOT, "icon.png")
CRED_FILE = os.path.join(ROOT, "kvn_credentials.json")
LICENSE_FILE = os.path.join(ROOT, "license_client.py")
VERSION_FILE = os.path.join(ROOT, "version.py")
VERSION_TXT = os.path.join(ROOT, "version.txt")

DIST_DIR = os.path.join(ROOT, "dist")
BUILD_DIR = os.path.join(ROOT, "build")

PYTHON = sys.executable
_SEP = ";" if sys.platform == "win32" else ":"

print("=" * 60)
print("  Building Hongguo Downloader (.exe)")
print("=" * 60)

# Clean previous build artifacts
for folder in [BUILD_DIR, os.path.join(DIST_DIR, APP_NAME)]:
    if os.path.exists(folder):
        print(f"  Cleaning {folder}...")
        try:
            shutil.rmtree(folder)
        except Exception:
            pass

spec_file = os.path.join(ROOT, f"{APP_NAME}.spec")
if os.path.exists(spec_file):
    try:
        os.remove(spec_file)
    except Exception:
        pass

args = [
    PYTHON, "-m", "PyInstaller",
    "--noconfirm",

    # Output
    "--name", APP_NAME,
    "--distpath", DIST_DIR,
    "--workpath", BUILD_DIR,
    "--specpath", ROOT,

    # GUI window (no black cmd box)
    "--windowed",
    "--noconsole",

    # One folder mode (fastest, most reliable, avoids antivirus false positives)
    "--onedir",

    # Icon
    *(["--icon", ICON] if os.path.exists(ICON) else []),

    # Data files
    *(["--add-data", f"{ICON}{_SEP}."] if os.path.exists(ICON) else []),
    *(["--add-data", f"{ICON_PNG}{_SEP}."] if os.path.exists(ICON_PNG) else []),
    *(["--add-data", f"{CRED_FILE}{_SEP}."] if os.path.exists(CRED_FILE) else []),
    *(["--add-data", f"{LICENSE_FILE}{_SEP}."] if os.path.exists(LICENSE_FILE) else []),
    *(["--add-data", f"{VERSION_FILE}{_SEP}."] if os.path.exists(VERSION_FILE) else []),
    *(["--add-data", f"{VERSION_TXT}{_SEP}."] if os.path.exists(VERSION_TXT) else []),

    # Hidden imports
    "--hidden-import", "version",
    "--hidden-import", "PyQt6",
    "--hidden-import", "PyQt6.QtCore",
    "--hidden-import", "PyQt6.QtGui",
    "--hidden-import", "PyQt6.QtWidgets",
    "--hidden-import", "PyQt6.QtMultimedia",
    "--hidden-import", "PyQt6.QtMultimediaWidgets",
    "--hidden-import", "gspread",
    "--hidden-import", "google.auth",
    "--hidden-import", "google.oauth2",
    "--hidden-import", "google.oauth2.service_account",
    "--hidden-import", "google.auth.transport.requests",
    "--hidden-import", "license_client",
    "--hidden-import", "activation_dialog",
    "--hidden-import", "update_dialog",
    "--hidden-import", "github_updater",
    "--hidden-import", "safe_thread",
    "--hidden-import", "download_dialog",
    "--hidden-import", "merge_dialog",
    "--hidden-import", "player",
    "--hidden-import", "downloader",
    "--hidden-import", "api",
    "--hidden-import", "database",
    "--hidden-import", "styles",
    "--hidden-import", "requests",
    "--hidden-import", "urllib3",
    "--hidden-import", "sqlite3",
    "--hidden-import", "cryptography",
    "--hidden-import", "hmac",
    "--hidden-import", "hashlib",

    # Collect Qt packages
    "--collect-all", "PyQt6",

    # Exclude heavy unnecessary modules, PyQt5 and admin_panel
    "--exclude-module", "admin_panel",
    "--exclude-module", "PyQt5",
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "--exclude-module", "numpy",
    "--exclude-module", "scipy",
    "--exclude-module", "pandas",
    "--exclude-module", "PIL",
    "--exclude-module", "pytest",

    # Disable UPX to prevent memory errors
    "--noupx",

    "--log-level", "INFO",
    MAIN
]

print(f"  Python : {PYTHON}")
print(f"  Entry  : {MAIN}")
print(f"  Output : {os.path.join(DIST_DIR, APP_NAME)}")
print()

result = subprocess.run(args, cwd=ROOT)

print()
if result.returncode == 0:
    exe = os.path.join(DIST_DIR, APP_NAME, f"{APP_NAME}.exe")
    # Do not copy loose source/icon files to dist root - they are already safely inside _internal
    # This keeps the application root folder clean with just HongguoDownloader.exe and _internal

    if os.path.exists(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        print("=" * 60)
        print(f"  [SUCCESS] Build complete!")
        print(f"  Location: {exe}")
        print(f"  Size: {size_mb:.1f} MB")
        print("=" * 60)
    else:
        print(f"  [SUCCESS] Build finished in {os.path.join(DIST_DIR, APP_NAME)}")
else:
    print(f"  [FAILED] PyInstaller exited with code {result.returncode}")
    sys.exit(result.returncode)
