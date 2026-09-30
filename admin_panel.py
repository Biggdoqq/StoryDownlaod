# =============================================================================
# KVN License Admin Panel — GUI Application
# Copyright (c) 2026 KVN Official. All rights reserved.
# =============================================================================
"""
admin_panel.py — PyQt5 Admin GUI for managing KVN license keys.
Build to .exe with:  python build_admin.py
"""

import sys
import os
import csv
import threading
from datetime import datetime
from pathlib import Path

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
        QHeaderView, QFrame, QMessageBox, QSpinBox, QDateEdit,
        QCheckBox, QFileDialog, QStatusBar, QSizePolicy, QAbstractItemView,
        QComboBox, QTabWidget, QTextEdit, QProgressBar
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QSize, QTimer
    from PyQt6.QtGui import (
        QFont, QColor, QIcon, QCursor, QPalette, QLinearGradient,
        QBrush, QPainter, QPixmap
    )
    # PyQt6 Enum compatibility mappings
    Qt.AlignCenter = Qt.AlignmentFlag.AlignCenter
    Qt.PointingHandCursor = Qt.CursorShape.PointingHandCursor
    QHeaderView.Stretch = QHeaderView.ResizeMode.Stretch
    QHeaderView.Fixed = QHeaderView.ResizeMode.Fixed
    QAbstractItemView.SelectRows = QAbstractItemView.SelectionBehavior.SelectRows
    QAbstractItemView.NoEditTriggers = QAbstractItemView.EditTrigger.NoEditTriggers
    if not hasattr(QApplication, "exec_"):
        QApplication.exec_ = QApplication.exec
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
        QHeaderView, QFrame, QMessageBox, QSpinBox, QDateEdit,
        QCheckBox, QFileDialog, QStatusBar, QSizePolicy, QAbstractItemView,
        QComboBox, QTabWidget, QTextEdit, QProgressBar
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QSize, QTimer
    from PyQt5.QtGui import (
        QFont, QColor, QIcon, QCursor, QPalette, QLinearGradient,
        QBrush, QPainter, QPixmap
    )

# ── Import license tools ───────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from license_client import (
    SPREADSHEET_ID, _get_gspread_client, generate_key, get_hwid, get_device_id,
    COL_KEY, COL_CUSTOMER, COL_HWID, COL_EXPIRY,
    COL_ACTIVE, COL_CREATED, COL_LAST_SEEN, COL_MAX_DEVICES,
    SHEET_NAME, get_app_config, set_app_config
)

# ── Current active app (sheet tab) — changed via App Switcher dropdown ─────────
_current_sheet = [SHEET_NAME]   # list so it's mutable from closures

def get_current_sheet() -> str:
    return _current_sheet[0]

def set_current_sheet(name: str):
    _current_sheet[0] = name.strip()

# ─────────────────────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────────────────────
T = {
    "bg_primary":    "#07070F",
    "bg_secondary":  "#0F0F1A",
    "bg_card":       "#12121F",
    "bg_input":      "#0A0A16",
    "accent":        "#7C3AED",
    "accent_hover":  "#6D28D9",
    "accent_light":  "#A78BFA",
    "accent2":       "#06B6D4",
    "accent2_hover": "#0891B2",
    "success":       "#10B981",
    "error":         "#EF4444",
    "warning":       "#F59E0B",
    "text_primary":  "#EEF2FF",
    "text_secondary":"#94A3B8",
    "text_muted":    "#3F4860",
    "border":        "#1E1E35",
    "border_focus":  "#7C3AED",
    "row_even":      "#0F0F1A",
    "row_odd":       "#12121F",
    "row_hover":     "#1A1A30",
    "row_selected":  "#1E1040",
}

GLOBAL_CSS = f"""
    QMainWindow, QWidget {{
        background: {T['bg_primary']};
        color: {T['text_primary']};
        font-family: 'Segoe UI', sans-serif;
    }}
    QTabWidget::pane {{
        border: 1px solid {T['border']};
        background: {T['bg_secondary']};
        border-radius: 10px;
    }}
    QTabBar::tab {{
        background: {T['bg_card']};
        color: {T['text_secondary']};
        padding: 10px 24px;
        border: 1px solid {T['border']};
        border-bottom: none;
        border-radius: 8px 8px 0 0;
        font-size: 13px;
        margin-right: 4px;
    }}
    QTabBar::tab:selected {{
        background: {T['accent']};
        color: #fff;
        font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{
        background: {T['bg_secondary']};
        color: {T['text_primary']};
    }}
    QLineEdit, QSpinBox, QDateEdit, QComboBox {{
        background: {T['bg_input']};
        border: 1.5px solid {T['border']};
        border-radius: 8px;
        color: {T['text_primary']};
        padding: 8px 12px;
        font-size: 13px;
        selection-background-color: {T['accent']};
    }}
    QLineEdit:focus, QSpinBox:focus, QDateEdit:focus {{
        border-color: {T['accent']};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDateEdit::up-button, QDateEdit::down-button {{
        background: {T['bg_card']};
        border: none;
        width: 18px;
    }}
    QDateEdit::drop-down {{ border: none; }}
    QPushButton {{
        background: {T['bg_card']};
        color: {T['text_primary']};
        border: 1px solid {T['border']};
        border-radius: 8px;
        padding: 9px 18px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {T['bg_secondary']}; }}
    QPushButton#btn_primary {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {T['accent']}, stop:1 {T['accent2']});
        color: #fff;
        border: none;
        font-weight: bold;
        font-size: 14px;
        padding: 11px 28px;
    }}
    QPushButton#btn_primary:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {T['accent_hover']}, stop:1 {T['accent2_hover']});
    }}
    QPushButton#btn_primary:disabled {{
        background: {T['bg_card']};
        color: {T['text_muted']};
    }}
    QPushButton#btn_danger {{
        background: transparent;
        color: {T['error']};
        border: 1px solid {T['error']};
        padding: 6px 14px;
        font-size: 12px;
    }}
    QPushButton#btn_danger:hover {{ background: rgba(239,68,68,0.12); }}
    QPushButton#btn_success {{
        background: transparent;
        color: {T['success']};
        border: 1px solid {T['success']};
        padding: 6px 14px;
        font-size: 12px;
    }}
    QPushButton#btn_success:hover {{ background: rgba(16,185,129,0.12); }}
    QPushButton#btn_warning {{
        background: transparent;
        color: {T['warning']};
        border: 1px solid {T['warning']};
        padding: 6px 14px;
        font-size: 12px;
    }}
    QPushButton#btn_warning:hover {{ background: rgba(245,158,11,0.12); }}
    QTableWidget {{
        background: {T['bg_secondary']};
        border: 1px solid {T['border']};
        border-radius: 8px;
        gridline-color: {T['border']};
        font-size: 12px;
        color: {T['text_primary']};
        selection-background-color: {T['row_selected']};
        outline: none;
    }}
    QTableWidget::item {{ padding: 6px 10px; border: none; }}
    QTableWidget::item:selected {{
        background: {T['row_selected']};
        color: {T['text_primary']};
    }}
    QTableWidget::item:hover {{ background: {T['row_hover']}; }}
    QHeaderView::section {{
        background: {T['bg_card']};
        color: {T['text_secondary']};
        padding: 8px 10px;
        border: none;
        border-bottom: 1px solid {T['border']};
        font-size: 11px;
        font-weight: bold;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    QScrollBar:vertical {{
        background: {T['bg_card']}; width: 6px; border-radius: 3px;
    }}
    QScrollBar::handle:vertical {{
        background: {T['text_muted']}; border-radius: 3px; min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QStatusBar {{
        background: {T['bg_card']};
        color: {T['text_secondary']};
        border-top: 1px solid {T['border']};
        font-size: 12px;
        padding: 0 12px;
    }}
    QCheckBox {{ color: {T['text_secondary']}; font-size: 13px; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border: 1.5px solid {T['border']};
        border-radius: 4px;
        background: {T['bg_input']};
    }}
    QCheckBox::indicator:checked {{
        background: {T['accent']};
        border-color: {T['accent']};
    }}
    QLabel#section_title {{
        font-size: 11px;
        font-weight: bold;
        color: {T['text_muted']};
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }}
"""

# ─────────────────────────────────────────────────────────────────────────────
#  WORKER THREADS
# ─────────────────────────────────────────────────────────────────────────────

class WorkerThread(QThread):
    """Generic background worker to keep GUI responsive."""
    finished = pyqtSignal(object)   # result
    error    = pyqtSignal(str)      # error message

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn   = fn
        self._args = args
        self._kw   = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kw)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


def _get_worksheet(sheet_name: str = None):
    """Return the gspread worksheet for the given sheet tab (default = current app)."""
    name = sheet_name or get_current_sheet()
    gc = _get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    # Try to get existing worksheet, create if missing
    try:
        ws = sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=1000, cols=10)
    # Ensure header row
    first_row = ws.row_values(1)
    if not first_row or first_row[0].upper() != "KEY":
        headers = ["Key", "Customer", "HWID", "Expiry", "Active", "Created", "Last Seen", "Max Devices"]
        ws.insert_row(headers, index=1)
        try:
            ws.format("A1:H1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    elif len(first_row) < 8:
        try:
            ws.update_cell(1, 8, "Max Devices")
            ws.format("H1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    return ws


def _list_all_sheet_tabs() -> list:
    """Return all worksheet tab names in the spreadsheet."""
    gc = _get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    return [ws.title for ws in sh.worksheets()]


def _add_new_app_tab(name: str):
    """Create a new sheet tab for a new app."""
    gc = _get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    existing = [ws.title for ws in sh.worksheets()]
    if name in existing:
        raise ValueError(f"Tab '{name}' already exists.")
    ws = sh.add_worksheet(title=name, rows=1000, cols=10)
    headers = ["Key", "Customer", "HWID", "Expiry", "Active", "Created", "Last Seen", "Max Devices"]
    ws.insert_row(headers, index=1)
    try:
        ws.format("A1:H1", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return name


def _fetch_all_licenses():
    ws = _get_worksheet()   # uses current app tab
    return ws.get_all_values()


def _generate_keys_to_sheet(count, expiry, customer, max_devices=1):
    ws = _get_worksheet()   # uses current app tab
    keys = []
    dev_str = "unlimited" if max_devices in (0, 999999) else str(max(1, max_devices))
    for _ in range(count):
        key = generate_key()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        row = [key, customer, "", expiry, "YES", now, "", dev_str]
        ws.append_row(row, value_input_option="USER_ENTERED")
        keys.append(key)
    return keys


def _revoke_key(key):
    ws = _get_worksheet()
    cell = ws.find(key, in_column=COL_KEY)
    if not cell:
        raise ValueError(f"Key not found: {key}")
    ws.update_cell(cell.row, COL_ACTIVE, "NO")
    return key


def _activate_key(key):
    ws = _get_worksheet()
    cell = ws.find(key, in_column=COL_KEY)
    if not cell:
        raise ValueError(f"Key not found: {key}")
    ws.update_cell(cell.row, COL_ACTIVE, "YES")
    return key


def _reset_hwid(key):
    ws = _get_worksheet()
    cell = ws.find(key, in_column=COL_KEY)
    if not cell:
        raise ValueError(f"Key not found: {key}")
    ws.update_cell(cell.row, COL_HWID, "")
    return key


def _set_expiry(key, expiry):
    ws = _get_worksheet()
    cell = ws.find(key, in_column=COL_KEY)
    if not cell:
        raise ValueError(f"Key not found: {key}")
    ws.update_cell(cell.row, COL_EXPIRY, expiry)
    return key


# ─────────────────────────────────────────────────────────────────────────────
#  STATS CARD
# ─────────────────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    def __init__(self, icon, value, label, color):
        super().__init__()
        self.setFixedHeight(90)
        self.setStyleSheet(f"""
            QFrame {{
                background: {T['bg_card']};
                border: 1px solid {T['border']};
                border-radius: 12px;
                border-left: 3px solid {color};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet(f"font-size: 22px; color: {color};")
        self.lbl_val = QLabel(value)
        self.lbl_val.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {T['text_primary']};")
        top.addWidget(lbl_icon)
        top.addStretch()
        top.addWidget(self.lbl_val)
        lay.addLayout(top)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: 11px; color: {T['text_secondary']}; letter-spacing: 0.5px;")
        lay.addWidget(lbl)

    def set_value(self, v):
        self.lbl_val.setText(str(v))


# ─────────────────────────────────────────────────────────────────────────────
#  GENERATE TAB
# ─────────────────────────────────────────────────────────────────────────────

class GenerateTab(QWidget):
    keys_generated = pyqtSignal(list)  # emits list of new keys

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # ── Header ──────────────────────────────────────────────────────────
        lbl_h = QLabel("Generate License Keys")
        lbl_h.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {T['text_primary']};")
        root.addWidget(lbl_h)
        lbl_s = QLabel("Keys will be automatically added to your Google Sheet.")
        lbl_s.setStyleSheet(f"font-size: 12px; color: {T['text_secondary']}; margin-bottom: 6px;")
        root.addWidget(lbl_s)

        # ── Form card ───────────────────────────────────────────────────────
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {T['bg_card']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 20, 24, 20)
        form.setSpacing(14)

        # Customer
        lbl1 = QLabel("CUSTOMER / NOTE")
        lbl1.setObjectName("section_title")
        form.addWidget(lbl1)
        self.edit_customer = QLineEdit()
        self.edit_customer.setPlaceholderText("e.g.  Shop A,  VIP User,  Staff Name ...")
        form.addWidget(self.edit_customer)

        # Count + Max Devices + Expiry row
        row2 = QHBoxLayout()
        row2.setSpacing(14)

        col_count = QVBoxLayout()
        lbl2 = QLabel("NUMBER OF KEYS")
        lbl2.setObjectName("section_title")
        col_count.addWidget(lbl2)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 100)
        self.spin_count.setValue(1)
        self.spin_count.setFixedHeight(38)
        col_count.addWidget(self.spin_count)
        row2.addLayout(col_count)

        col_devices = QVBoxLayout()
        lbl_dev = QLabel("MAX DEVICES (SEATS)")
        lbl_dev.setObjectName("section_title")
        col_devices.addWidget(lbl_dev)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(10)
        self.spin_devices = QSpinBox()
        self.spin_devices.setRange(1, 10000)
        self.spin_devices.setValue(1)
        self.spin_devices.setFixedHeight(38)
        dev_row.addWidget(self.spin_devices)

        self.chk_unlimited_dev = QCheckBox("Unlimited")
        self.chk_unlimited_dev.stateChanged.connect(self._toggle_unlimited_dev)
        dev_row.addWidget(self.chk_unlimited_dev)
        col_devices.addLayout(dev_row)
        row2.addLayout(col_devices)

        col_expiry = QVBoxLayout()
        lbl3 = QLabel("EXPIRY DATE")
        lbl3.setObjectName("section_title")
        col_expiry.addWidget(lbl3)

        exp_row = QHBoxLayout()
        exp_row.setSpacing(10)
        self.chk_lifetime = QCheckBox("Lifetime (No expiry)")
        self.chk_lifetime.setChecked(True)
        self.chk_lifetime.stateChanged.connect(self._toggle_expiry)
        exp_row.addWidget(self.chk_lifetime)
        self.date_expiry = QDateEdit()
        self.date_expiry.setCalendarPopup(True)
        self.date_expiry.setDate(QDate.currentDate().addYears(1))
        self.date_expiry.setFixedHeight(38)
        self.date_expiry.setEnabled(False)
        exp_row.addWidget(self.date_expiry)
        col_expiry.addLayout(exp_row)
        row2.addLayout(col_expiry)

        form.addLayout(row2)
        root.addWidget(card)

        # ── Generate button ──────────────────────────────────────────────────
        self.btn_gen = QPushButton("  Generate Keys")
        self.btn_gen.setObjectName("btn_primary")
        self.btn_gen.setFixedHeight(48)
        self.btn_gen.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_gen.clicked.connect(self._on_generate)
        root.addWidget(self.btn_gen)

        # ── Result area ──────────────────────────────────────────────────────
        lbl_out = QLabel("GENERATED KEYS")
        lbl_out.setObjectName("section_title")
        root.addWidget(lbl_out)

        self.txt_result = QTextEdit()
        self.txt_result.setReadOnly(True)
        self.txt_result.setFixedHeight(160)
        self.txt_result.setStyleSheet(f"""
            QTextEdit {{
                background: {T['bg_input']};
                border: 1px solid {T['border']};
                border-radius: 8px;
                color: {T['accent_light']};
                font-family: Consolas, 'Courier New', monospace;
                font-size: 14px;
                padding: 10px;
                letter-spacing: 1px;
            }}
        """)
        self.txt_result.setPlaceholderText("Keys will appear here after generation...")
        root.addWidget(self.txt_result)

        # Copy all button
        btn_copy = QPushButton("Copy All Keys")
        btn_copy.setCursor(QCursor(Qt.PointingHandCursor))
        btn_copy.clicked.connect(self._copy_keys)
        row_copy = QHBoxLayout()
        row_copy.addStretch()
        row_copy.addWidget(btn_copy)
        root.addLayout(row_copy)

        root.addStretch()

    def _toggle_expiry(self, state):
        self.date_expiry.setEnabled(not state)

    def _toggle_unlimited_dev(self, state):
        self.spin_devices.setEnabled(not state)

    def _on_generate(self):
        customer = self.edit_customer.text().strip()
        if not customer:
            QMessageBox.warning(self, "Warning", "Please enter a Customer / Note name.")
            return

        count  = self.spin_count.value()
        expiry = "lifetime" if self.chk_lifetime.isChecked() else \
                 self.date_expiry.date().toString("yyyy-MM-dd")
        max_dev = 999999 if self.chk_unlimited_dev.isChecked() else self.spin_devices.value()

        self.btn_gen.setEnabled(False)
        self.btn_gen.setText("  Generating...")
        self.txt_result.clear()

        self._worker = WorkerThread(_generate_keys_to_sheet, count, expiry, customer, max_dev)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, keys):
        self.btn_gen.setEnabled(True)
        self.btn_gen.setText("  Generate Keys")
        self.txt_result.setPlainText("\n".join(keys))
        self.keys_generated.emit(keys)

    def _on_error(self, msg):
        self.btn_gen.setEnabled(True)
        self.btn_gen.setText("  Generate Keys")
        QMessageBox.critical(self, "Error", f"Failed to generate keys:\n\n{msg}")

    def _copy_keys(self):
        text = self.txt_result.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copied", "Keys copied to clipboard!")


# ─────────────────────────────────────────────────────────────────────────────
#  LICENSES TABLE TAB
# ─────────────────────────────────────────────────────────────────────────────

class LicensesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows = []
        self._worker   = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # ── Header + stats ───────────────────────────────────────────────────
        lbl_h = QLabel("License Manager")
        lbl_h.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {T['text_primary']};")
        root.addWidget(lbl_h)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.card_total    = StatCard("🔑", "—", "Total Keys",   T['accent_light'])
        self.card_active   = StatCard("✅", "—", "Active",       T['success'])
        self.card_revoked  = StatCard("❌", "—", "Revoked",      T['error'])
        self.card_nodevice = StatCard("📱", "—", "Not Activated",T['warning'])
        for c in (self.card_total, self.card_active, self.card_revoked, self.card_nodevice):
            stats_row.addWidget(c)
        root.addLayout(stats_row)

        # ── Toolbar ─────────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Search key, customer, HWID...")
        self.edit_search.setFixedHeight(36)
        self.edit_search.textChanged.connect(self._filter)
        tb.addWidget(self.edit_search, stretch=3)

        self.combo_filter = QComboBox()
        self.combo_filter.setFixedHeight(36)
        self.combo_filter.addItems(["All Status", "Active Only", "Revoked Only", "Not Activated"])
        self.combo_filter.currentIndexChanged.connect(self._filter)
        tb.addWidget(self.combo_filter, stretch=1)

        btn_refresh = QPushButton("  Refresh")
        btn_refresh.setFixedHeight(36)
        btn_refresh.setCursor(QCursor(Qt.PointingHandCursor))
        btn_refresh.clicked.connect(self.refresh)
        tb.addWidget(btn_refresh)

        btn_export = QPushButton("  Export CSV")
        btn_export.setFixedHeight(36)
        btn_export.setCursor(QCursor(Qt.PointingHandCursor))
        btn_export.clicked.connect(self._export)
        tb.addWidget(btn_export)

        root.addLayout(tb)

        # ── Table ────────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "License Key", "Customer", "Devices", "Expiry", "Status",
            "Created", "Last Seen", "Actions"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 200)
        self.table.setStyleSheet(self.table.styleSheet() + f"""
            QTableWidget {{ alternate-background-color: {T['row_odd']}; }}
        """)
        self.table.setRowHeight(0, 42)
        root.addWidget(self.table)

        # Loading indicator
        self.lbl_loading = QLabel("Loading licenses from Google Sheet...")
        self.lbl_loading.setAlignment(Qt.AlignCenter)
        self.lbl_loading.setStyleSheet(f"color: {T['text_secondary']}; font-size: 13px;")
        self.lbl_loading.hide()
        root.addWidget(self.lbl_loading)

    def refresh(self):
        self.lbl_loading.show()
        self.table.setRowCount(0)
        self._worker = WorkerThread(_fetch_all_licenses)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_load_error)
        self._worker.start()

    def _on_loaded(self, rows):
        self.lbl_loading.hide()
        # Skip header row
        data = rows[1:] if len(rows) > 1 else []
        self._all_rows = data
        self._update_stats(data)
        self._populate(data)

    def _on_load_error(self, msg):
        self.lbl_loading.hide()
        QMessageBox.critical(self, "Connection Error", f"Could not load licenses:\n\n{msg}")

    def _update_stats(self, data):
        total   = len(data)
        active  = sum(1 for r in data if len(r) > 4 and r[4].upper() in ("YES","TRUE","1","Y"))
        revoked = sum(1 for r in data if len(r) > 4 and r[4].upper() not in ("YES","TRUE","1","Y",""))
        no_dev  = sum(1 for r in data if len(r) <= 2 or not r[2].strip())
        self.card_total.set_value(total)
        self.card_active.set_value(active)
        self.card_revoked.set_value(revoked)
        self.card_nodevice.set_value(no_dev)

    def _filter(self):
        q      = self.edit_search.text().strip().lower()
        status = self.combo_filter.currentIndex()  # 0=all,1=active,2=revoked,3=no device
        filtered = []
        for r in self._all_rows:
            active_val = r[4].upper() if len(r) > 4 else ""
            is_active  = active_val in ("YES","TRUE","1","Y")
            is_no_dev  = not r[2].strip() if len(r) > 2 else True
            if status == 1 and not is_active:
                continue
            if status == 2 and is_active:
                continue
            if status == 3 and not is_no_dev:
                continue
            if q and not any(q in cell.lower() for cell in r):
                continue
            filtered.append(r)
        self._populate(filtered)

    def _populate(self, data):
        self.table.setRowCount(len(data))
        for row_idx, row in enumerate(data):
            def _col(i): return row[i].strip() if len(row) > i else ""

            key       = _col(0)
            customer  = _col(1)
            hwid      = _col(2)
            expiry    = _col(3)
            active    = _col(4)
            created   = _col(5)
            last_seen = _col(6)
            max_dev   = _col(7) or "1"

            is_active = active.upper() in ("YES","TRUE","1","Y")

            # Key — monospace
            item_key = QTableWidgetItem(key)
            item_key.setFont(QFont("Consolas", 11))
            item_key.setForeground(QColor(T['accent_light']))
            self.table.setItem(row_idx, 0, item_key)

            self.table.setItem(row_idx, 1, QTableWidgetItem(customer))

            # Devices count & HWIDs
            import re
            hwids = [h.strip() for h in re.split(r"[,;\n]+", hwid) if h.strip()]
            dev_str = f"{len(hwids)} / {max_dev}"
            item_dev = QTableWidgetItem(dev_str)
            item_dev.setTextAlignment(Qt.AlignCenter)
            if len(hwids) == 0:
                item_dev.setForeground(QColor(T['warning']))
            elif max_dev.lower() not in ("unlimited", "0", "999999") and max_dev.isdigit() and len(hwids) >= int(max_dev):
                item_dev.setForeground(QColor(T['accent_light']))
            else:
                item_dev.setForeground(QColor(T['text_primary']))

            tooltip_lines = [f"Devices: {dev_str}"]
            if hwids:
                tooltip_lines.append("Activated Devices:")
                for i_h, h_val in enumerate(hwids, 1):
                    tooltip_lines.append(f"  {i_h}. {h_val}")
            else:
                tooltip_lines.append("No devices activated yet.")
            item_dev.setToolTip("\n".join(tooltip_lines))
            self.table.setItem(row_idx, 2, item_dev)

            self.table.setItem(row_idx, 3, QTableWidgetItem(expiry or "lifetime"))

            # Status badge
            status_text = "Active" if is_active else "Revoked"
            status_color = T['success'] if is_active else T['error']
            item_status = QTableWidgetItem(status_text)
            item_status.setForeground(QColor(status_color))
            item_status.setFont(QFont("Segoe UI", 11, QFont.Bold))
            self.table.setItem(row_idx, 4, item_status)

            self.table.setItem(row_idx, 5, QTableWidgetItem(created))
            self.table.setItem(row_idx, 6, QTableWidgetItem(last_seen or "—"))

            # Action buttons
            cell_widget = QWidget()
            cell_widget.setStyleSheet(f"background: transparent;")
            btn_lay = QHBoxLayout(cell_widget)
            btn_lay.setContentsMargins(4, 2, 4, 2)
            btn_lay.setSpacing(6)

            if is_active:
                btn_toggle = QPushButton("Revoke")
                btn_toggle.setObjectName("btn_danger")
            else:
                btn_toggle = QPushButton("Activate")
                btn_toggle.setObjectName("btn_success")
            btn_toggle.setFixedHeight(28)
            btn_toggle.setCursor(QCursor(Qt.PointingHandCursor))
            btn_toggle.clicked.connect(lambda _, k=key, a=is_active: self._toggle(k, a))
            btn_lay.addWidget(btn_toggle)

            btn_hwid = QPushButton("Reset Dev")
            btn_hwid.setObjectName("btn_warning")
            btn_hwid.setFixedHeight(28)
            btn_hwid.setCursor(QCursor(Qt.PointingHandCursor))
            btn_hwid.clicked.connect(lambda _, k=key: self._reset_hwid(k))
            btn_lay.addWidget(btn_hwid)

            btn_copy = QPushButton("Copy")
            btn_copy.setFixedHeight(28)
            btn_copy.setCursor(QCursor(Qt.PointingHandCursor))
            btn_copy.clicked.connect(lambda _, k=key: QApplication.clipboard().setText(k))
            btn_lay.addWidget(btn_copy)

            self.table.setCellWidget(row_idx, 7, cell_widget)
            self.table.setRowHeight(row_idx, 44)

    def _toggle(self, key, currently_active):
        action = "Revoke" if currently_active else "Re-activate"
        reply  = QMessageBox.question(self, "Confirm",
                    f"{action} license:\n{key}?",
                    QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        fn = _revoke_key if currently_active else _activate_key
        worker = WorkerThread(fn, key)
        worker.finished.connect(lambda _: self.refresh())
        worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        worker.start()

    def _reset_hwid(self, key):
        reply = QMessageBox.question(self, "Confirm",
                    f"Reset device binding for:\n{key}\n\nThis clears all registered devices and frees up seats.",
                    QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        worker = WorkerThread(_reset_hwid, key)
        worker.finished.connect(lambda _: self.refresh())
        worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        worker.start()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Licenses", "kvn_licenses.csv",
                                               "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                headers = ["Key","Customer","HWID","Expiry","Active","Created","Last Seen","Max Devices"]
                writer.writerow(headers)
                writer.writerows(self._all_rows)
            QMessageBox.information(self, "Exported",
                f"Exported {len(self._all_rows)} license(s) to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
#  APP UPDATES TAB
# ─────────────────────────────────────────────────────────────────────────────

class UpdatesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self.load_config()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        lbl_h = QLabel("🚀  App Version & Update Manager")
        lbl_h.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {T['text_primary']};")
        root.addWidget(lbl_h)

        lbl_sub = QLabel("Configure the latest version and download URL for KVN Downloader client apps.")
        lbl_sub.setStyleSheet(f"font-size: 12px; color: {T['text_secondary']};")
        root.addWidget(lbl_sub)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {T['bg_card']};
                border: 1px solid {T['border']};
                border-radius: 12px;
                padding: 16px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(14)

        # Row 1: Latest Version
        r1 = QHBoxLayout()
        lbl_v = QLabel("Latest Version:")
        lbl_v.setFixedWidth(140)
        lbl_v.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {T['text_primary']};")
        self.edit_ver = QLineEdit("1.0.0")
        self.edit_ver.setFixedHeight(36)
        self.edit_ver.setPlaceholderText("e.g. 1.0.1")
        self.edit_ver.setStyleSheet(f"background: {T['bg_input']}; color: {T['text_primary']}; border: 1px solid {T['border']}; border-radius: 6px; padding: 0 10px;")
        r1.addWidget(lbl_v)
        r1.addWidget(self.edit_ver)
        c_lay.addLayout(r1)

        # Row 2: Download URL
        r2 = QHBoxLayout()
        lbl_u = QLabel("Download URL:")
        lbl_u.setFixedWidth(140)
        lbl_u.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {T['text_primary']};")
        self.edit_url = QLineEdit()
        self.edit_url.setFixedHeight(36)
        self.edit_url.setPlaceholderText("Direct link or Google Drive link to KVNDownloader_Setup.exe")
        self.edit_url.setStyleSheet(f"background: {T['bg_input']}; color: {T['text_primary']}; border: 1px solid {T['border']}; border-radius: 6px; padding: 0 10px;")
        r2.addWidget(lbl_u)
        r2.addWidget(self.edit_url)
        c_lay.addLayout(r2)

        # Row 3: Changelog
        lbl_c = QLabel("Changelog / Release Notes:")
        lbl_c.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {T['text_primary']};")
        c_lay.addWidget(lbl_c)

        self.edit_notes = QTextEdit()
        self.edit_notes.setPlaceholderText("1. Bug fixes\n2. Performance improvements...")
        self.edit_notes.setStyleSheet(f"background: {T['bg_input']}; color: {T['text_primary']}; border: 1px solid {T['border']}; border-radius: 6px; padding: 8px;")
        c_lay.addWidget(self.edit_notes, 1)

        # Row 4: Mandatory
        self.chk_mandatory = QCheckBox("Mandatory Update (Force user to update)")
        self.chk_mandatory.setStyleSheet(f"font-size: 12px; color: {T['text_secondary']};")
        c_lay.addWidget(self.chk_mandatory)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_reload = QPushButton("🔄 Reload from Sheet")
        btn_reload.setFixedHeight(38)
        btn_reload.setCursor(QCursor(Qt.PointingHandCursor))
        btn_reload.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['text_secondary']};
                border: 1px solid {T['border']}; border-radius: 6px; padding: 0 14px;
            }}
            QPushButton:hover {{ background: {T['border']}; color: {T['text_primary']}; }}
        """)
        btn_reload.clicked.connect(self.load_config)

        self.btn_save = QPushButton("💾 Save Update to Google Sheets")
        self.btn_save.setFixedHeight(38)
        self.btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {T['accent']}; color: #ffffff;
                border: none; border-radius: 6px; font-weight: bold; padding: 0 20px;
            }}
            QPushButton:hover {{ background: {T['accent_hover']}; }}
        """)
        self.btn_save.clicked.connect(self.save_config)

        btn_row.addWidget(btn_reload)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_save)
        c_lay.addLayout(btn_row)

        root.addWidget(card, stretch=1)

    def _get_target_config_sheet(self) -> str:
        cur = get_current_sheet()
        if "hongguo" in cur.lower():
            return "Hongguo_App_Config"
        return "App_Config"

    def load_config(self):
        worker = WorkerThread(lambda: get_app_config(self._get_target_config_sheet()))
        worker.finished.connect(self._on_loaded)
        worker.start()
        self._worker_load = worker

    def _on_loaded(self, cfg):
        if cfg:
            self.edit_ver.setText(cfg.get("latest_version", "1.0.0"))
            self.edit_url.setText(cfg.get("download_url", ""))
            self.edit_notes.setPlainText(cfg.get("changelog", ""))
            self.chk_mandatory.setChecked(bool(cfg.get("mandatory", False)))

    def save_config(self):
        ver = self.edit_ver.text().strip()
        url = self.edit_url.text().strip()
        notes = self.edit_notes.toPlainText().strip()
        mand = self.chk_mandatory.isChecked()

        if not ver:
            QMessageBox.warning(self, "Error", "Latest version cannot be empty.")
            return

        self.btn_save.setEnabled(False)
        self.btn_save.setText("Saving...")

        target_sheet = self._get_target_config_sheet()
        def _do_save():
            return set_app_config(ver, url, notes, mand, sheet_name=target_sheet)

        worker = WorkerThread(_do_save)
        worker.finished.connect(self._on_saved)
        worker.start()
        self._worker_save = worker

    def _on_saved(self, ok):
        self.btn_save.setEnabled(True)
        self.btn_save.setText("💾 Save Update to Google Sheets")
        if ok:
            QMessageBox.information(self, "Success", "Update configuration saved to Google Sheet successfully!")
        else:
            QMessageBox.warning(self, "Error", "Failed to save update configuration to Google Sheet.")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KVN License Admin Panel")
        self.setMinimumSize(1060, 700)
        self.resize(1160, 750)
        self._build_ui()
        # Load app list then auto-refresh licenses
        QTimer.singleShot(300, self._load_app_list)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            QFrame {{
                background: {T['bg_card']};
                border-bottom: 1px solid {T['border']};
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(24, 0, 20, 0)
        h_lay.setSpacing(12)

        lbl_logo = QLabel("\U0001f510  KVN License Admin")
        lbl_logo.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {T['text_primary']};")
        h_lay.addWidget(lbl_logo)

        h_lay.addStretch()

        # ── App Switcher ───────────────────────────────────────────────────────
        lbl_app = QLabel("App:")
        lbl_app.setStyleSheet(f"font-size: 12px; color: {T['text_secondary']}; font-weight: 600;")
        h_lay.addWidget(lbl_app)

        self.combo_app = QComboBox()
        self.combo_app.setFixedWidth(220)
        self.combo_app.setFixedHeight(34)
        self.combo_app.setStyleSheet(f"""
            QComboBox {{
                background: {T['bg_input']};
                border: 1.5px solid {T['accent']};
                border-radius: 8px;
                color: {T['text_primary']};
                padding: 4px 10px;
                font-size: 13px;
                font-weight: 600;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background: {T['bg_card']};
                color: {T['text_primary']};
                selection-background-color: {T['accent']};
                border: 1px solid {T['border']};
            }}
        """)
        self.combo_app.currentTextChanged.connect(self._on_app_switched)
        h_lay.addWidget(self.combo_app)

        # + New App button
        btn_new_app = QPushButton("+ New App")
        btn_new_app.setFixedHeight(34)
        btn_new_app.setFixedWidth(90)
        btn_new_app.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T['accent_light']};
                border: 1.5px solid {T['accent']};
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: rgba(124,58,237,0.15); }}
        """)
        btn_new_app.setCursor(QCursor(Qt.PointingHandCursor))
        btn_new_app.clicked.connect(self._on_new_app)
        h_lay.addWidget(btn_new_app)

        h_lay.addSpacing(8)
        lbl_copy = QLabel("\u00a9 2026 KVN Official")
        lbl_copy.setStyleSheet(f"font-size: 11px; color: {T['text_muted']};")
        h_lay.addWidget(lbl_copy)

        root.addWidget(header)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.tab_gen      = GenerateTab()
        self.tab_licenses = LicensesTab()
        self.tab_updates  = UpdatesTab()

        self.tabs.addTab(self.tab_gen,      "  Generate Keys  ")
        self.tabs.addTab(self.tab_licenses, "  Manage Licenses  ")
        self.tabs.addTab(self.tab_updates,  "  🚀 App Updates  ")

        self.tab_gen.keys_generated.connect(lambda _: self.tab_licenses.refresh())

        tab_wrap = QWidget()
        tw_lay = QVBoxLayout(tab_wrap)
        tw_lay.setContentsMargins(16, 12, 16, 12)
        tw_lay.addWidget(self.tabs)
        root.addWidget(tab_wrap, stretch=1)

        # ── Status bar ────────────────────────────────────────────────────────
        self.statusBar().showMessage(
            f"  Google Sheet connected  |  {SPREADSHEET_ID[:36]}..."
        )

    # ── App Switcher Logic ─────────────────────────────────────────────────────

    def _load_app_list(self):
        """Load all sheet tabs from Google Sheet into the dropdown."""
        def _fetch():
            return _list_all_sheet_tabs()

        worker = WorkerThread(_fetch)
        worker.finished.connect(self._on_app_list_loaded)
        worker.error.connect(lambda e: (
            self.combo_app.addItem(get_current_sheet()),
            self.tab_licenses.refresh()
        ))
        worker.start()
        self._app_list_worker = worker  # keep reference

    def _on_app_list_loaded(self, tabs):
        self.combo_app.blockSignals(True)
        self.combo_app.clear()
        for tab in tabs:
            self.combo_app.addItem(tab)
        # Select current sheet
        idx = self.combo_app.findText(get_current_sheet())
        if idx >= 0:
            self.combo_app.setCurrentIndex(idx)
        self.combo_app.blockSignals(False)
        self.tab_licenses.refresh()

    def _on_app_switched(self, app_name: str):
        if not app_name:
            return
        set_current_sheet(app_name)
        self.statusBar().showMessage(
            f"  App: {app_name}  |  Google Sheet: {SPREADSHEET_ID[:30]}..."
        )
        self.tab_licenses.refresh()

    def _on_new_app(self):
        """Prompt for new app name and create a new sheet tab."""
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "New App",
            "Enter app name (will become a new Sheet tab):\n"
            "Example: MyApp_Licenses",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        def _create():
            return _add_new_app_tab(name)

        worker = WorkerThread(_create)
        worker.finished.connect(lambda n: (
            self._load_app_list(),
            QTimer.singleShot(2000, lambda: (
                self.combo_app.setCurrentText(n)
            ))
        ))
        worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        worker.start()
        self._new_app_worker = worker


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(GLOBAL_CSS)

    icon_path = Path(__file__).parent / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = AdminWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
