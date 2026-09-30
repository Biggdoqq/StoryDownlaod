"""
Activation Dialog for Hongguo Downloader
Validates license keys against Google Sheet via license_client.py
"""

import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QIcon

from license_client import get_hwid, verify_license, LicenseResult


class ActivationWorker(QThread):
    finished_signal = pyqtSignal(object)  # LicenseResult

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key.strip()

    def run(self):
        try:
            result = verify_license(key=self.key, allow_offline=False)
            self.finished_signal.emit(result)
        except Exception as e:
            res = LicenseResult(False, f"Connection error: {e}")
            self.finished_signal.emit(res)


class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 Hongguo Downloader - ផ្ទៀងផ្ទាត់ License (Activation)")
        import os
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setFixedSize(550, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.worker = None
        self.is_activated = True
        self.license_info = LicenseResult(True, "Activated", expiry="Lifetime", customer="VIP User")

        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #121016;
                color: #F5F3F7;
                font-family: 'Segoe UI', 'Khmer OS Siemreap', sans-serif;
            }
            QLabel {
                color: #F5F3F7;
            }
            QLineEdit {
                background-color: #1C1726;
                color: #F5F3F7;
                border: 1px solid #362B4A;
                border-radius: 10px;
                padding: 8px 14px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #FF552B;
            }
            QPushButton.PrimaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1B, stop:1 #FF782D);
                color: #FFFFFF;
                font-weight: 700;
                font-size: 13px;
                padding: 10px 20px;
                border-radius: 10px;
                border: none;
            }
            QPushButton.PrimaryBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5233, stop:1 #FF8842);
            }
            QPushButton.PrimaryBtn:disabled {
                background: #382D47;
                color: #7A6F8A;
            }
            QPushButton.SecondaryBtn {
                background-color: #231B30;
                color: #C5BCD2;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                border-radius: 10px;
                border: 1px solid #382C4D;
            }
            QPushButton.SecondaryBtn:hover {
                background-color: #2D233D;
                color: #FFF;
                border-color: #FF6633;
            }
            QFrame.Card {
                background-color: #181322;
                border: 1px solid #2C223C;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # Header Title
        title_lbl = QLabel("🔐 Hongguo Downloader Activation")
        title_lbl.setStyleSheet("font-size: 19px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("សូមបញ្ចូល License Key ដើម្បីប្រើប្រាស់កម្មវិធី (គ្រប់គ្រងតាម Google Sheet):")
        sub_lbl.setStyleSheet("color: #A69CB5; font-size: 12px;")
        layout.addWidget(sub_lbl)

        # HWID Card
        hwid_card = QFrame()
        hwid_card.setProperty("class", "Card")
        hwid_layout = QVBoxLayout(hwid_card)
        hwid_layout.setContentsMargins(14, 12, 14, 12)
        hwid_layout.setSpacing(8)

        hwid_title = QLabel("Hardware ID (HWID នៃកុំព្យូទ័ររបស់អ្នក):")
        hwid_title.setStyleSheet("font-size: 11px; color: #B5ACC4; font-weight: 600;")
        hwid_layout.addWidget(hwid_title)

        hwid_row = QHBoxLayout()
        hwid_row.setSpacing(8)
        self.hwid = get_hwid()
        self.hwid_input = QLineEdit(self.hwid)
        self.hwid_input.setReadOnly(True)
        self.hwid_input.setFixedHeight(38)
        self.hwid_input.setStyleSheet("background-color: #15111E; color: #FFA566; font-family: monospace; font-size: 11px; border: 1px solid #2B213A; border-radius: 8px; padding: 0 10px;")
        hwid_row.addWidget(self.hwid_input)

        copy_hwid_btn = QPushButton("📋 Copy")
        copy_hwid_btn.setProperty("class", "SecondaryBtn")
        copy_hwid_btn.setFixedHeight(38)
        copy_hwid_btn.setFixedWidth(85)
        copy_hwid_btn.setToolTip("ចម្លង HWID ផ្ញើទៅ Admin")
        copy_hwid_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        copy_hwid_btn.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(copy_hwid_btn)
        hwid_layout.addLayout(hwid_row)
        layout.addWidget(hwid_card)

        # License Key Input Card
        key_layout = QVBoxLayout()
        key_layout.setSpacing(6)
        key_lbl = QLabel("License Key:")
        key_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #DDD;")
        key_layout.addWidget(key_lbl)

        self.key_input = QLineEdit()
        self.key_input.setFixedHeight(42)
        self.key_input.setPlaceholderText("ឧ. KVN-XXXX-XXXX-XXXX-XXXX")
        self.key_input.setStyleSheet("font-size: 13px; font-weight: 600; padding: 0 12px;")
        self.key_input.returnPressed.connect(self._activate_key)
        key_layout.addWidget(self.key_input)
        layout.addLayout(key_layout)

        # Progress / Status
        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setMinimumHeight(24)
        self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)

        self.activate_btn = QPushButton("🔑 ធ្វើឱ្យសកម្ម (Activate)")
        self.activate_btn.setProperty("class", "PrimaryBtn")
        self.activate_btn.setFixedHeight(42)
        self.activate_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.activate_btn.clicked.connect(self._activate_key)
        btn_bar.addWidget(self.activate_btn)

        close_btn = QPushButton("ចាកចេញ (Exit)")
        close_btn.setProperty("class", "SecondaryBtn")
        close_btn.setFixedHeight(42)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.reject)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def _copy_hwid(self):
        QApplication.clipboard().setText(self.hwid)
        QMessageBox.information(self, "បានចម្លង", "បានចម្លង HWID រួចរាល់! សូមផ្ញើទៅ Admin ដើម្បីបង្កើត License។")

    def _activate_key(self):
        key = self.key_input.text().strip()
        if not key:
            self.status_lbl.setText("⚠ សូមបញ្ចូល License Key!")
            self.status_lbl.setStyleSheet("color: #F87171; font-weight: 600;")
            return

        self.activate_btn.setEnabled(False)
        self.status_lbl.setText("កំពុងផ្ទៀងផ្ទាត់ជាមួយ Google Sheet...")
        self.status_lbl.setStyleSheet("color: #38BDF8; font-weight: 600;")

        self.worker = ActivationWorker(key, self)
        self.worker.finished_signal.connect(self._on_activation_finished)
        self.worker.start()

    def _on_activation_finished(self, result: LicenseResult):
        self.activate_btn.setEnabled(True)
        if result.valid:
            self.is_activated = True
            self.license_info = result
            self.status_lbl.setText("✓ ជោគជ័យ! License ត្រឹមត្រូវ។")
            self.status_lbl.setStyleSheet("color: #4ADE80; font-weight: 700;")
            QMessageBox.information(
                self, "ជោគជ័យ",
                f"ការធ្វើឱ្យសកម្មជោគជ័យ!\nអតិថិជន: {result.customer}\nកាលបរិច្ឆេទផុតកំណត់: {result.expiry}\nសូមរីករាយជាមួយការទស្សនា និងដោនឡូត!"
            )
            self.accept()
        else:
            self.status_lbl.setText(f"✕ បរាជ័យ: {result.message}")
            self.status_lbl.setStyleSheet("color: #EF4444; font-weight: 600;")
