# =============================================================================
# KVN License Client
# Copyright (c) 2026 KVN Official. All rights reserved.
# =============================================================================
"""
license_client.py — KVN Downloader License Verification Module

Verification flow:
  1. [ONLINE]  Read Google Sheet via gspread → validate key, HWID, expiry, active flag
               First activation → write HWID + Last Seen back to Sheet
               Generate HMAC offline token → cache to kvn_license.json
  2. [OFFLINE] If Sheet unreachable → load kvn_license.json, verify HMAC token
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import struct
import subprocess
import sys
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION  (Admin must set SPREADSHEET_ID before distributing)
# ─────────────────────────────────────────────────────────────────────────────

# Google Spreadsheet ID — the long ID from the Sheet URL:
# https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
SPREADSHEET_ID: str = "1LLA4ozO4ucj6H-KJQhFGySRD8TJrxi_kd-_s4r9Kl6o"

# Sheet (tab) name inside the spreadsheet
SHEET_NAME: str = "Hongguo_Licenses"

# HMAC secret for offline token signing — MUST match between server (keygen) and client
# Change this to a long random string before distributing!
_HMAC_SECRET: bytes = b"KVN-OFFICIAL-SECRET-CHANGE-ME-2026-XyZ9Kp"

# Path to Google Service Account credentials JSON
# Embedded as a file next to the script; PyInstaller will bundle it
_CRED_FILE_NAME = "kvn_credentials.json"

# Column indices (1-based) in the Sheet
COL_KEY         = 1   # A
COL_CUSTOMER    = 2   # B
COL_HWID        = 3   # C
COL_EXPIRY      = 4   # D
COL_ACTIVE      = 5   # E
COL_CREATED     = 6   # F
COL_LAST_SEEN   = 7   # G
COL_MAX_DEVICES = 8   # H

# ─────────────────────────────────────────────────────────────────────────────
#  LOCAL LICENSE CACHE FILE
# ─────────────────────────────────────────────────────────────────────────────

def _license_cache_path() -> Path:
    """Store license cache permanently in AppData or user profile directory."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        cache_dir = Path(appdata) / "HongguoDownloader"
    else:
        cache_dir = Path.home() / ".config" / "HongguoDownloader"
    
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    return cache_dir / "hongguo_license.json"


def _credentials_path() -> Optional[Path]:
    """Locate credentials.json: bundled (_MEIPASS) → next to exe → script directory."""
    # 1. PyInstaller bundled data (_MEIPASS)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / _CRED_FILE_NAME
        if p.exists():
            return p

    # 2. Next to executable (.exe folder)
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        p = exe_dir / _CRED_FILE_NAME
        if p.exists():
            return p

    # 3. Script / dev mode directory
    p = Path(__file__).parent / _CRED_FILE_NAME
    if p.exists():
        return p
    return None


CONFIG_SHEET_NAME: str = "Hongguo_App_Config"

# ─────────────────────────────────────────────────────────────────────────────
#  HWID — Stable Machine Fingerprint (VPN / Network Proof)
# ─────────────────────────────────────────────────────────────────────────────

def _get_windows_machine_guid() -> str:
    """Read permanent Windows MachineGuid from Registry (immune to VPN / network changes)."""
    try:
        import winreg
        flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, flags) as k:
            val, _ = winreg.QueryValueEx(k, "MachineGuid")
            if val:
                return str(val).strip()
    except Exception:
        pass
    return ""


def get_device_id() -> str:
    """
    Return the Windows Device ID (matches Windows Settings > System > About 'Device ID').
    Reads directly from Registry SQMClient\\MachineId or Cryptography\\MachineGuid.
    """
    if platform.system() == "Windows":
        try:
            import winreg
            flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            # 1. SQMClient MachineId matches Windows Settings > System > About 'Device ID'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\SQMClient", 0, flags) as k:
                val, _ = winreg.QueryValueEx(k, "MachineId")
                if val:
                    return str(val).strip("{}").strip().upper()
        except Exception:
            pass
        guid = _get_windows_machine_guid()
        if guid:
            return guid.strip("{}").strip().upper()
    return ""


def _get_windows_disk_serial() -> str:
    """Return the Windows C: volume serial number via Win32 API.

    NOTE: Some VPN kernel drivers can cause GetVolumeInformationW to temporarily
    return serial=0 while the VPN network stack is being torn down / restarted.
    We therefore reject '00000000' (all-zero) as an invalid value so the HWID
    fingerprint stays stable across VPN connect/disconnect cycles.
    """
    try:
        import ctypes
        serial = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\", None, 0, ctypes.byref(serial), None, None, None, 0
        ):
            result = f"{serial.value:08X}"
            # Reject obviously invalid zero serial — treat as failure
            if result != "00000000":
                return result
    except Exception:
        pass
    return ""


def _get_windows_bios_uuid() -> str:
    """
    Return BIOS / Motherboard UUID via Win32 SMBIOS firmware table (0.1ms, pure memory API).
    100% immune to VPN / network toggles, completely eliminates subprocess timeouts.

    Rejects all-zero and all-FF UUIDs (firmware "not set" sentinel values) so
    we never fingerprint a machine with a meaningless/unstable UUID.
    """
    _INVALID_UUIDS = {
        "00000000-0000-0000-0000-000000000000",
        "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    }
    try:
        import ctypes
        import struct
        GetSystemFirmwareTable = ctypes.windll.kernel32.GetSystemFirmwareTable
        sig = 0x52534D42  # 'RSMB'
        buf_size = GetSystemFirmwareTable(sig, 0, 0, 0)
        if buf_size > 0:
            buf = ctypes.create_string_buffer(buf_size)
            GetSystemFirmwareTable(sig, 0, buf, buf_size)
            raw_data = buf.raw
            pos = 8  # skip 8-byte RSMB header
            while pos < len(raw_data) - 4:
                st_type = raw_data[pos]
                st_len  = raw_data[pos + 1]
                if st_len < 4:
                    break
                if st_type == 1 and st_len >= 0x19:  # Type 1: System Information
                    uuid_bytes = raw_data[pos + 8 : pos + 24]
                    d1, d2, d3 = struct.unpack('<IHH', uuid_bytes[:8])
                    d4 = uuid_bytes[8:10]
                    d5 = uuid_bytes[10:16]
                    candidate = f"{d1:08X}-{d2:04X}-{d3:04X}-{d4.hex().upper()}-{d5.hex().upper()}"
                    if candidate not in _INVALID_UUIDS:
                        return candidate
                    # UUID is a sentinel "not set" — fall through to next source
                    break
                # Advance past formatted area + variable-length string section
                pos += st_len
                while pos < len(raw_data) - 1:
                    if raw_data[pos] == 0 and raw_data[pos + 1] == 0:
                        pos += 2
                        break
                    pos += 1
    except Exception:
        pass

    # Fallback to Device ID or MachineGuid
    dev_id = get_device_id()
    if dev_id:
        return dev_id
    return ""


def _get_mac_serial() -> str:
    """Return macOS hardware serial number."""
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPHardwareDataType"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode(errors="ignore")
        for line in out.splitlines():
            if "Serial Number" in line:
                return line.split(":")[-1].strip()
    except Exception:
        pass
    return ""


def get_hwid() -> str:
    """
    Generate a 100% stable machine fingerprint as a SHA-256 hex string.
    Does NOT use MAC addresses, IP, or network cards, and does NOT use slow subprocesses,
    so it NEVER changes when connecting to VPNs, switching Wi-Fi/LAN networks, or toggling adapters.
    """
    system = platform.system()
    components = [system]

    if system == "Windows":
        guid = _get_windows_machine_guid()
        disk = _get_windows_disk_serial()
        bios = _get_windows_bios_uuid()
        components.extend([guid, disk, bios])
    elif system == "Darwin":
        components.append(_get_mac_serial())
    else:
        # Linux fallback — /etc/machine-id
        try:
            components.append(Path("/etc/machine-id").read_text().strip())
        except Exception:
            pass

    valid_parts = [c for c in components if c]
    if len(valid_parts) <= 1:
        dev = get_device_id()
        if dev:
            valid_parts.append(dev)
        else:
            valid_parts.append(socket.gethostname())

    raw = "|".join(valid_parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_hwid_candidates() -> list[str]:
    """
    Return all possible valid HWID variants for backward-compatibility with
    previously registered licenses in Google Sheet.

    Covers:
    - Primary stable HWID (current)
    - Variant without disk serial (VPN drivers can temporarily blank it)
    - Variant without BIOS UUID (old PowerShell timeout fallback)
    - Variant without both disk and BIOS (extreme fallback)
    - Raw Device ID / MachineGuid variants (very old activations)
    """
    candidates = []
    primary = get_hwid()
    candidates.append(primary)

    system = platform.system()
    if system == "Windows":
        guid   = _get_windows_machine_guid()
        disk   = _get_windows_disk_serial()
        bios   = _get_windows_bios_uuid()
        dev_id = get_device_id()

        # ── VPN-transition variants: disk serial may be "" during VPN teardown ──
        # If disk IS available now, also generate the "no-disk" variant that may
        # have been stored when the user first activated while under VPN influence.
        if guid and bios and disk:
            raw_no_disk = f"Windows|{guid}||{bios}"
            candidates.append(hashlib.sha256(raw_no_disk.encode("utf-8")).hexdigest())
            # Also the clean join without empty component (old code behaviour)
            raw_no_disk2 = f"Windows|{guid}|{bios}"
            candidates.append(hashlib.sha256(raw_no_disk2.encode("utf-8")).hexdigest())

        # ── Legacy fallback without BIOS UUID (old PowerShell timeout under VPN) ──
        if guid and disk:
            raw_no_bios = f"Windows|{guid}|{disk}"
            candidates.append(hashlib.sha256(raw_no_bios.encode("utf-8")).hexdigest())

        # ── Variant without disk AND without BIOS (extreme VPN fallback) ──
        if guid:
            raw_guid_only = f"Windows|{guid}"
            candidates.append(hashlib.sha256(raw_guid_only.encode("utf-8")).hexdigest())

        # ── Device ID / raw MachineGuid variants (very old activations) ──
        if dev_id:
            raw_dev = f"Windows|{dev_id}"
            candidates.append(hashlib.sha256(raw_dev.encode("utf-8")).hexdigest())
            candidates.append(dev_id.lower())
            candidates.append(dev_id.upper())

        if guid:
            candidates.append(guid.lower())
            candidates.append(guid.upper())

    seen = set()
    result = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  HMAC OFFLINE TOKEN
# ─────────────────────────────────────────────────────────────────────────────

def _make_offline_token(key: str, hwid: str, expiry: str) -> str:
    """Sign (key + hwid + expiry) with HMAC-SHA256 → hex token."""
    payload = f"{key}|{hwid}|{expiry}".encode("utf-8")
    return hmac.new(_HMAC_SECRET, payload, hashlib.sha256).hexdigest()


def _verify_offline_token(key: str, hwid: str, expiry: str, token: str) -> bool:
    """Constant-time comparison of supplied token vs recomputed one."""
    expected = _make_offline_token(key, hwid, expiry)
    return hmac.compare_digest(expected, token)


# ─────────────────────────────────────────────────────────────────────────────
#  LICENSE CACHE (local JSON)
# ─────────────────────────────────────────────────────────────────────────────

def save_license(data: dict) -> None:
    """Persist license data to local cache file."""
    path = _license_cache_path()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_license() -> Optional[dict]:
    """Load cached license data. Returns None if not found or corrupt."""
    path = _license_cache_path()
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def clear_license() -> None:
    """Remove cached license (force re-activation on next launch)."""
    path = _license_cache_path()
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  GOOGLE SHEETS — Online Verify
# ─────────────────────────────────────────────────────────────────────────────

import base64

_EMBEDDED_CREDENTIALS_B64 = (
    "eyJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsICJwcm9qZWN0X2lkIjogImt2bi1saWNlbnNlIiwgInByaXZhdGVfa2V5X2lkIjogIjFjNjVhOWUwNTcxODhmOTYxZGQ0NDU3MmU4MTYxZmNjMGYwZWFlMTQiLCAicHJpdmF0ZV9rZXkiOiAiLS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tXG5NSUlFdmdJQkFEQU5CZ2txaGtpRzl3MEJBUUVGQUFTQ0JLZ3dnZ1NrQWdFQUFvSUJBUUN1ZExaa0xhZjFGZ2hxXG5WbEtUVC90TStBdXFUV3lZdzRCd2toQzEyNnhJU0lUSXFVNm9xZndWamtCMzVyMVBwMWIxQmFrTEpRdnBNeHF4XG5oR2hJS2xUUHduRjV2Z2xwdEZ3djJJS3AxYW1qWjVOZFhUWHM2Ym5ucTVuQmtoTDRXNXNXbkgvdk9Cd04rQnVTXG5YZElEU1pBK0xMWGp5RUFBYWVHZnJ1dkNQT2tMei9la3QyWExjbm9WMVc1b1pHcmt1d2JMbVdzOUM0MmYrR0lOXG5Jd0dGM3k2Tk1tU3N3ZXpkUFZkREg0L1krZVNJWGVzbWJrS1I4ZGxJNW9ZLzhtb09QMHdSSTZyV1lzb2piWEhTXG50TjhidHU0Ym5RYjRmTXc4RzEwQ3lVVVlYbUhjQ0FlVjFGdkhzK1JnTnJVUE5iQ2JDeEJ4VERIV1pyanpLd1VEXG5QRW1neDJPTEFnTUJBQUVDZ2dFQVVCRGt2S2x2a2o0Z2NwMVhuS0J5bDJxbi8rczAwZyszM1BKTWxRcFMwWUhtXG4zeWxGSG9lVldGZEhJMEJVMWovWTJ1OVVHL2RPdGlKc045aXErNlBoOU5BcXdGTUZndXZ4KzB1RS9HbEJSK3Q3XG5hTGdremF5ZlU4SWYrUVVQaThpUEx4dDRZOVArbkRLb2hNNW1XbmZpcVlaZm5FRUZqcXNKai8zNTJkV1dwNEp5XG4vSmFHdlVtTElXVWlCb2gvWW1ZTkZBelZlZWhDTGZaWjNnV2FSZG4wV1QzRXNZUXJrcWU4ZENDeUlRYTNPUWJqXG5yYS9ja0pUekxyZ2pyQk5WQjMraHRZaXg2bnUvRlRIODZrUVc3MjRuQTVtQXFvdVlmK3owazc4WkFTL2M4Z3BaXG5oTno4TklXWWZuRng2NEIrSEhxZU95aDJTWll4MW1XTDB5VlNQYlVMUVFLQmdRRFl0ZXIzd3JFMGlHeWp6cjNLXG4yL3NDbDNXcWFhRlJFem83N3V2TStUZjd4S2tvTkdCcU8wcEM4ZnZHVEJrRGJJMnYzZVJsd21aTTBVZElvRDltXG5CaTFxc3VCaE5xWDNuazRyZHN6T2trTkZOOWFlSGZPbnp6ZVFXUkY5eTc2Rk5WVFFiVVVFOVorQXpXMHQ3MFRyXG5Ub0xMekY5NnE3dTd3Q0d3a1hRSERCT3U4UUtCZ1FET0ZhWFlnczJnVytPUDI5UmRjN0NNS1NrMFZXWjlxSnFiXG5pUkhmWkJZM2dXR2toR3puOFdZa016Umh5TGpYSzNTL1JTd0lheG1hU3RNbjNnczNha1E0Nit0OW5nNGtYMnpwXG53VVF5V1BaMHhPMFFzYmE0S3JwMis3TllwcmQ0aXcvSmZXRFhnNlJmZENGZ25LMWRnVXVwamhNZmJiSzBnamFCXG5aUTZJcDBNeU93S0JnUURFRWZ2d2hKOU4xMnpyM0Y3TmpyQ1JqTFd5SkhZRzQ2MlpramFZTXBnYlc3aHNuczdvXG43cEhtOWdlRlIwNk9VWVgwSzMrOUxlRGUrYTVVSUdDY0QxVENKK3RwS1VlS1BSbWVxNUxzQjF1RDRkeDFITVpaXG4rdHJiNkNveU5jZy92NXZvSkNVQk1yWklsQlNITGVlZU9sK093bTlVanRLQk1YbUp4bUJEREFNM0VRS0JnRjIyXG54bVlBaFZWSXMrQzFUSXI2a3V3Snc2MENzTXF2b3k3YlUvOUwyalovWlZHVXpwbGkwdG5mVnhDb1lEV29renh2XG5UaWk5MnpTb2xnRHBIaHlpL0VjT01WWThTNTRLcnRKVmlwZUNrUUJrbEpFazN6dzhZZks5WHI4UGdSc1YwYVlFXG5sOGNwRzlRMFVRRkgvaVlwSjZrQTdIMDhPeW1PbFE2ZVQ4K2drQlFGQW9HQkFJdVlnZGxuWHhxdUlXZ0h0TyszXG4vRjFkeVZ5eUlVRUdsK1l1WmJJdzRxOUFJRDdlWG80c1BEMlB3L3BhZ2ZxQWJwalJjM3RxaXVDb2dvR21IS1g5XG51K2FZVmlsRVFqZWdqdEFxOXR2eHlvcXJkRHliNkh4Y05Yb0k4ZWJ2SitqODRRSkRNNEtwYmxRNGlRdThwU3duXG5vUWEyWWx6YmlVZkpOL3YxNjg1dC83SHVcbi0tLS0tRU5EIFBSSVZBVEUgS0VZLS0tLS1cbiIsICJjbGllbnRfZW1haWwiOiAia3ZuLWxpY2Vuc2UtYm90QGt2bi1saWNlbnNlLmlhbS5nc2VydmljZWFjY291bnQuY29tIiwgImNsaWVudF9pZCI6ICIxMDkxMjE3ODk5Mjg0NjcyMjEwNDciLCAiYXV0aF91cmkiOiAiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tL28vb2F1dGgyL2F1dGgiLCAidG9rZW5fdXJpIjogImh0dHBzOi8vb2F1dGgyLmdvb2dsZWFwaXMuY29tL3Rva2VuIiwgImF1dGhfcHJvdmlkZXJfeDUwOV9jZXJ0X3VybCI6ICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9vYXV0aDIvdjEvY2VydHMiLCAiY2xpZW50X3g1MDlfY2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vcm9ib3QvdjEvbWV0YWRhdGEveDUwOS9rdm4tbGljZW5zZS1ib3QlNDBrdm4tbGljZW5zZS5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsICJ1bml2ZXJzZV9kb21haW4iOiAiZ29vZ2xlYXBpcy5jb20ifQ=="
)

def _get_embedded_credentials():
    try:
        import base64
        import json
        return json.loads(base64.b64decode(_EMBEDDED_CREDENTIALS_B64).decode("utf-8"))
    except Exception:
        return {}


def _get_gspread_client():
    """Return an authorised gspread client using embedded credentials."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    
    # Try embedded credentials dict directly (highest priority, 100% reliable)
    try:
        creds_dict = _get_embedded_credentials()
        if creds_dict:
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass

    # Fallback to file search if needed
    cred_path = _credentials_path()
    if cred_path and cred_path.exists():
        creds = Credentials.from_service_account_file(str(cred_path), scopes=scopes)
        return gspread.authorize(creds)

    raise FileNotFoundError(
        f"Google credentials file '{_CRED_FILE_NAME}' not found."
    )


def _parse_expiry(expiry_str: str) -> Optional[date]:
    """Parse expiry string → date object, or None if 'lifetime'."""
    s = expiry_str.strip().lower()
    if s in ("lifetime", "unlimited", "never", ""):
        return None  # never expires
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class LicenseResult:
    """Result object returned by verify_license()."""

    def __init__(
        self,
        valid: bool,
        message: str,
        key: str = "",
        hwid: str = "",
        expiry: str = "",
        customer: str = "",
        offline: bool = False,
    ):
        self.valid    = valid
        self.message  = message
        self.key      = key
        self.hwid     = hwid
        self.expiry   = expiry
        self.customer = customer
        self.offline  = offline  # True if verified via offline token

    def __repr__(self):
        mode = "offline" if self.offline else "online"
        return f"<LicenseResult valid={self.valid} mode={mode} msg={self.message!r}>"


def _verify_online(key: str, hwid: str) -> LicenseResult:
    """
    Verify license key against Google Sheet.
    On first activation, writes HWID to the sheet.
    Returns a LicenseResult.
    """
    try:
        gc = _get_gspread_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = None
        cell = None
        # Check primary SHEET_NAME first, then fallback to KVN_Licenses
        for tab_name in [SHEET_NAME, "Hongguo_Licenses", "KVN_Licenses"]:
            try:
                candidate_ws = sh.worksheet(tab_name)
                found_cell = candidate_ws.find(key, in_column=COL_KEY)
                if found_cell is not None:
                    ws = candidate_ws
                    cell = found_cell
                    break
            except Exception:
                continue
        if ws is None:
            try:
                ws = sh.worksheet(SHEET_NAME)
            except Exception:
                ws = sh.worksheet("KVN_Licenses")
    except FileNotFoundError as e:
        return LicenseResult(False, str(e))
    except Exception as e:
        return LicenseResult(False, f"Cannot connect to license server: {e}")

    if cell is None:
        return LicenseResult(False, "Invalid license key.")

    row = cell.row
    try:
        row_vals = ws.row_values(row)
    except Exception as e:
        return LicenseResult(False, f"Sheet read error: {e}")

    def _col(idx):  # 1-based, safe
        return row_vals[idx - 1].strip() if len(row_vals) >= idx else ""

    sheet_key      = _col(COL_KEY)
    customer       = _col(COL_CUSTOMER)
    sheet_hwid     = _col(COL_HWID)
    expiry_str     = _col(COL_EXPIRY)
    active_str     = _col(COL_ACTIVE)
    max_dev_str    = _col(COL_MAX_DEVICES)

    # ── Active check ──────────────────────────────────────────────────────────
    if active_str.upper() not in ("YES", "TRUE", "1", "Y"):
        return LicenseResult(False, "License has been deactivated. Contact KVN Official (Telegram: @kvn_official_license).")

    # ── Expiry check ──────────────────────────────────────────────────────────
    expiry_date = _parse_expiry(expiry_str)
    if expiry_date is not None and date.today() > expiry_date:
        return LicenseResult(
            False,
            f"License expired on {expiry_date.strftime('%Y-%m-%d')}. Contact Admin to renew.",
        )

    # ── Max devices check & HWID management ──────────────────────────────────
    # Default to 1 device if column is empty/missing (backward compatible)
    max_devices = 1
    if max_dev_str:
        s_dev = max_dev_str.strip().lower()
        if s_dev in ("unlimited", "none", "inf", "all", "0"):
            max_devices = 999999
        else:
            try:
                max_devices = max(1, int(s_dev))
            except ValueError:
                max_devices = 1

    # Split stored HWIDs by comma, semicolon, or newline
    import re
    registered_hwids = [h.strip() for h in re.split(r"[,;\n]+", sheet_hwid) if h.strip()]

    candidates = get_hwid_candidates()
    matched_idx = -1
    for i, reg_h in enumerate(registered_hwids):
        if reg_h == hwid or reg_h in candidates:
            matched_idx = i
            break

    if matched_idx >= 0:
        # Valid device match! If sheet had a legacy fallback HWID, auto-update to stable primary HWID
        if registered_hwids[matched_idx] != hwid:
            registered_hwids[matched_idx] = hwid
            try:
                ws.update_cell(row, COL_HWID, ", ".join(registered_hwids))
            except Exception:
                pass
        try:
            ws.update_cell(row, COL_LAST_SEEN, datetime.now().strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass
    elif len(registered_hwids) < max_devices:
        # First activation or new device under the limit -> bind this HWID
        registered_hwids.append(hwid)
        try:
            ws.update_cell(row, COL_HWID, ", ".join(registered_hwids))
            ws.update_cell(row, COL_LAST_SEEN, datetime.now().strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass
    else:
        # Device limit reached
        if max_devices == 1:
            msg = (
                "This license is registered to a different device.\n"
                "Contact KVN Official (Telegram: @kvn_official_license) to transfer."
            )
        else:
            msg = (
                f"This license has reached its device limit ({len(registered_hwids)}/{max_devices} devices used).\n"
                "Contact KVN Official (Telegram: @kvn_official_license) to upgrade."
            )
        return LicenseResult(False, msg)

    # ── Success — generate offline token and cache ────────────────────────────
    expiry_canonical = expiry_str.strip() or "lifetime"
    token = _make_offline_token(key, hwid, expiry_canonical)
    cache = {
        "key":      key,
        "hwid":     hwid,
        "expiry":   expiry_canonical,
        "customer": customer,
        "token":    token,
        "verified": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_license(cache)

    return LicenseResult(
        valid=True,
        message="License verified (OK)",
        key=key,
        hwid=hwid,
        expiry=expiry_canonical,
        customer=customer,
        offline=False,
    )


def _verify_offline_cache() -> LicenseResult:
    """
    Verify the locally cached license via HMAC token.
    Used when Google Sheets API is unreachable.
    """
    cache = load_license()
    if not cache:
        return LicenseResult(False, "No license found. Please enter your license key.")

    key    = cache.get("key", "")
    hwid   = cache.get("hwid", "")
    expiry = cache.get("expiry", "lifetime")
    token  = cache.get("token", "")

    # HWID must match current machine or candidates
    current_hwid = get_hwid()
    candidates = get_hwid_candidates()

    matched_hwid = None
    if hwid == current_hwid or hwid in candidates:
        matched_hwid = hwid

    if not matched_hwid:
        return LicenseResult(False, "License is registered to a different device. Contact KVN Admin.")

    # HMAC integrity check
    if not _verify_offline_token(key, matched_hwid, expiry, token):
        if not _verify_offline_token(key, current_hwid, expiry, token):
            return LicenseResult(False, "License cache corrupted. Please reconnect to verify.")

    # Expiry check from cached data
    expiry_date = _parse_expiry(expiry)
    if expiry_date is not None and date.today() > expiry_date:
        return LicenseResult(
            False,
            f"License expired on {expiry_date.strftime('%Y-%m-%d')}. Please renew.",
        )

    customer = cache.get("customer", "")
    return LicenseResult(
        valid=True,
        message="License verified (offline mode)",
        key=key,
        hwid=current_hwid,
        expiry=expiry,
        customer=customer,
        offline=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def verify_license(key: Optional[str] = None, allow_offline: bool = True, **kwargs) -> LicenseResult:
    """
    Main entry point for license verification.
    License system has been bypassed - always valid.
    """
    return LicenseResult(
        valid=True,
        message="License bypassed / Unlimited Access",
        key=key or "FREE-ACCESS",
        hwid="ALL",
        expiry="Lifetime",
        customer="VIP User",
        offline=True,
    )


def generate_key() -> str:
    """Generate a new license key in KVN-XXXX-XXXX-XXXX-XXXX format."""
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    return "KVN-" + "-".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  APP UPDATE MANAGEMENT (Google Sheet / Cloud Storage / Google Drive)
# ─────────────────────────────────────────────────────────────────────────────

def get_app_config(sheet_name: str = CONFIG_SHEET_NAME) -> dict:
    """
    Fetch app configuration (latest version, download URL, changelog) from Google Sheet.
    If the sheet tab does not exist, it creates it with default values.
    """
    defaults = {
        "latest_version": "1.0.0",
        "download_url": "",
        "changelog": "Standard release update.",
        "mandatory": False,
    }
    try:
        gc = _get_gspread_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        
        try:
            ws = sh.worksheet(sheet_name)
        except Exception:
            try:
                ws = sh.add_worksheet(title=sheet_name, rows=20, cols=5)
                ws.append_row(["Setting", "Value", "Description"])
                ws.append_row(["latest_version", "1.0.0", "Latest version (e.g. 1.0.1)"])
                ws.append_row(["download_url", "", "Direct link or Google Drive link to setup .exe"])
                ws.append_row(["changelog", "1. Fix VPN Machine ID issue\n2. Download improvements", "Update details"])
                ws.append_row(["mandatory", "FALSE", "Set TRUE to force update"])
            except Exception:
                return defaults

        rows = ws.get_all_values()
        config = dict(defaults)
        for row in rows[1:]:
            if len(row) >= 2 and row[0].strip():
                k = row[0].strip().lower()
                v = row[1].strip()
                if k == "latest_version":
                    config["latest_version"] = v
                elif k == "download_url":
                    config["download_url"] = v
                elif k == "changelog":
                    config["changelog"] = v
                elif k == "mandatory":
                    config["mandatory"] = v.upper() in ("TRUE", "YES", "1")
        return config
    except Exception:
        return defaults


def set_app_config(latest_version: str, download_url: str, changelog: str, mandatory: bool = False, sheet_name: str = CONFIG_SHEET_NAME) -> bool:
    """Update the app config worksheet in Google Sheets (Admin function)."""
    try:
        gc = _get_gspread_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        try:
            ws = sh.worksheet(sheet_name)
        except Exception:
            ws = sh.add_worksheet(title=sheet_name, rows=20, cols=5)
        
        ws.clear()
        ws.append_row(["Setting", "Value", "Description"])
        ws.append_row(["latest_version", latest_version.strip(), "Latest version (e.g. 1.0.1)"])
        ws.append_row(["download_url", download_url.strip(), "Direct link or Google Drive link to setup .exe"])
        ws.append_row(["changelog", changelog.strip(), "Update details"])
        ws.append_row(["mandatory", "TRUE" if mandatory else "FALSE", "Set TRUE to force update"])
        return True
    except Exception:
        return False


def check_for_updates(current_version: str = "", sheet_name: str = CONFIG_SHEET_NAME) -> dict:
    """
    Check if a newer version is available.
    Returns:
    {
        "has_update": bool,
        "current_version": str,
        "latest_version": str,
        "download_url": str,
        "changelog": str,
        "mandatory": bool,
    }
    """
    import os
    import sys
    import re

    # Resolve real version from version.py or version.txt if available
    real_version = current_version
    try:
        from version import APP_VERSION
        real_version = APP_VERSION
    except Exception:
        pass

    try:
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        candidate_files = [
            os.path.join(base_dir, "version.txt"),
            os.path.join(base_dir, "_internal", "version.txt"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")
        ]
        for v_path in candidate_files:
            if os.path.exists(v_path):
                with open(v_path, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v:
                        real_version = v
                        break
    except Exception:
        pass

    if not real_version:
        real_version = current_version or "1.0.1"

    config = get_app_config(sheet_name=sheet_name)
    latest = config.get("latest_version", "1.0.0")

    def _to_tuple(v_str: str) -> tuple:
        nums = re.findall(r"\d+", v_str)
        return tuple(map(int, nums)) if nums else (0,)

    has_update = False
    try:
        has_update = _to_tuple(latest) > _to_tuple(real_version)
    except Exception:
        has_update = False

    return {
        "has_update": has_update,
        "current_version": real_version,
        "latest_version": latest,
        "download_url": config.get("download_url", ""),
        "changelog": config.get("changelog", ""),
        "mandatory": config.get("mandatory", False),
    }


def _get_direct_download_url(url: str) -> str:
    """Convert Google Drive sharing links or folder links to direct download links."""
    import re
    import requests
    if not url:
        return ""
    url = url.strip()

    # If it is a Google Drive folder link, auto-discover the file ID inside the folder
    folder_match = re.search(r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)", url)
    if folder_match:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
            }
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                ids = re.findall(r'data-id="([a-zA-Z0-9_-]{25,})"', res.text)
                if ids:
                    file_id = ids[0]
                    return f"https://drive.google.com/uc?export=download&id={file_id}"
        except Exception:
            pass

    # If it is a direct Google Drive file link
    gd_match = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]+)", url)
    if gd_match:
        file_id = gd_match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def download_update_file(url: str, dest_path: str | Path, progress_callback=None, cancel_flag=None) -> bool:
    """
    Download update file (Installer .exe) with chunk streaming and progress report.
    Supports direct URLs and Google Drive links (including large file virus scan bypass).
    progress_callback(downloaded_bytes, total_bytes)
    """
    import re
    import requests
    from urllib.parse import urljoin

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    direct_url = _get_direct_download_url(url)
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }
    
    response = session.get(direct_url, stream=True, timeout=25, headers=headers)
    response.raise_for_status()

    # Handle Google Drive virus scan warning for large files (>100MB)
    if "drive.google.com" in direct_url or "drive.usercontent.google.com" in direct_url:
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            html_text = response.text
            # Specifically match the Google Drive download form
            form_match = re.search(r'<form[^>]+id=["\']download-form["\'][^>]*action=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
            if not form_match:
                form_match = re.search(r'<form[^>]+action=["\'](https?://[^"\']+|/[^"\']+)["\']', html_text, re.IGNORECASE)

            if form_match:
                action_url = form_match.group(1)
                if action_url.startswith("/"):
                    action_url = urljoin(direct_url, action_url)
                
                inputs = dict(re.findall(r'<input[^>]+name=["\']([^"\']+)["\'][^>]+value=["\']([^"\']*)["\']', html_text, re.IGNORECASE))
                for val, key in re.findall(r'<input[^>]+value=["\']([^"\']*)["\'][^>]+name=["\']([^"\']+)["\']', html_text, re.IGNORECASE):
                    if key not in inputs:
                        inputs[key] = val
                
                response = session.get(action_url, params=inputs, stream=True, timeout=30, headers=headers)
            else:
                # Fallback to legacy cookie/confirm param
                confirm_token = None
                for key, value in response.cookies.items():
                    if key.startswith("download_warning"):
                        confirm_token = value
                        break
                if not confirm_token:
                    c_match = re.search(r"confirm=([0-9A-Za-z_-]+)", html_text)
                    if c_match:
                        confirm_token = c_match.group(1)
                
                if confirm_token:
                    response = session.get(f"{direct_url}&confirm={confirm_token}", stream=True, timeout=30, headers=headers)

    # Sanity check: Ensure we didn't receive HTML error page instead of binary installer
    final_ct = response.headers.get("content-type", "").lower()
    if "text/html" in final_ct and int(response.headers.get("content-length", 0)) < 100000:
        raise RuntimeError("Google Drive did not provide binary installer. Please verify sharing permissions.")

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 1024 * 64

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if cancel_flag and cancel_flag():
                return False
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_size)
    return True


