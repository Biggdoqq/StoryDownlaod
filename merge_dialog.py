"""
Episode Merger Dialog & Worker (PyQt6)
Merges all downloaded short-drama episodes into a single Full Movie MP4 with chapters.
Connects to local engine /dl/library/merge with ffmpeg fallback.
"""

import os
import time
import json
import shutil
import subprocess
import requests
from typing import Dict, Any, Optional, List

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame, QComboBox, QMessageBox,
    QFileDialog, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor

from downloader import ENGINE_URL, ensure_engine_running, sanitize_filename, get_app_dir
from api import HongguoAPI
from player import DramaPlayerDialog
from safe_thread import retain_thread


def get_ffmpeg_path() -> str:
    """Find bundled or system FFmpeg binary."""
    candidates = [
        os.path.join(get_app_dir(), "engine", "app", "tools", "ffmpeg", "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine", "app", "tools", "ffmpeg", "ffmpeg.exe"),
        r"C:\Program Files\FFmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\FFmpeg\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Hongguo Downloader", "app", "tools", "ffmpeg.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Hongguo Downloader", "engine", "app", "tools", "ffmpeg", "ffmpeg.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    which = shutil.which("ffmpeg")
    return which if which else "ffmpeg"


class EpisodeMergeWorker(QThread):
    progress_signal = pyqtSignal(int)          # percent 0-100
    status_signal = pyqtSignal(str)           # message
    finished_signal = pyqtSignal(bool, str)   # success, output_path_or_error

    def __init__(self, drama_name: str, drama_dir: str, parent=None):
        super().__init__(parent)
        self.drama_name = drama_name
        self.drama_dir = drama_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            ensure_engine_running()
            self.status_signal.emit(f"Preparing to merge episodes of: {self.drama_name}...")

            # 1. First attempt: Use local engine merge endpoint
            parent_dir = os.path.dirname(os.path.abspath(self.drama_dir))
            try:
                requests.post(f"{ENGINE_URL}/dl/config", json={"output_dir": parent_dir}, timeout=3)
            except Exception:
                pass

            payload = {"name": self.drama_name, "variant": ""}
            resp = requests.post(f"{ENGINE_URL}/dl/library/merge", json=payload, timeout=8)
            merge_data = resp.json() if resp.status_code == 200 else {}

            if merge_data.get("ok"):
                self.status_signal.emit("Engine is merging episodes (Lossless Merge with Chapters)...")
                last_pct = 0
                while not self._is_cancelled:
                    time.sleep(1.2)
                    try:
                        st_resp = requests.get(f"{ENGINE_URL}/dl/library/merge-status", timeout=4)
                        if st_resp.status_code != 200:
                            continue
                        st = st_resp.json()
                        pct = st.get("pct", last_pct)
                        last_pct = pct
                        self.progress_signal.emit(pct)
                        self.status_signal.emit(f"Merging episodes... {pct}%")

                        if not st.get("running"):
                            if st.get("done"):
                                merged_file = st.get("file", "")
                                if not merged_file or not os.path.exists(merged_file):
                                    # Find merged mp4 in directory
                                    for f in os.listdir(self.drama_dir):
                                        if f.lower().endswith(".mp4") and any(k in f.lower() for k in ["merged", "full", "complete", self.drama_name.lower()]):
                                            merged_file = os.path.join(self.drama_dir, f)
                                            break
                                self.progress_signal.emit(100)
                                self.status_signal.emit("✓ All episodes merged successfully (100%)!")
                                self.finished_signal.emit(True, merged_file or self.drama_dir)
                                return
                            elif st.get("error"):
                                break
                    except Exception:
                        pass

            # 2. Fallback: Local ffmpeg concat merge
            self.status_signal.emit("Using local concat merger...")
            self._local_concat_merge()

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def _local_concat_merge(self):
        mp4_files = []
        if os.path.exists(self.drama_dir):
            for f in sorted(os.listdir(self.drama_dir)):
                if f.lower().endswith(".mp4") and not any(k in f.lower() for k in ["merged", "full_movie"]):
                    mp4_files.append(os.path.join(self.drama_dir, f))

        if not mp4_files:
            self.finished_signal.emit(False, "No MP4 episode files found to merge")
            return

        out_file = os.path.join(self.drama_dir, f"{sanitize_filename(self.drama_name)}_Full_Movie.mp4")
        list_file = os.path.join(self.drama_dir, "concat_list.txt")

        with open(list_file, "w", encoding="utf-8") as f:
            for mp4 in mp4_files:
                safe_p = mp4.replace(os.sep, '/').replace("'", "'\\''")
                f.write(f"file '{safe_p}'\n")

        ffmpeg_bin = get_ffmpeg_path()
        cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_file]
        self.status_signal.emit(f"Merging {len(mp4_files)} episodes (Local FFmpeg Concat)...")
        
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if os.path.exists(list_file):
            try:
                os.remove(list_file)
            except Exception:
                pass

        if res.returncode == 0 and os.path.exists(out_file) and os.path.getsize(out_file) > 0:
            self.progress_signal.emit(100)
            self.status_signal.emit("✓ Episodes merged successfully!")
            self.finished_signal.emit(True, out_file)
        else:
            self.finished_signal.emit(False, "Could not run ffmpeg concat")


class EpisodeMergeDialog(QDialog):
    def __init__(self, drama_name: str, drama_dir: str = "", drama_info: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.drama_name = drama_name
        self.drama_info = drama_info or {}
        self.worker = None
        self.merged_output_path = ""

        base_dl = os.path.join(get_app_dir(), "Downloaded_Videos")
        self.drama_dir = drama_dir or os.path.join(base_dl, sanitize_filename(drama_name))
        if not os.path.exists(self.drama_dir) and os.path.exists(os.path.join(base_dl, drama_name)):
            self.drama_dir = os.path.join(base_dl, drama_name)

        self.setWindowTitle(f"🎬 Merge All Episodes: {self.drama_name}")
        self.resize(650, 480)
        self.setMinimumSize(540, 400)

        self.init_ui()
        self._scan_episodes()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        # Header Info Card
        top_card = QFrame()
        top_card.setStyleSheet("background-color: #171220; border-radius: 14px; border: 1px solid #2C223C;")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(14, 14, 14, 14)
        top_layout.setSpacing(16)

        self.poster_lbl = QLabel()
        self.poster_lbl.setFixedSize(85, 115)
        self.poster_lbl.setStyleSheet("background-color: #21192E; border-radius: 8px; border: 1px solid #3B2E52;")
        self.poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Try to find poster locally first
        local_poster = os.path.join(self.drama_dir, "poster.jpg")
        if not os.path.exists(local_poster):
            local_poster = os.path.join(self.drama_dir, "cover.jpg")

        if os.path.exists(local_poster):
            pix = QPixmap(local_poster)
            if not pix.isNull():
                self.poster_lbl.setPixmap(pix.scaled(85, 115, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))

        if not self.poster_lbl.pixmap():
            self.poster_lbl.setText("🎬 Poster")

        top_layout.addWidget(self.poster_lbl)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        t_lbl = QLabel(f"🎬 {self.drama_name}")
        t_lbl.setStyleSheet("font-size: 17px; font-weight: 800; color: #FFFFFF;")
        t_lbl.setWordWrap(True)
        info_layout.addWidget(t_lbl)

        self.eps_count_lbl = QLabel("Scanning episode videos...")
        self.eps_count_lbl.setStyleSheet("color: #FF8038; font-size: 13px; font-weight: 700;")
        info_layout.addWidget(self.eps_count_lbl)

        desc_lbl = QLabel("This combines all individual episode videos into a single Full Movie MP4 with lossless quality and chapter markers.")
        desc_lbl.setStyleSheet("color: #B5ACC4; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        info_layout.addWidget(desc_lbl)

        top_layout.addLayout(info_layout)
        layout.addWidget(top_card)

        # Episode list preview
        list_lbl = QLabel("📋 Episodes to Merge:")
        list_lbl.setStyleSheet("color: #E2DDF0; font-size: 12px; font-weight: 700;")
        layout.addWidget(list_lbl)

        self.ep_list_widget = QListWidget()
        self.ep_list_widget.setStyleSheet("background-color: #191424; border-radius: 10px; border: 1px solid #2F2440; padding: 6px;")
        self.ep_list_widget.setMaximumHeight(120)
        layout.addWidget(self.ep_list_widget)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Ready to merge")
        self.status_lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.start_btn = QPushButton("🎬 Start Merge All")
        self.start_btn.setProperty("class", "PrimaryBtn")
        self.start_btn.clicked.connect(self._start_merge)
        btn_bar.addWidget(self.start_btn)

        self.play_btn = QPushButton("▶ Play Full Movie")
        self.play_btn.setProperty("class", "PrimaryBtn")
        self.play_btn.setVisible(False)
        self.play_btn.clicked.connect(self._play_full_movie)
        btn_bar.addWidget(self.play_btn)

        self.open_folder_btn = QPushButton("📂 Open Folder")
        self.open_folder_btn.setProperty("class", "SecondaryBtn")
        self.open_folder_btn.clicked.connect(self._open_folder)
        btn_bar.addWidget(self.open_folder_btn)

        close_btn = QPushButton("Close")
        close_btn.setProperty("class", "SecondaryBtn")
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def _scan_episodes(self):
        self.ep_list_widget.clear()
        self.episodes = []
        if os.path.exists(self.drama_dir):
            for f in sorted(os.listdir(self.drama_dir)):
                if f.lower().endswith(".mp4") and not any(k in f.lower() for k in ["merged", "full_movie"]):
                    self.episodes.append(f)
                    item = QListWidgetItem(f"📄 {f}")
                    self.ep_list_widget.addItem(item)

        total = len(self.episodes)
        self.eps_count_lbl.setText(f"Found: <b>{total} Episodes</b> locally")
        if total == 0:
            self.status_lbl.setText("⚠️ No video episodes found in this folder. Please download first.")
            self.start_btn.setEnabled(False)

        # Check if already merged
        if os.path.exists(self.drama_dir):
            for f in os.listdir(self.drama_dir):
                if f.lower().endswith(".mp4") and any(k in f.lower() for k in ["merged", "full_movie"]):
                    self.merged_output_path = os.path.join(self.drama_dir, f)
                    self.play_btn.setVisible(True)
                    self.status_lbl.setText(f"✓ Full Movie already exists: {f}")
                    break

    def _start_merge(self):
        if not self.episodes:
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Merging all episodes...")

        self.worker = retain_thread(EpisodeMergeWorker(self.drama_name, self.drama_dir, parent=None))
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.status_signal.connect(self._on_status)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)

    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)

    def _on_finished(self, success: bool, path_or_err: str):
        self.start_btn.setEnabled(True)
        if success:
            self.merged_output_path = path_or_err
            self.progress_bar.setValue(100)
            self.play_btn.setVisible(True)
            self.status_lbl.setText(f"✓ Merge complete! File: {os.path.basename(path_or_err)}")
            QMessageBox.information(
                self, "Merge Complete",
                f"All episodes of '{self.drama_name}' merged successfully!\n\nYou can now click '▶ Play Full Movie'!"
            )
        else:
            self.status_lbl.setText(f"Error: {path_or_err}")
            QMessageBox.critical(self, "Error", f"Failed to merge episodes: {path_or_err}")

    def _open_folder(self):
        if os.path.exists(self.drama_dir):
            if os.name == 'nt':
                os.startfile(self.drama_dir)
            else:
                subprocess.Popen(['xdg-open', self.drama_dir])

    def _play_full_movie(self):
        if self.merged_output_path and os.path.exists(self.merged_output_path):
            dlg = DramaPlayerDialog(
                drama={"title": f"{self.drama_name} (Full Movie)", "series_id": self.drama_info.get("series_id", "")},
                initial_video_path=self.merged_output_path,
                parent=self
            )
            dlg.exec()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            try:
                self.worker.progress_signal.disconnect()
                self.worker.status_signal.disconnect()
                self.worker.finished_signal.disconnect()
            except Exception:
                pass
            self.worker.cancel()
        if event:
            super().closeEvent(event)

    def reject(self):
        self.closeEvent(None)
        super().reject()
