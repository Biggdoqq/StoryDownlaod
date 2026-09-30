"""
build_installer.py — Complete All-in-One Build Automation
1. Runs PyInstaller (build.py) to compile HongguoDownloader.exe
2. Runs Inno Setup Compiler (ISCC.exe) to produce HongguoDownloader-Setup.exe
"""

import os
import sys
import subprocess
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
ISCC_CANDIDATES = [
    r"C:\Program Files\Inno Setup 7\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Inno Setup 6\ISCC.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Inno Setup 7\ISCC.exe"),
]

def find_iscc() -> str:
    for path in ISCC_CANDIDATES:
        if os.path.exists(path):
            return path
    which = shutil.which("ISCC")
    if which:
        return which
    return ""

def main():
    print("=" * 65)
    print("  HONGGUO DOWNLOADER — ALL-IN-ONE INSTALLER BUILDER")
    print("=" * 65)

    iscc_path = find_iscc()
    if not iscc_path:
        print("[ERROR] Inno Setup compiler (ISCC.exe) not found!")
        sys.exit(1)
    print(f"[*] Found Inno Setup Compiler: {iscc_path}")

    # Step 1: Run PyInstaller
    print("\n[STEP 1/2] Compiling Python Application with PyInstaller...")
    build_py = os.path.join(ROOT, "build.py")
    res1 = subprocess.run([sys.executable, build_py], cwd=ROOT)
    if res1.returncode != 0:
        print("[FAILED] PyInstaller build failed!")
        sys.exit(res1.returncode)

    # Check dist/HongguoDownloader/HongguoDownloader.exe
    app_exe = os.path.join(ROOT, "dist", "HongguoDownloader", "HongguoDownloader.exe")
    if not os.path.exists(app_exe):
        print(f"[ERROR] Expected output missing: {app_exe}")
        sys.exit(1)

    # Step 2: Sync Version and Run Inno Setup
    print("\n[STEP 2/2] Compiling Inno Setup Installer...")
    try:
        from version import APP_VERSION
        iss_file = os.path.join(ROOT, "installer.iss")
        with open(iss_file, "r", encoding="utf-8") as f:
            iss_text = f.read()
        import re
        iss_text = re.sub(r'#define\s+MyAppVersion\s+"[^"]*"', f'#define MyAppVersion "{APP_VERSION}"', iss_text)
        with open(iss_file, "w", encoding="utf-8") as f:
            f.write(iss_text)
        print(f"[*] Synced installer.iss MyAppVersion to {APP_VERSION}")
    except Exception as e:
        print(f"[!] Warning syncing version: {e}")

    iss_file = os.path.join(ROOT, "installer.iss")
    res2 = subprocess.run([iscc_path, iss_file], cwd=ROOT)
    if res2.returncode != 0:
        print("[FAILED] Inno Setup compilation failed!")
        sys.exit(res2.returncode)

    setup_exe = os.path.join(ROOT, "dist", "HongguoDownloader-Setup.exe")
    if os.path.exists(setup_exe):
        size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
        print("\n" + "=" * 65)
        print("  [SUCCESS] ALL-IN-ONE INSTALLER CREATED SUCCESSFULLY!")
        print(f"  Installer: {setup_exe}")
        print(f"  File Size: {size_mb:.1f} MB")
        print("=" * 65)

        root_setup = os.path.join(ROOT, "HongguoDownloader-Setup.exe")
        try:
            shutil.copy2(setup_exe, root_setup)
            print(f"[*] Copied setup to root: {root_setup}")
        except Exception as e:
            print(f"[!] Warning copying to root: {e}")
    else:
        print("[WARNING] Build finished but setup file not found at expected path.")

if __name__ == "__main__":
    main()
