"""
Application Version Configuration for Hongguo Downloader.
Central single source of truth for application versioning.
"""

import os
import sys

APP_VERSION = "1.0.7"

# Optionally allow reading version from version.txt next to executable or script
try:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    ver_file = os.path.join(base_dir, "version.txt")
    if os.path.exists(ver_file):
        with open(ver_file, "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                APP_VERSION = v
except Exception:
    pass
