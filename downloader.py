"""
Downloader module for Hongguo media, posters, metadata, and files.
Includes QThread workers for smooth background downloads with progress reporting,
and direct integration with the local Hongguo Download Engine (1080p MP4).
"""

import os
import sys
import time
import json
import subprocess
import shutil
import re
import requests
from typing import List, Dict, Any, Optional
from PyQt6.QtCore import QThread, pyqtSignal

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://hongguodownloader.com/",
}

ENGINE_URL = "http://127.0.0.1:8000"
SIGNER_URL = "http://127.0.0.1:9099"

def get_app_dir() -> str:
    """Return the true application directory (parent of _internal if frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


POSSIBLE_ENGINE_PATHS = [
    os.path.join(get_app_dir(), "engine"),
    os.path.join(os.path.dirname(sys.executable), "engine"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"),
    r"C:\Users\Seyhanasa\AppData\Local\Programs\Hongguo Downloader",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Hongguo Downloader"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "HongguoDownloader"),
]


def sanitize_filename(filename: str) -> str:
    """Clean filename of characters invalid on Windows filesystem."""
    invalid_chars = '<>:"/\\|?*\n\r\t'
    for ch in invalid_chars:
        filename = filename.replace(ch, "_")
    return filename.strip()


def is_signer_alive() -> bool:
    """Check if the local unidbg Java signer on port 9099 is responding."""
    try:
        r = requests.post(f"{SIGNER_URL}/sign", json={"url": "ping", "headers": {}}, timeout=1.5)
        return r.status_code in (200, 400, 404, 500)
    except Exception:
        return False


def is_engine_alive() -> bool:
    """Check if the local Hongguo engine on port 8000 is running."""
    try:
        r = requests.get(f"{ENGINE_URL}/dl/status", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def is_engine_busy() -> bool:
    """Check if the local Hongguo engine on port 8000 is currently running an active download."""
    try:
        r = requests.get(f"{ENGINE_URL}/dl/status", timeout=2.0)
        if r.status_code == 200:
            return bool(r.json().get("running", False))
    except Exception:
        pass
    return False


def ensure_engine_running() -> bool:
    """Ensure both the local unidbg Java signer (9099) and engine API (8000) are running."""
    if is_engine_alive() and is_signer_alive():
        return True

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS

    for base_path in POSSIBLE_ENGINE_PATHS:
        if not os.path.exists(base_path):
            continue

        java_exe = os.path.join(base_path, "jre", "bin", "java.exe")
        sign_dir = os.path.join(base_path, "app", "sign")
        sign_jar = os.path.join(sign_dir, "unidbg-sign.jar")
        app_dir = os.path.join(base_path, "app")
        py_exe = os.path.join(base_path, "python", "python.exe")
        if not os.path.exists(py_exe):
            py_exe = os.path.join(base_path, "python", "pythonw.exe")

        # 1. Start Java Signer if not alive
        if not is_signer_alive() and os.path.exists(java_exe) and os.path.exists(sign_jar):
            cmd_java = [
                java_exe,
                "-Xmx1024m",
                "-XX:+ExitOnOutOfMemoryError",
                "--add-opens",
                "java.base/java.lang=ALL-UNNAMED",
                "-cp",
                "unidbg-sign.jar",
                "com.hongguo.sign.FqTrace",
                "serve",
                "9099"
            ]
            try:
                subprocess.Popen(
                    cmd_java,
                    cwd=sign_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
            except Exception:
                pass

            for _ in range(30):
                time.sleep(0.5)
                if is_signer_alive():
                    break

        # 2. Start Python Engine Server if not alive
        if not is_engine_alive() and os.path.exists(py_exe):
            # Ensure apikeys.pyc exists in app_dir
            target_apikeys = os.path.join(app_dir, "apikeys.pyc")
            if not os.path.exists(target_apikeys):
                for candidate in [
                    os.path.join(get_app_dir(), "app", "apikeys.pyc"),
                    os.path.join(base_path, "..", "app", "apikeys.pyc"),
                ]:
                    cand_norm = os.path.normpath(candidate)
                    if os.path.exists(cand_norm):
                        try:
                            shutil.copy2(cand_norm, target_apikeys)
                            break
                        except Exception:
                            pass

            server_script = os.path.join(app_dir, "server.py")
            if not os.path.exists(server_script):
                server_script = os.path.join(app_dir, "server.pyc")

            if os.path.exists(server_script):
                env = os.environ.copy()
                env["PATH"] = os.path.join(base_path, "jre", "bin") + ";" + env.get("PATH", "")
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                env["SIGN_SERVER"] = "http://127.0.0.1:9099"
                env["BIND_HOST"] = "127.0.0.1"
                env["PORT"] = "8000"

                try:
                    subprocess.Popen(
                        [py_exe, server_script],
                        cwd=app_dir,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creationflags
                    )
                except Exception:
                    pass

                for _ in range(20):
                    time.sleep(0.5)
                    if is_engine_alive():
                        break

        if is_engine_alive() and is_signer_alive():
            return True

    return is_engine_alive() and is_signer_alive()


def fetch_series_episodes(series_id: str, ensure_start: bool = True) -> Optional[Dict[str, Any]]:
    """Fetch episode listing directly from local engine."""
    if ensure_start:
        ensure_engine_running()
    try:
        r = requests.get(f"{ENGINE_URL}/dl/episodes?series_id={series_id}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data and "episodes" in data and not data.get("error"):
                return data
    except Exception:
        pass
    return None


class FileDownloadWorker(QThread):
    """Downloads any file from URL to destination with progress updates."""
    progress_signal = pyqtSignal(int, int, float)  # downloaded_bytes, total_bytes, speed_kb_s
    finished_signal = pyqtSignal(bool, str)        # success, message/file_path
    
    def __init__(self, url: str, output_path: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.output_path = output_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
            with requests.get(self.url, headers=HEADERS, stream=True, timeout=20) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                start_time = time.time()
                
                with open(self.output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self._is_cancelled:
                            f.close()
                            if os.path.exists(self.output_path):
                                os.remove(self.output_path)
                            self.finished_signal.emit(False, "Cancelled by user")
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            elapsed = time.time() - start_time
                            speed = (downloaded / 1024) / max(elapsed, 0.001)
                            self.progress_signal.emit(downloaded, total_size, speed)

            self.finished_signal.emit(True, self.output_path)
        except Exception as e:
            self.finished_signal.emit(False, str(e))


_SERIES_COVER_CACHE: Dict[str, str] = {}


def resolve_ultra_hd_cover(cover_url: str, series_id: str = "") -> str:
    """
    Transform thumbnail cover URLs (240x343 or 400x572) into Ultra HD master covers (1039x1484+).
    ByteDance image CDN supports '~noop.image' on 'p3-novel.byteimg.com' to get the full original resolution.
    """
    if not cover_url and not series_id:
        return ""

    cover_url = str(cover_url or "").strip()
    series_id = str(series_id or "").strip()

    # 1. Check if series_id is cached
    if series_id and series_id in _SERIES_COVER_CACHE:
        return _SERIES_COVER_CACHE[series_id]

    # 2. Extract series_id from explorer URL if not provided
    if not series_id and "cover/" in cover_url:
        sm = re.search(r"cover/(\d+)", cover_url)
        if sm:
            series_id = sm.group(1)
            if series_id in _SERIES_COVER_CACHE:
                return _SERIES_COVER_CACHE[series_id]

    # 3. Direct match for ByteDance image hash: novel-pic/<hash>
    m = re.search(r"novel-pic/([a-zA-Z0-9_-]{20,})", cover_url)
    if m:
        hd_url = f"https://p3-novel.byteimg.com/novel-pic/{m.group(1)}~noop.image"
        if series_id:
            _SERIES_COVER_CACHE[series_id] = hd_url
        return hd_url

    # 4. If series_id is available, fetch real ByteDance cover from local engine
    if series_id:
        try:
            info = fetch_series_episodes(series_id, ensure_start=True)
            if info and info.get("cover"):
                m2 = re.search(r"novel-pic/([a-zA-Z0-9_-]{20,})", info["cover"])
                if m2:
                    hd_url = f"https://p3-novel.byteimg.com/novel-pic/{m2.group(1)}~noop.image"
                    _SERIES_COVER_CACHE[series_id] = hd_url
                    return hd_url
        except Exception:
            pass

    # 5. If cover_url has ByteDance template shrink, upgrade to noop.image
    if "~" in cover_url:
        base = cover_url.split("~")[0]
        if "byteimg.com" in base:
            hd_url = f"{base}~noop.image"
            if series_id:
                _SERIES_COVER_CACHE[series_id] = hd_url
            return hd_url

    return cover_url


class BatchPosterDownloadWorker(QThread):
    """Worker for downloading multiple drama poster covers simultaneously in Ultra HD."""
    item_downloaded = pyqtSignal(int, int, str)   # current_index, total_items, filename
    all_finished = pyqtSignal(int, int)           # successful_count, failed_count
    
    def __init__(self, drama_list: List[Dict[str, Any]], target_folder: str, parent=None):
        super().__init__(parent)
        self.drama_list = drama_list
        self.target_folder = target_folder
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        os.makedirs(self.target_folder, exist_ok=True)
        total = len(self.drama_list)
        success = 0
        failed = 0

        for idx, item in enumerate(self.drama_list, start=1):
            if self._is_cancelled:
                break
            
            raw_cover = item.get("cover", "")
            title = item.get("title", f"drama_{item.get('series_id', idx)}")
            safe_title = sanitize_filename(title)
            series_id = str(item.get("series_id", idx))
            filename = f"{safe_title}_{series_id}.jpg"
            save_path = os.path.join(self.target_folder, filename)

            # Resolve Ultra HD cover (1039x1484+)
            cover_url = resolve_ultra_hd_cover(raw_cover, series_id) or raw_cover

            if not cover_url:
                failed += 1
                continue

            try:
                resp = requests.get(cover_url, headers=HEADERS, timeout=15)
                # Fallback to raw cover if HD failed
                if (resp.status_code != 200 or not resp.content) and raw_cover and raw_cover != cover_url:
                    resp = requests.get(raw_cover, headers=HEADERS, timeout=12)

                if resp.status_code == 200 and resp.content:
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
                    success += 1
                    self.item_downloaded.emit(idx, total, filename)
                else:
                    failed += 1
            except Exception:
                failed += 1

        self.all_finished.emit(success, failed)


class DramaSeriesDownloadWorker(QThread):
    """
    In-App Direct Series Episode Downloader.
    Downloads series metadata, cover, and high-definition MP4 episodes (1080p).
    Seamlessly talks to local Hongguo engine with live feedback in Khmer.
    """
    episode_progress = pyqtSignal(int, int, int, float)  # current_ep, total_eps, percent, speed_kb
    status_message = pyqtSignal(str)                     # status update text
    all_finished = pyqtSignal(bool, str)                 # success, folder_path_or_error

    def __init__(
        self,
        drama: Dict[str, Any],
        output_folder: str = "",
        episodes_range: str = "",
        quality: str = "1080p",
        episode_urls: Optional[List[str]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.drama = drama
        self.title = drama.get("title", "Drama")
        self.series_id = str(drama.get("series_id", "0"))
        safe_title = sanitize_filename(self.title)
        out = output_folder.strip() if output_folder else ""
        if not out:
            out = os.path.join(get_app_dir(), "Downloaded_Videos", safe_title)
        else:
            out = os.path.normpath(out)
            if os.path.basename(out) != safe_title:
                out = os.path.join(out, safe_title)
        self.output_folder = out
        self.episodes_range = episodes_range.strip()
        self.quality = quality or "1080p"
        self.episode_urls = episode_urls or []
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        try:
            requests.post(f"{ENGINE_URL}/dl/cancel", timeout=3)
        except Exception:
            pass

    def run(self):
        try:
            os.makedirs(self.output_folder, exist_ok=True)
            self.status_message.emit(f"Preparing output folder: {self.output_folder}")

            # 1. Download Cover / Poster (Ultra HD)
            raw_cover = self.drama.get("cover", "")
            hd_cover = resolve_ultra_hd_cover(raw_cover, self.series_id) or raw_cover
            if hd_cover:
                self.status_message.emit("Downloading Ultra HD poster...")
                try:
                    resp = requests.get(hd_cover, headers=HEADERS, timeout=15)
                    if (resp.status_code != 200 or not resp.content) and raw_cover and raw_cover != hd_cover:
                        resp = requests.get(raw_cover, headers=HEADERS, timeout=12)
                    if resp.status_code == 200 and resp.content:
                        with open(os.path.join(self.output_folder, "poster.jpg"), "wb") as f:
                            f.write(resp.content)
                except Exception:
                    pass

            # 2. Save metadata info.json
            with open(os.path.join(self.output_folder, "info.json"), "w", encoding="utf-8") as f:
                json.dump(self.drama, f, indent=2, ensure_ascii=False)

            # 3. Handle custom direct episode URLs if provided
            if self.episode_urls:
                total_eps = len(self.episode_urls)
                for idx, ep_url in enumerate(self.episode_urls, start=1):
                    if self._is_cancelled:
                        self.status_message.emit("Download cancelled by user")
                        self.all_finished.emit(False, "Cancelled")
                        return

                    ep_filename = f"EP_{idx:02d}.mp4"
                    ep_path = os.path.join(self.output_folder, ep_filename)
                    self.status_message.emit(f"Downloading Episode {idx}/{total_eps}: {ep_filename}...")

                    start_t = time.time()
                    downloaded = 0
                    with requests.get(ep_url, headers=HEADERS, stream=True, timeout=20) as r:
                        r.raise_for_status()
                        total_bytes = int(r.headers.get("content-length", 0))
                        with open(ep_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=65536):
                                if self._is_cancelled:
                                    f.close()
                                    if os.path.exists(ep_path):
                                        os.remove(ep_path)
                                    self.all_finished.emit(False, "Cancelled")
                                    return
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    pct = int((downloaded / total_bytes * 100)) if total_bytes > 0 else 50
                                    speed = (downloaded / 1024) / max(time.time() - start_t, 0.001)
                                    self.episode_progress.emit(idx, total_eps, pct, speed)

                    self.status_message.emit(f"✓ Downloaded Episode {idx}/{total_eps}!")
                
                self.all_finished.emit(True, self.output_folder)
                return

            # 4. Use Engine for direct 1080p short-drama download
            self.status_message.emit("Connecting to Download Engine...")
            engine_ready = ensure_engine_running()
            if not engine_ready:
                self.status_message.emit("Error: Could not start download engine")
                self.all_finished.emit(False, "Could not start local download engine")
                return

            # Set engine output folder to parent folder so engine's {title} subfolder matches self.output_folder
            try:
                parent_dir = os.path.dirname(os.path.abspath(self.output_folder))
                requests.post(f"{ENGINE_URL}/dl/config", json={"output_dir": parent_dir}, timeout=4)
            except Exception:
                pass

            # Fetch series episode total
            total_eps = int(self.drama.get("episode_cnt") or 1)
            ep_info = fetch_series_episodes(self.series_id)
            if ep_info and ep_info.get("total"):
                total_eps = ep_info["total"]

            # Submit download job
            self.status_message.emit(f"Submitting download request for '{self.title}' ({self.quality})...")
            ranges_dict = {}
            if self.episodes_range:
                ranges_dict[self.series_id] = self.episodes_range

            scores_dict = {}
            sc = self.drama.get("score")
            if sc:
                scores_dict[self.series_id] = str(sc)

            payload = {
                "series_ids": [self.series_id],
                "quality": self.quality,
                "concurrency": 2,
                "series_at_once": 1,
                "ranges": ranges_dict,
                "scores": scores_dict
            }

            submit_data = {}
            for attempt in range(45):
                if self._is_cancelled:
                    self.all_finished.emit(False, "Cancelled")
                    return
                try:
                    resp = requests.post(f"{ENGINE_URL}/dl/submit", json=payload, timeout=10)
                    submit_data = resp.json() if resp.status_code == 200 else {}
                except Exception as e:
                    submit_data = {"ok": False, "error": str(e)}

                if submit_data.get("ok"):
                    break

                err_msg = str(submit_data.get("error", ""))
                if "already running" in err_msg.lower():
                    self.status_message.emit("Engine busy with previous download... waiting in queue...")
                    time.sleep(2.0)
                else:
                    self.status_message.emit(f"Engine Error: {err_msg}")
                    self.all_finished.emit(False, err_msg)
                    return
            else:
                if not submit_data.get("ok"):
                    err_msg = submit_data.get("error") or "Timed out waiting for engine to become free"
                    self.status_message.emit(f"Engine Error: {err_msg}")
                    self.all_finished.emit(False, err_msg)
                    return

            # Poll status loop
            self.status_message.emit("Starting 1080p MP4 download...")
            done_eps = 0
            target_eps = total_eps
            if self.episodes_range:
                parts = self.episodes_range.split(",")
                cnt = 0
                for p in parts:
                    if "-" in p:
                        s, e = p.split("-", 1)
                        cnt += max(1, int(e) - int(s) + 1)
                    else:
                        cnt += 1
                target_eps = cnt

            while not self._is_cancelled:
                time.sleep(1.5)
                try:
                    s_resp = requests.get(f"{ENGINE_URL}/dl/status", timeout=4)
                    if s_resp.status_code != 200:
                        continue
                    s_data = s_resp.json()
                    running = s_data.get("running", False)
                    series_list = s_data.get("series", [])
                    logs = s_data.get("log", [])

                    # Find our series in progress
                    found = False
                    for s_item in series_list:
                        if s_item.get("sid") == self.series_id:
                            found = True
                            done_eps = s_item.get("done", 0)
                            tot = s_item.get("total", target_eps) or target_eps
                            target_eps = tot
                            st = s_item.get("status", "")
                            pct = int((done_eps / max(tot, 1)) * 100)
                            self.episode_progress.emit(done_eps, tot, pct, 0.0)
                            self.status_message.emit(f"Downloading Episode {done_eps}/{tot} ({pct}%) [{st}]...")
                            break

                    if not running:
                        # Job is completed
                        if logs:
                            last_log = logs[-1]
                            self.status_message.emit(f"✓ {last_log}")
                        break
                except Exception as e:
                    pass

            if self._is_cancelled:
                self.status_message.emit("Download cancelled")
                self.all_finished.emit(False, "Cancelled")
                return

            # Auto-flatten if engine created a nested subfolder
            if os.path.exists(self.output_folder):
                for item in list(os.listdir(self.output_folder)):
                    sub_p = os.path.join(self.output_folder, item)
                    if os.path.isdir(sub_p):
                        for sub_f in os.listdir(sub_p):
                            src_f = os.path.join(sub_p, sub_f)
                            dst_f = os.path.join(self.output_folder, sub_f)
                            if not os.path.exists(dst_f):
                                shutil.move(src_f, dst_f)
                        try:
                            os.rmdir(sub_p)
                        except Exception:
                            pass

            self.episode_progress.emit(target_eps, target_eps, 100, 0.0)
            self.status_message.emit(f"✓ Downloaded '{self.title}' successfully!")
            self.all_finished.emit(True, self.output_folder)

        except Exception as e:
            self.status_message.emit(f"Unexpected error: {e}")
            self.all_finished.emit(False, str(e))


class BatchSeriesDownloadWorker(QThread):
    """
    Worker to download multiple drama series simultaneously (2, 3, or more dramas at once).
    """
    total_progress = pyqtSignal(int, int, int)              # done_series, total_series, total_pct
    series_progress = pyqtSignal(str, int, int, str)        # series_title, done_eps, total_eps, status
    status_message = pyqtSignal(str)                        # live log message
    all_finished = pyqtSignal(bool, str)                    # success, output_dir_or_error

    def __init__(
        self,
        series_list: List[Dict[str, Any]],
        output_dir: str = "",
        quality: str = "1080p",
        series_at_once: int = 2,
        concurrency: int = 4,
        parent=None
    ):
        super().__init__(parent)
        self.series_list = series_list
        self.output_dir = output_dir or os.path.join(get_app_dir(), "Downloaded_Videos")
        self.quality = quality or "1080p"
        self.series_at_once = max(1, min(series_at_once, 4))
        self.concurrency = max(1, min(concurrency, 6))
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        try:
            requests.post(f"{ENGINE_URL}/dl/cancel", timeout=3)
        except Exception:
            pass

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            ensure_engine_running()

            try:
                requests.post(f"{ENGINE_URL}/dl/config", json={"output_dir": self.output_dir}, timeout=4)
            except Exception:
                pass

            series_ids = [str(d.get("series_id")) for d in self.series_list if d.get("series_id")]
            if not series_ids:
                self.all_finished.emit(False, "No drama IDs found to download")
                return

            total_series_count = len(series_ids)
            self.status_message.emit(f"Submitting download request for {total_series_count} drama(s)...")

            scores_dict = {}
            for d in self.series_list:
                sid = str(d.get("series_id"))
                if d.get("score"):
                    scores_dict[sid] = str(d["score"])

            payload = {
                "series_ids": series_ids,
                "quality": self.quality,
                "concurrency": self.concurrency,
                "series_at_once": self.series_at_once,
                "ranges": {},
                "scores": scores_dict
            }

            resp = requests.post(f"{ENGINE_URL}/dl/submit", json=payload, timeout=12)
            submit_data = resp.json() if resp.status_code == 200 else {}
            if not submit_data.get("ok"):
                err = submit_data.get("error") or submit_data.get("reason") or "Failed to start batch download"
                self.all_finished.emit(False, err)
                return

            self.status_message.emit(f"✓ Started downloading {total_series_count} drama(s) in parallel (Series at once: {self.series_at_once})...")

            # Monitoring loop
            while not self._is_cancelled:
                time.sleep(1.5)
                try:
                    s_resp = requests.get(f"{ENGINE_URL}/dl/status", timeout=4)
                    if s_resp.status_code != 200:
                        continue
                    st = s_resp.json()
                    running = st.get("running", False)
                    series_status_list = st.get("series", [])
                    logs = st.get("log", [])

                    done_series = 0
                    total_eps_all = 0
                    done_eps_all = 0

                    for s in series_status_list:
                        s_title = s.get("title", "Drama")
                        s_done = s.get("done", 0)
                        s_tot = max(1, s.get("total", 1))
                        s_st = s.get("status", "")
                        done_eps_all += s_done
                        total_eps_all += s_tot

                        if s_st == "done" or s_done >= s_tot:
                            done_series += 1

                        self.series_progress.emit(s_title, s_done, s_tot, s_st)

                    total_pct = int(done_eps_all * 100 / max(total_eps_all, 1))
                    self.total_progress.emit(done_series, total_series_count, total_pct)

                    if logs:
                        self.status_message.emit(logs[-1])

                    if not running:
                        break
                except Exception:
                    pass

            if self._is_cancelled:
                self.all_finished.emit(False, "Cancelled")
                return

            # Auto flatten any nested folders in output_dir
            for d in list(os.listdir(self.output_dir)):
                dp = os.path.join(self.output_dir, d)
                if os.path.isdir(dp):
                    for sub in list(os.listdir(dp)):
                        subp = os.path.join(dp, sub)
                        if os.path.isdir(subp):
                            for f in os.listdir(subp):
                                src = os.path.join(subp, f)
                                dst = os.path.join(dp, f)
                                if not os.path.exists(dst):
                                    shutil.move(src, dst)
                            try:
                                os.rmdir(subp)
                            except Exception:
                                pass

            self.total_progress.emit(total_series_count, total_series_count, 100)
            self.status_message.emit(f"✓ All {total_series_count} drama(s) downloaded successfully!")
            self.all_finished.emit(True, self.output_dir)

        except Exception as e:
            self.all_finished.emit(False, str(e))

