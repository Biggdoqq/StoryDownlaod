"""
build_admin.py — PyInstaller Builder for KVN License Admin Panel (ADMIN ONLY)
Builds the Admin GUI as a standalone tool for the administrator.
DO NOT DISTRIBUTE THIS FILE OR ITS OUTPUT TO GUESTS/CLIENTS!
"""

import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "KVNAdminPanel"
MAIN = os.path.join(ROOT, "admin_panel.py")
ICON = os.path.join(ROOT, "icon.ico")
CRED_FILE = os.path.join(ROOT, "kvn_credentials.json")
LICENSE_FILE = os.path.join(ROOT, "license_client.py")

DIST_DIR = os.path.join(ROOT, "dist_admin")
BUILD_DIR = os.path.join(ROOT, "build_admin")

PYTHON = sys.executable
_SEP = ";" if sys.platform == "win32" else ":"

print("=" * 60)
print("  Building KVN Admin Panel (.exe) [ADMIN TOOL ONLY]")
print("=" * 60)

for folder in [BUILD_DIR]:
    if os.path.exists(folder):
        print(f"  Cleaning {folder}...")
        try:
            shutil.rmtree(folder)
        except Exception:
            pass

args = [
    PYTHON, "-m", "PyInstaller",
    "--name", APP_NAME,
    "--distpath", DIST_DIR,
    "--workpath", BUILD_DIR,
    "--specpath", ROOT,
    "--windowed",
    "--noconsole",
    "--onedir",
    *(["--icon", ICON] if os.path.exists(ICON) else []),
    *(["--add-data", f"{ICON}{_SEP}."] if os.path.exists(ICON) else []),
    *(["--add-data", f"{CRED_FILE}{_SEP}."] if os.path.exists(CRED_FILE) else []),
    *(["--add-data", f"{LICENSE_FILE}{_SEP}."] if os.path.exists(LICENSE_FILE) else []),
    "--hidden-import", "PyQt6",
    "--hidden-import", "PyQt6.QtCore",
    "--hidden-import", "PyQt6.QtGui",
    "--hidden-import", "PyQt6.QtWidgets",
    "--hidden-import", "gspread",
    "--hidden-import", "google.auth",
    "--hidden-import", "google.oauth2",
    "--hidden-import", "google.oauth2.service_account",
    "--hidden-import", "google.auth.transport.requests",
    "--hidden-import", "license_client",
    "--hidden-import", "cryptography",
    "--hidden-import", "hmac",
    "--hidden-import", "hashlib",
    "--collect-all", "PyQt6",
    "--exclude-module", "PyQt5",
    "--exclude-module", "tkinter",
    "--noupx",
    "--log-level", "INFO",
    MAIN
]

print(f"  Entry  : {MAIN}")
print(f"  Output : {os.path.join(DIST_DIR, APP_NAME)}")
print()

result = subprocess.run(args, cwd=ROOT)

if result.returncode == 0:
    exe = os.path.join(DIST_DIR, APP_NAME, f"{APP_NAME}.exe")
    for extra in ["license_client.py", "kvn_credentials.json", "icon.ico"]:
        src = os.path.join(ROOT, extra)
        dst = os.path.join(DIST_DIR, APP_NAME, extra)
        if os.path.exists(src):
            try:
                shutil.copy(src, dst)
            except Exception:
                pass

    if os.path.exists(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        print("=" * 60)
        print(f"  [SUCCESS] Admin Panel Build complete!")
        print(f"  Location: {exe}")
        print(f"  Size: {size_mb:.1f} MB")
        print("=" * 60)
