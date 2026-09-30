"""
In-App Direct Drama Episode Download Dialog (PyQt6)
Allows users to download short-dramas directly inside the application,
view real-time progress, and immediately play the downloaded episodes in 1080p MP4.
"""

import os
import subprocess
from typing import Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QMessageBox,
    QProgressBar, QFrame, QTextEdit, QRadioButton, QButtonGroup,
    QComboBox
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor

from downloader import (
    DramaSeriesDownloadWorker, sanitize_filename,
    ensure_engine_running, fetch_series_episodes,
    is_engine_alive, is_signer_alive, get_app_dir
)
from api import HongguoAPI
from player import DramaPlayerDialog
from safe_thread import retain_thread


class DramaDetailsLoaderThread(QThread):
    loaded_signal = pyqtSignal(dict, bool)  # ep_info, engine_ready

    def __init__(self, series_id: str, parent=None):
        super().__init__(parent)
        self.series_id = series_id
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        engine_ready = ensure_engine_running()
        if not self._is_running:
            return
        ep_info = fetch_series_episodes(self.series_id, ensure_start=False) if engine_ready else None
        if self._is_running:
            self.loaded_signal.emit(ep_info or {}, engine_ready)


class AsyncPosterLoaderThread(QThread):
    image_loaded = pyqtSignal(bytes)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            b = HongguoAPI().fetch_image_bytes(self.url)
            if b and self._is_running:
                self.image_loaded.emit(b)
        except Exception:
            pass


class DramaDownloadDialog(QDialog):
    def __init__(self, drama: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.drama = drama
        self.title = drama.get("title", "Drama")
        self.series_id = str(drama.get("series_id", ""))
        self.eps_count = int(drama.get("episode_cnt") or 1)
        self.worker = None
        self._loader_thread = None
        self._poster_thread = None

        self.setWindowTitle(f"⬇ Download Drama: {self.title}")
        self.resize(700, 560)
        self.setMinimumSize(600, 480)

        # Default save location inside project
        safe_title = sanitize_filename(self.title)
        self.target_dir = os.path.join(get_app_dir(), "Downloaded_Videos", safe_title)

        self.init_ui()
        self._start_async_loading()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Top Card: Poster + Drama Info
        top_card = QFrame()
        top_card.setStyleSheet("background-color: #171220; border-radius: 14px; border: 1px solid #2C223C;")
        top_card_layout = QHBoxLayout(top_card)
        top_card_layout.setContentsMargins(14, 14, 14, 14)
        top_card_layout.setSpacing(16)

        self.poster_lbl = QLabel()
        self.poster_lbl.setFixedSize(95, 128)
        self.poster_lbl.setStyleSheet("background-color: #21192E; border-radius: 10px; border: 1px solid #3B2E52;")
        self.poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_lbl.setText("Poster")

        cover_url = self.drama.get("cover", "")
        if cover_url:
            self._poster_thread = retain_thread(AsyncPosterLoaderThread(cover_url, parent=None))
            self._poster_thread.image_loaded.connect(self._on_poster_bytes)
            self._poster_thread.start()

        top_card_layout.addWidget(self.poster_lbl)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        t_lbl = QLabel(f"🎬 {self.title}")
        t_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")
        t_lbl.setWordWrap(True)
        info_layout.addWidget(t_lbl)

        self.meta_lbl = QLabel(f"Series ID: <b>{self.series_id}</b> | Episodes: <b>{self.eps_count} Eps</b>")
        self.meta_lbl.setStyleSheet("color: #FF8038; font-size: 13px; font-weight: 600;")
        info_layout.addWidget(self.meta_lbl)

        engine_ready_now = is_engine_alive() and is_signer_alive()
        initial_status = "🟢 Engine Ready" if engine_ready_now else "🟡 Connecting Engine..."
        self.engine_lbl = QLabel(initial_status)
        color = "#4ADE80" if engine_ready_now else "#FBBF24"
        self.engine_lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")
        info_layout.addWidget(self.engine_lbl)

        tip_lbl = QLabel("✓ Videos are downloaded as 1080p Full HD MP4 files without watermarks.")
        tip_lbl.setStyleSheet("color: #B5ACC4; font-size: 12px;")
        info_layout.addWidget(tip_lbl)

        top_card_layout.addLayout(info_layout)
        layout.addWidget(top_card)

        # Options: Episode Range Selection
        opt_frame = QFrame()
        opt_frame.setStyleSheet("background-color: #191424; border-radius: 12px; border: 1px solid #2E2440; padding: 10px;")
        opt_layout = QVBoxLayout(opt_frame)
        opt_layout.setSpacing(8)

        opt_title = QLabel("⚙️ Episode Selection:")
        opt_title.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 700;")
        opt_layout.addWidget(opt_title)

        self.radio_all = QRadioButton(f"All Episodes ({self.eps_count} Total)")
        self.radio_all.setChecked(True)
        self.radio_all.setStyleSheet("color: #E2DDF0; font-size: 13px;")

        self.radio_first = QRadioButton("Download Episode 1 only (Quick Test)")
        self.radio_first.setStyleSheet("color: #E2DDF0; font-size: 13px;")

        self.radio_custom = QRadioButton("Custom Episode Range:")
        self.radio_custom.setStyleSheet("color: #E2DDF0; font-size: 13px;")

        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.radio_all)
        self.btn_group.addButton(self.radio_first)
        self.btn_group.addButton(self.radio_custom)

        opt_layout.addWidget(self.radio_all)
        opt_layout.addWidget(self.radio_first)

        custom_row = QHBoxLayout()
        custom_row.addWidget(self.radio_custom)
        self.range_input = QLineEdit("1-5")
        self.range_input.setPlaceholderText("e.g. 1-10 or 1,3,5")
        self.range_input.setMaximumWidth(180)
        custom_row.addWidget(self.range_input)
        custom_row.addStretch()
        opt_layout.addLayout(custom_row)

        # Quality selector row
        qual_row = QHBoxLayout()
        q_label = QLabel("📺 Video Quality:")
        q_label.setStyleSheet("color: #B5ACC4; font-size: 12px; font-weight: 600;")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["1080p (Best - Full HD)", "720p (HD)", "480p (SD)"])
        qual_row.addWidget(q_label)
        qual_row.addWidget(self.quality_combo)
        qual_row.addStretch()
        opt_layout.addLayout(qual_row)

        layout.addWidget(opt_frame)

        # Destination folder
        folder_row = QHBoxLayout()
        f_label = QLabel("📁 Save Folder:")
        f_label.setStyleSheet("color: #B5ACC4; font-size: 12px; font-weight: 600;")
        self.folder_input = QLineEdit(self.target_dir)
        browse_btn = QPushButton("Browse Folder")
        browse_btn.setProperty("class", "SecondaryBtn")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(f_label)
        folder_row.addWidget(self.folder_input)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        # Progress bar & status
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Ready to download")
        self.status_lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.start_btn = QPushButton("⬇ Start Download")
        self.start_btn.setProperty("class", "PrimaryBtn")
        self.start_btn.clicked.connect(self._start_download)
        btn_bar.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("⛔ Cancel")
        self.cancel_btn.setProperty("class", "SecondaryBtn")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_download)
        btn_bar.addWidget(self.cancel_btn)

        self.play_now_btn = QPushButton("▶ Play Now")
        self.play_now_btn.setProperty("class", "PrimaryBtn")
        self.play_now_btn.setVisible(False)
        self.play_now_btn.clicked.connect(self._play_now)
        btn_bar.addWidget(self.play_now_btn)

        self.merge_btn = QPushButton("🎬 Merge Episodes")
        self.merge_btn.setProperty("class", "SecondaryBtn")
        self.merge_btn.setVisible(False)
        self.merge_btn.clicked.connect(self._open_merge_dialog)
        btn_bar.addWidget(self.merge_btn)

        self.open_folder_btn = QPushButton("📂 Open Folder")
        self.open_folder_btn.setProperty("class", "SecondaryBtn")
        self.open_folder_btn.clicked.connect(self._open_folder)
        btn_bar.addWidget(self.open_folder_btn)

        close_btn = QPushButton("Close")
        close_btn.setProperty("class", "SecondaryBtn")
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def _on_poster_bytes(self, img_bytes: bytes):
        if img_bytes:
            pix = QPixmap()
            if pix.loadFromData(img_bytes):
                self.poster_lbl.setPixmap(pix.scaled(95, 128, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))

    def _start_async_loading(self):
        """Asynchronously load engine readiness and series episode count."""
        # 1. Check existing downloaded files instantly without blocking
        safe_title = sanitize_filename(self.title)
        check_dirs = [
            os.path.join(get_app_dir(), "Downloaded_Videos", safe_title),
            os.path.join(get_app_dir(), "Downloaded_Videos", self.title),
        ]
        base_dl = os.path.join(get_app_dir(), "Downloaded_Videos")
        if os.path.exists(base_dl):
            for d in os.listdir(base_dl):
                check_dirs.append(os.path.join(base_dl, d))

        for c_dir in check_dirs:
            if os.path.exists(c_dir):
                self.play_now_btn.setVisible(True)
                self.merge_btn.setVisible(True)
                break

        # 2. Launch background thread to ensure engine and fetch episode list
        self._loader_thread = retain_thread(DramaDetailsLoaderThread(self.series_id, parent=None))
        self._loader_thread.loaded_signal.connect(self._on_details_loaded)
        self._loader_thread.start()

    def _on_details_loaded(self, ep_info: dict, engine_ready: bool):
        """Handle background loading completion without freezing UI."""
        if engine_ready:
            self.engine_lbl.setText("🟢 Engine Ready")
            self.engine_lbl.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 700;")
        else:
            self.engine_lbl.setText("🟡 Engine Initializing (ready on start)")
            self.engine_lbl.setStyleSheet("color: #FBBF24; font-size: 12px; font-weight: 700;")

        if ep_info:
            if ep_info.get("cover"):
                self.drama["cover"] = ep_info["cover"]
            if ep_info.get("total"):
                self.eps_count = ep_info["total"]
                self.meta_lbl.setText(f"Series ID: <b>{self.series_id}</b> | Episodes: <b>{self.eps_count} Eps</b>")
                self.radio_all.setText(f"All Episodes ({self.eps_count} Total)")

    def _open_merge_dialog(self):
        from merge_dialog import EpisodeMergeDialog
        dlg = EpisodeMergeDialog(self.title, self.target_dir, self.drama, parent=self)
        dlg.exec()

    def _browse_folder(self):
        current = self.folder_input.text().strip()
        start_dir = os.path.dirname(current) if current else get_app_dir()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Save Videos", start_dir or get_app_dir())
        if folder:
            safe_title = sanitize_filename(self.title)
            if os.path.basename(os.path.normpath(folder)) != safe_title:
                folder = os.path.join(folder, safe_title)
            self.folder_input.setText(folder)
            self.target_dir = folder

    def _start_download(self):
        folder = self.folder_input.text().strip()
        if not folder:
            return
        safe_title = sanitize_filename(self.title)
        if os.path.basename(os.path.normpath(folder)) != safe_title:
            folder = os.path.join(folder, safe_title)
            self.folder_input.setText(folder)
        self.target_dir = folder

        # Determine episodes range
        ep_range = ""
        if self.radio_first.isChecked():
            ep_range = "1"
        elif self.radio_custom.isChecked():
            ep_range = self.range_input.text().strip()
        else:
            ep_range = ""  # empty means all

        quality_choice = self.quality_combo.currentText()
        quality_code = "1080p"
        if "720p" in quality_choice:
            quality_code = "720p"
        elif "480p" in quality_choice:
            quality_code = "480p"

        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Starting download...")

        self.worker = retain_thread(DramaSeriesDownloadWorker(
            drama=self.drama,
            output_folder=self.target_dir,
            episodes_range=ep_range,
            quality=quality_code,
            parent=None
        ))
        self.worker.episode_progress.connect(self._on_progress)
        self.worker.status_message.connect(self._on_status)
        self.worker.all_finished.connect(self._on_finished)
        self.worker.start()

    def _cancel_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_lbl.setText("Cancelling...")
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, current_ep, total_eps, pct, speed):
        self.progress_bar.setValue(pct)
        self.status_lbl.setText(f"Downloading Episode {current_ep}/{total_eps} ({pct}%)...")

    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)

    def _on_finished(self, success: bool, msg_or_path: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        if success:
            self.progress_bar.setValue(100)
            self.status_lbl.setText(f"✓ Download complete! Location: {self.target_dir}")
            self.play_now_btn.setVisible(True)
            self.merge_btn.setVisible(True)
            msg = QMessageBox(self)
            msg.setWindowTitle("🎉 Download Complete")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(f"<b>🎉 Download Completed for 《{self.title}》!</b>")
            msg.setInformativeText(
                f"<div style='margin-top: 6px; line-height: 1.6;'>"
                f"📁 <b>Save Location:</b><br>"
                f"<span style='color: #FF8A47; font-weight: 600;'>{self.target_dir}</span><br><br>"
                f"▶ <i>You can now click <b>'▶ Play Now'</b> to watch immediately!</i>"
                f"</div>"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        else:
            self.status_lbl.setText(f"Error: {msg_or_path}")
            QMessageBox.critical(self, "Error", f"Failed to download:\n{msg_or_path}")

    def _open_folder(self):
        folder = self.folder_input.text().strip()
        os.makedirs(folder, exist_ok=True)
        if os.name == 'nt':
            os.startfile(folder)
        else:
            subprocess.Popen(['xdg-open', folder])

    def _play_now(self):
        dlg = DramaPlayerDialog(self.drama, parent=self)
        dlg.exec()

    def closeEvent(self, event):
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.stop()
            try:
                self._loader_thread.loaded_signal.disconnect()
            except Exception:
                pass
        if self._poster_thread and self._poster_thread.isRunning():
            self._poster_thread.stop()
            try:
                self._poster_thread.image_loaded.disconnect()
            except Exception:
                pass
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            try:
                self.worker.episode_progress.disconnect()
                self.worker.status_message.disconnect()
                self.worker.all_finished.disconnect()
            except Exception:
                pass
        if event:
            super().closeEvent(event)

    def reject(self):
        self.closeEvent(None)
        super().reject()
