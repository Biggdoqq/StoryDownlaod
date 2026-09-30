"""
update_dialog.py — In-App GitHub Auto-Update Dialog & Notification Alert (PyQt6)
Directly connects to https://github.com/Biggdoqq/StoryDownlaod to check for updates,
displays release notes / changelog, alerts the user inside the tool, and streams
the new Setup Installer with live progress.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor

from github_updater import check_github_release, download_github_asset
from version import APP_VERSION
from safe_thread import retain_thread


class UpdateCheckWorker(QThread):
    check_finished = pyqtSignal(dict)  # update_info

    def __init__(self, current_version: str = APP_VERSION, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            info = check_github_release(self.current_version)
            self.check_finished.emit(info)
        except Exception as e:
            self.check_finished.emit({
                "has_update": False,
                "current_version": self.current_version,
                "latest_version": self.current_version,
                "error": str(e)
            })


class UpdateDownloadWorker(QThread):
    progress_signal = pyqtSignal(int, int, int, float)  # downloaded_bytes, total_bytes, percent, speed_kb
    finished_signal = pyqtSignal(bool, str)             # success, file_path_or_err

    def __init__(self, download_url: str, dest_path: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.dest_path = dest_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _progress_cb(self, downloaded: int, total: int, pct: int, speed_kb: float):
        self.progress_signal.emit(downloaded, total, pct, speed_kb)

    def run(self):
        try:
            success = download_github_asset(
                url=self.download_url,
                dest_path=self.dest_path,
                progress_callback=self._progress_cb,
                cancel_flag=lambda: self._is_cancelled
            )
            if success and not self._is_cancelled:
                self.finished_signal.emit(True, self.dest_path)
            else:
                self.finished_signal.emit(False, "Cancelled or failed to download from GitHub")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class UpdateAlertModal(QDialog):
    """
    Sleek in-tool modal that alerts the user when a new version is released on GitHub.
    Shows version difference, changelog, and instant 'Update Now' CTA.
    """
    def __init__(self, update_info: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.latest_version = update_info.get("latest_version", "New")
        self.current_version = update_info.get("current_version", APP_VERSION)
        self.setWindowTitle(f"🎉 New Update Available — v{self.latest_version}")
        self.resize(570, 440)
        self.setMinimumSize(500, 380)
        self.setStyleSheet("""
            QDialog {
                background-color: #160F0D;
                color: #EDE5DF;
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
            }
            QLabel {
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
                background: transparent;
                border: none;
            }
            QPushButton {
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
            }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header Card
        header_card = QFrame()
        header_card.setObjectName("AlertHeaderCard")
        header_card.setStyleSheet("""
            QFrame#AlertHeaderCard {
                background-color: #201512;
                border: 1px solid #38241D;
                border-radius: 12px;
            }
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(14)

        icon_lbl = QLabel("🚀")
        icon_lbl.setStyleSheet("font-size: 34px;")
        h_layout.addWidget(icon_lbl)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title_lbl = QLabel("🎉 មានកំណែអាប់ដេតថ្មី! (New Update Available)")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #FFFFFF;")
        info_layout.addWidget(title_lbl)

        sub_lbl = QLabel(f"Hongguo Downloader <b>v{self.latest_version}</b> is now ready on GitHub!")
        sub_lbl.setStyleSheet("color: #FF8E52; font-size: 12px; font-weight: 600;")
        info_layout.addWidget(sub_lbl)

        h_layout.addLayout(info_layout)
        h_layout.addStretch()
        layout.addWidget(header_card)

        # Version comparison row
        ver_row = QHBoxLayout()
        ver_row.setSpacing(10)

        cur_box = QLabel(f"Current: v{self.current_version}")
        cur_box.setStyleSheet("background-color: #201613; border: 1px solid #36241D; color: #9E8E87; border-radius: 8px; padding: 5px 12px; font-weight: 600; font-size: 11.5px;")
        ver_row.addWidget(cur_box)

        arrow_lbl = QLabel("➜")
        arrow_lbl.setStyleSheet("color: #FF7733; font-weight: 900; font-size: 14px;")
        ver_row.addWidget(arrow_lbl)

        new_box = QLabel(f"Latest: v{self.latest_version}")
        new_box.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733); color: #FFFFFF; border-radius: 8px; padding: 5px 14px; font-weight: 800; font-size: 12px;")
        ver_row.addWidget(new_box)

        ver_row.addStretch()
        layout.addLayout(ver_row)

        # Changelog / Release Notes
        cl_title = QLabel("📝 Release Notes / Changelog:")
        cl_title.setStyleSheet("color: #EDE5DF; font-size: 12.5px; font-weight: 700;")
        layout.addWidget(cl_title)

        changelog = self.update_info.get("changelog", "").strip() or "• Performance enhancements & faster downloads\n• Bug fixes and UI improvements"
        self.changelog_edit = QTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setPlainText(changelog)
        self.changelog_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1A1210;
                color: #DDD4CF;
                border: 1px solid #2F201A;
                border-radius: 10px;
                font-size: 12px;
                line-height: 1.5;
                padding: 8px;
            }
        """)
        layout.addWidget(self.changelog_edit)

        # Bottom Action Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        later_btn = QPushButton("Remind Me Later (ពេលក្រោយ)")
        later_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        later_btn.setStyleSheet("""
            QPushButton {
                background-color: #221815;
                color: #B8AAA2;
                border: 1px solid #33221C;
                border-radius: 9px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2D1F1A;
                color: #FFFFFF;
            }
        """)
        later_btn.clicked.connect(self.reject)
        btn_bar.addWidget(later_btn)

        btn_bar.addStretch()

        update_btn = QPushButton("🚀 Update Now (អាប់ដេតឥឡូវនេះ)")
        update_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        update_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733);
                color: #FFFFFF;
                border: none;
                border-radius: 9px;
                padding: 8px 20px;
                font-weight: 800;
                font-size: 12.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5D36, stop:1 #FF8847);
            }
        """)
        update_btn.clicked.connect(self.accept)
        btn_bar.addWidget(update_btn)

        layout.addLayout(btn_bar)


class UpdateDialog(QDialog):
    def __init__(self, current_version: str = APP_VERSION, auto_check: bool = True, update_info: Optional[dict] = None, auto_download: bool = False, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.update_info = update_info or {}
        self.check_worker = None
        self.download_worker = None
        self.downloaded_installer_path = ""
        self.auto_download = auto_download

        self.setWindowTitle("🚀 Check for Updates — GitHub")
        self.resize(560, 430)
        self.setMinimumSize(490, 370)
        self.setStyleSheet("""
            QDialog {
                background-color: #160F0D;
                color: #EDE5DF;
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
            }
            QLabel {
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
                background: transparent;
                border: none;
            }
            QPushButton {
                font-family: 'Segoe UI', 'Leelawadee UI', 'Khmer OS Siemreap', 'Noto Sans Khmer', sans-serif;
            }
        """)

        self.init_ui()
        if self.update_info and self.auto_download:
            self._display_info(self.update_info)
            self._on_action_clicked()
        elif auto_check:
            self.start_check()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header Card
        header_card = QFrame()
        header_card.setObjectName("UpdateHeaderCard")
        header_card.setStyleSheet("""
            QFrame#UpdateHeaderCard {
                background-color: #201512;
                border: 1px solid #38241D;
                border-radius: 12px;
            }
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(14)

        icon_lbl = QLabel("🚀")
        icon_lbl.setStyleSheet("font-size: 34px;")
        h_layout.addWidget(icon_lbl)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title_lbl = QLabel("Hongguo Downloader Update Manager")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #FFFFFF;")
        info_layout.addWidget(title_lbl)

        self.ver_lbl = QLabel(f"Current Version: <b>v{self.current_version}</b>")
        self.ver_lbl.setStyleSheet("color: #B5ACC4; font-size: 12px;")
        info_layout.addWidget(self.ver_lbl)

        self.status_badge = QLabel("🟡 Checking GitHub releases...")
        self.status_badge.setStyleSheet("color: #FBBF24; font-size: 12px; font-weight: 700;")
        info_layout.addWidget(self.status_badge)

        h_layout.addLayout(info_layout)
        h_layout.addStretch()
        layout.addWidget(header_card)

        # Changelog / Release Notes
        cl_title = QLabel("📝 Release Notes / Changelog:")
        cl_title.setStyleSheet("color: #EDE5DF; font-size: 12.5px; font-weight: 700;")
        layout.addWidget(cl_title)

        self.changelog_edit = QTextEdit()
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setPlaceholderText("Checking GitHub for latest release...")
        self.changelog_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1A1210;
                color: #DDD4CF;
                border: 1px solid #2F201A;
                border-radius: 10px;
                font-size: 12px;
                line-height: 1.5;
                padding: 8px;
            }
        """)
        layout.addWidget(self.changelog_edit)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #241814;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #22C55E);
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.dl_status_lbl = QLabel("")
        self.dl_status_lbl.setStyleSheet("color: #FF8E52; font-size: 11.5px; font-weight: 600;")
        self.dl_status_lbl.setVisible(False)
        layout.addWidget(self.dl_status_lbl)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.check_again_btn = QPushButton("🔄 Check Again")
        self.check_again_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.check_again_btn.setStyleSheet("""
            QPushButton {
                background-color: #221815;
                color: #B8AAA2;
                border: 1px solid #33221C;
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: 600;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #2D1F1A;
                color: #FFFFFF;
            }
        """)
        self.check_again_btn.clicked.connect(self.start_check)
        btn_bar.addWidget(self.check_again_btn)

        btn_bar.addStretch()

        self.action_btn = QPushButton("⬇ Download & Install (Update Now)")
        self.action_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.action_btn.setEnabled(False)
        self.action_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733);
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 7px 18px;
                font-weight: 800;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5D36, stop:1 #FF8847);
            }
            QPushButton:disabled {
                background-color: #2A1E19;
                color: #6E5C54;
            }
        """)
        self.action_btn.clicked.connect(self._on_action_clicked)
        btn_bar.addWidget(self.action_btn)

        close_btn = QPushButton("Close")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #221815;
                color: #B8AAA2;
                border: 1px solid #33221C;
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: 600;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #2D1F1A;
                color: #FFFFFF;
            }
        """)
        close_btn.clicked.connect(self.close)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def start_check(self):
        self.status_badge.setText("🟡 Connecting to GitHub releases...")
        self.status_badge.setStyleSheet("color: #FBBF24; font-size: 12px; font-weight: 700;")
        self.action_btn.setEnabled(False)
        self.check_again_btn.setEnabled(False)
        self.changelog_edit.setPlainText("Fetching update information from GitHub...")

        self.check_worker = retain_thread(UpdateCheckWorker(self.current_version, parent=None))
        self.check_worker.check_finished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_finished(self, info: dict):
        self.check_again_btn.setEnabled(True)
        self.update_info = info
        self._display_info(info)

    def _display_info(self, info: dict):
        curr = info.get("current_version", self.current_version)
        self.current_version = curr
        latest = info.get("latest_version", self.current_version)
        has_update = info.get("has_update", False)
        changelog = info.get("changelog", "").strip() or "• Performance enhancements & download speed optimization\n• UI design polish and bug fixes"
        dl_url = info.get("download_url", "")

        self.ver_lbl.setText(f"Current: <b>v{curr}</b> | Latest: <b style='color: #FF7A33;'>v{latest}</b>")
        self.changelog_edit.setPlainText(changelog)

        if has_update:
            self.status_badge.setText(f"🔥 New version v{latest} available on GitHub!")
            self.status_badge.setStyleSheet("color: #FF552B; font-size: 12px; font-weight: 800;")
            if dl_url:
                self.action_btn.setEnabled(True)
                self.action_btn.setText(f"⬇ Download & Update to v{latest}")
            else:
                self.action_btn.setEnabled(False)
                self.action_btn.setText("No Installer Attached on GitHub")
        else:
            self.status_badge.setText("🟢 You are using the latest version!")
            self.status_badge.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 700;")
            self.action_btn.setEnabled(False)
            self.action_btn.setText("Up to Date")

    def _on_action_clicked(self):
        dl_url = self.update_info.get("download_url", "")
        if not dl_url:
            return

        latest = self.update_info.get("latest_version", "latest")
        temp_dir = Path(os.environ.get("TEMP", os.getcwd())) / "HongguoDownloader_Updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        dest_file = str(temp_dir / f"HongguoDownloader-Setup-v{latest}.exe")

        self.action_btn.setEnabled(False)
        self.check_again_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.dl_status_lbl.setVisible(True)
        self.dl_status_lbl.setText("Connecting to GitHub...")

        self.download_worker = retain_thread(UpdateDownloadWorker(dl_url, dest_file, parent=None))
        self.download_worker.progress_signal.connect(self._on_download_progress)
        self.download_worker.finished_signal.connect(self._on_download_finished)
        self.download_worker.start()

    def _on_download_progress(self, downloaded: int, total: int, pct: int, speed_kb: float):
        self.progress_bar.setValue(pct)
        mb_down = downloaded / (1024 * 1024)
        mb_tot = total / (1024 * 1024) if total > 0 else 0
        speed_str = f" · {speed_kb / 1024:.2f} MB/s" if speed_kb >= 1024 else f" · {speed_kb:.1f} KB/s"
        if mb_tot > 0:
            self.dl_status_lbl.setText(f"Downloading from GitHub: {mb_down:.1f} MB / {mb_tot:.1f} MB ({pct}%){speed_str}...")
        else:
            self.dl_status_lbl.setText(f"Downloading: {mb_down:.1f} MB{speed_str}...")

    def _on_download_finished(self, success: bool, path_or_err: str):
        self.check_again_btn.setEnabled(True)
        if success and os.path.exists(path_or_err):
            self.progress_bar.setValue(100)
            self.dl_status_lbl.setText("✓ Installer downloaded! Launching Setup...")
            self.downloaded_installer_path = path_or_err

            reply = QMessageBox.question(
                self,
                "Download Complete",
                "🎉 The update installer has been downloaded successfully from GitHub!\n\nWould you like to install now and restart?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.startfile(self.downloaded_installer_path)
                    QApplication.quit()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not launch Setup: {e}")
            else:
                self.action_btn.setEnabled(True)
                self.action_btn.setText("🚀 Launch Setup Now")
                self.action_btn.clicked.disconnect()
                self.action_btn.clicked.connect(lambda: os.startfile(self.downloaded_installer_path))
        else:
            self.dl_status_lbl.setText(f"Download failed: {path_or_err}")
            self.action_btn.setEnabled(True)
            self.action_btn.setText("Retry Download")
            QMessageBox.critical(self, "Error", f"Failed to download update: {path_or_err}")

    def closeEvent(self, event):
        if self.check_worker and self.check_worker.isRunning():
            try:
                self.check_worker.check_finished.disconnect()
            except Exception:
                pass
        if self.download_worker and self.download_worker.isRunning():
            try:
                self.download_worker.progress_signal.disconnect()
                self.download_worker.finished_signal.disconnect()
            except Exception:
                pass
            self.download_worker.cancel()
        if event:
            super().closeEvent(event)

    def reject(self):
        self.closeEvent(None)
        super().reject()
