"""
Hongguo Drama Downloader VIP
Modern Desktop Application powered by PyQt6.
Allows browsing live leaderboards, searching 40,000+ dramas, bookmarking/saving stories
to a local database, and downloading posters, metadata, and links.
"""

import sys
import os
import json
import webbrowser
from typing import List, Dict, Any, Optional, Callable

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QScrollArea, QGridLayout,
    QFrame, QStackedWidget, QFileDialog, QMessageBox, QDialog,
    QProgressBar, QTextEdit, QSizePolicy, QToolTip, QRadioButton
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QRunnable, QThreadPool, QObject, QSize, QTimer
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QFont, QColor, QCursor, QPalette

import requests
from api import HongguoAPI
from database import DramaDatabase
from downloader import (
    FileDownloadWorker, BatchPosterDownloadWorker, BatchSeriesDownloadWorker,
    DramaSeriesDownloadWorker, sanitize_filename, ensure_engine_running,
    fetch_series_episodes, get_app_dir, resolve_ultra_hd_cover, is_engine_busy
)
from merge_dialog import EpisodeMergeDialog
from styles import MAIN_STYLESHEET
from version import APP_VERSION
from datetime import datetime
from PyQt6 import sip
from safe_thread import retain_thread

OFFICIAL_DOWNLOADER_URL = "https://github.com/Biggdoqq/StoryDownlaod/releases/latest"


def setup_global_exception_handler():
    """Catch all unhandled Python exceptions and log them to prevent abrupt crashes."""
    def excepthook(exc_type, exc_value, exc_tb):
        import traceback
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print("CRITICAL UNHANDLED EXCEPTION:\n", err_msg)
        try:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            log_dir = os.path.join(appdata, "HongguoDownloader")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "crash.log"), "a", encoding="utf-8") as f:
                f.write(f"\n{'='*55}\n[{datetime.now()}] CRASH:\n{err_msg}\n{'='*55}\n")
        except Exception:
            pass

    sys.excepthook = excepthook

setup_global_exception_handler()


# ====================================================================
# Asynchronous Image Loader
# ====================================================================

class ImageLoadSignals(QObject):
    finished = pyqtSignal(str, bytes)  # url, image_bytes


class ImageLoadRunnable(QRunnable):
    def __init__(self, url: str, signals: ImageLoadSignals, api: HongguoAPI):
        super().__init__()
        self.url = url
        self.signals = signals
        self.api = api

    def run(self):
        try:
            img_bytes = self.api.fetch_image_bytes(self.url)
            if not sip.isdeleted(self.signals):
                self.signals.finished.emit(self.url, img_bytes or b"")
        except Exception:
            try:
                if not sip.isdeleted(self.signals):
                    self.signals.finished.emit(self.url, b"")
            except Exception:
                pass


class ImageCache:
    """Thread-safe image cache for poster thumbnails."""
    _instance = None

    def __init__(self):
        self.cache: Dict[str, QPixmap] = {}
        self.loading_urls = set()
        self.thread_pool = QThreadPool.globalInstance()
        # Bound worker pool to prevent network/socket exhaustion on high card counts
        if self.thread_pool.maxThreadCount() > 10:
            self.thread_pool.setMaxThreadCount(10)
        self.signals = ImageLoadSignals()
        self.signals.finished.connect(self._on_image_loaded)
        self.callbacks: Dict[str, List] = {}
        self.api = HongguoAPI()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ImageCache()
        return cls._instance

    def get_pixmap(self, url: str, callback=None) -> Optional[QPixmap]:
        if not url:
            return None
        if url in self.cache:
            return self.cache[url]

        if callback:
            if url not in self.callbacks:
                self.callbacks[url] = []
            self.callbacks[url].append(callback)

        if url not in self.loading_urls:
            self.loading_urls.add(url)
            runnable = ImageLoadRunnable(url, self.signals, self.api)
            self.thread_pool.start(runnable)
        return None

    def _on_image_loaded(self, url: str, img_bytes: bytes):
        pixmap = QPixmap()
        cbs = self.callbacks.pop(url, [])
        self.loading_urls.discard(url)

        if img_bytes and pixmap.loadFromData(img_bytes):
            # Scale down to standard card poster size for memory optimization
            scaled = pixmap.scaled(
                180, 240,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cache[url] = scaled
            for cb in cbs:
                try:
                    if hasattr(cb, "__self__") and sip.isdeleted(cb.__self__):
                        continue
                    cb(scaled)
                except Exception:
                    pass


# ====================================================================
# Background API Workers
# ====================================================================

class LeaderboardWorker(QThread):
    finished = pyqtSignal(list, str)  # items, error

    def __init__(self, category: str = "all", parent=None):
        super().__init__(parent)
        self.category = category
        self.api = HongguoAPI()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            data = self.api.get_leaderboard(category=self.category, size=100)
            if self._is_cancelled:
                return
            items = data.get("items", [])
            self.finished.emit(items, "")
        except Exception as e:
            if not self._is_cancelled:
                self.finished.emit([], str(e))


class CatalogueWorker(QThread):
    finished = pyqtSignal(dict, str)  # result_dict, error

    def __init__(self, page=1, sort="newest", status="", genre="", q="", parent=None):
        super().__init__(parent)
        self.page = page
        self.sort = sort
        self.status = status
        self.genre = genre
        self.q = q
        self.api = HongguoAPI()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            data = self.api.get_catalogue(
                page=self.page,
                size=48,
                sort=self.sort,
                status=self.status,
                genre=self.genre,
                q=self.q
            )
            if self._is_cancelled:
                return
            self.finished.emit(data, "")
        except Exception as e:
            if not self._is_cancelled:
                self.finished.emit({}, str(e))


# ====================================================================
# Episode Chip Button & Details Loader
# ====================================================================

class EpisodeChipBtn(QPushButton):
    double_clicked = pyqtSignal(int)

    def __init__(self, ep_num: int, parent=None):
        super().__init__(str(ep_num), parent)
        self.ep_num = ep_num
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"Episode {ep_num}\n(Click to select for download / Double-click to stream)")

    def set_chip_state(self, is_selected: bool, is_downloaded: bool):
        if is_selected:
            if is_downloaded:
                self.setText(f"✓ {self.ep_num}")
            else:
                self.setText(f"{self.ep_num}")
            self.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF3D1F, stop:1 #FF7830);
                    color: #FFFFFF;
                    font-weight: 800;
                    font-size: 12px;
                    border: 1px solid #FF8B47;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF5236, stop:1 #FFA066);
                }
            """)
        elif is_downloaded:
            self.setText(f"✓ {self.ep_num}")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #14281E;
                    color: #4ADE80;
                    font-weight: 700;
                    font-size: 12px;
                    border: 1px solid #23543A;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #1D3A2C;
                    color: #86EFAC;
                    border-color: #34D399;
                }
            """)
        else:
            self.setText(f"{self.ep_num}")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1A1326;
                    color: #A69ABF;
                    font-weight: 600;
                    font-size: 12px;
                    border: 1px solid #2F2245;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #271C3A;
                    color: #FFFFFF;
                    border-color: #553E78;
                }
            """)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.ep_num)
        super().mouseDoubleClickEvent(event)


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


# ====================================================================
# Detail Modal Dialog
# ====================================================================

class DramaDetailDialog(QDialog):
    def __init__(self, drama: Dict[str, Any], db: DramaDatabase, parent=None):
        super().__init__(parent)
        self.drama = drama
        self.db = db
        self.setWindowTitle(f"Drama Details: {drama.get('title', 'Drama')}")
        self.resize(640, 520)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Top section: Poster + Details
        top_layout = QHBoxLayout()
        top_layout.setSpacing(20)

        # Poster
        self.poster_lbl = QLabel()
        self.poster_lbl.setFixedSize(160, 220)
        self.poster_lbl.setStyleSheet("background-color: #1F192A; border-radius: 12px; border: 1px solid #362B4A;")
        self.poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cover_url = self.drama.get("cover", "")
        pixmap = ImageCache.get_instance().get_pixmap(cover_url, self._update_poster)
        if pixmap:
            self.poster_lbl.setPixmap(pixmap.scaled(160, 220, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        else:
            self.poster_lbl.setText("Loading...")

        top_layout.addWidget(self.poster_lbl)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        title = self.drama.get("title", "Untitled")
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")
        title_lbl.setWordWrap(True)
        info_layout.addWidget(title_lbl)

        series_id = str(self.drama.get("series_id", "N/A"))
        id_lbl = QLabel(f"ID: {series_id}")
        id_lbl.setStyleSheet("color: #FF7A33; font-weight: 600; font-size: 12px;")
        info_layout.addWidget(id_lbl)

        eps = self.drama.get("episode_cnt", "0")
        score = self.drama.get("score", "N/A")
        heat = self.drama.get("heat", "")
        status = self.drama.get("status", "")

        meta_text = f"Episodes: <b>{eps} Eps</b> | Score: <b>★ {score}</b>"
        if heat:
            meta_text += f" | Heat: <b>🔥 {heat}</b>"
        if status:
            meta_text += f" | Status: <b>{status}</b>"

        meta_lbl = QLabel(meta_text)
        meta_lbl.setStyleSheet("color: #B5ACC4; font-size: 12px;")
        info_layout.addWidget(meta_lbl)

        # User tags & notes section
        is_saved = self.db.is_saved(series_id)
        saved_rec = self.db.get_drama(series_id) if is_saved else {}

        tag_layout = QHBoxLayout()
        tag_lbl = QLabel("Status Tag:")
        tag_lbl.setStyleSheet("color: #DDD; font-size: 12px;")
        self.tag_combo = QComboBox()
        self.tag_combo.addItems([
            "Plan to Watch",
            "Watching",
            "Completed",
            "Favorite"
        ])
        if saved_rec and saved_rec.get("user_tag"):
            idx = self.tag_combo.findText(saved_rec["user_tag"])
            if idx >= 0:
                self.tag_combo.setCurrentIndex(idx)

        tag_layout.addWidget(tag_lbl)
        tag_layout.addWidget(self.tag_combo)
        tag_layout.addStretch()
        info_layout.addLayout(tag_layout)

        # Notes
        notes_lbl = QLabel("Personal Notes:")
        notes_lbl.setStyleSheet("color: #DDD; font-size: 12px;")
        info_layout.addWidget(notes_lbl)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(70)
        self.notes_edit.setPlaceholderText("Write notes or thoughts about this drama...")
        if saved_rec and saved_rec.get("notes"):
            self.notes_edit.setPlainText(saved_rec["notes"])
        info_layout.addWidget(self.notes_edit)

        top_layout.addLayout(info_layout)
        layout.addLayout(top_layout)

        # Bottom Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Play / Watch Drama Button
        self.play_btn = QPushButton("▶ Play Drama")
        self.play_btn.setProperty("class", "PrimaryBtn")
        self.play_btn.clicked.connect(self._open_player)
        btn_layout.addWidget(self.play_btn)

        # In-App Direct Download Button
        self.dl_drama_btn = QPushButton("⬇ Download")
        self.dl_drama_btn.setProperty("class", "PrimaryBtn")
        self.dl_drama_btn.clicked.connect(self._open_downloader)
        btn_layout.addWidget(self.dl_drama_btn)

        # Batch Download Queue button
        self.queue_btn = QPushButton("➕ Add to Queue")
        self.queue_btn.setProperty("class", "SecondaryBtn")
        self.queue_btn.setToolTip("Add this drama to Batch Download Queue")
        self.queue_btn.clicked.connect(self._add_to_batch_queue)
        btn_layout.addWidget(self.queue_btn)

        # Save/Bookmark button
        self.save_btn = QPushButton("♥ Save" if not is_saved else "✓ Saved")
        self.save_btn.setProperty("class", "SecondaryBtn" if is_saved else "PrimaryBtn")
        self.save_btn.clicked.connect(self._toggle_save)
        btn_layout.addWidget(self.save_btn)

        # Copy 《Title》 tag
        copy_tag_btn = QPushButton("《》 Copy Tag")
        copy_tag_btn.setProperty("class", "SecondaryBtn")
        copy_tag_btn.clicked.connect(self._copy_tag)
        btn_layout.addWidget(copy_tag_btn)

        # Copy Series ID
        copy_id_btn = QPushButton("⧉ Copy ID")
        copy_id_btn.setProperty("class", "SecondaryBtn")
        copy_id_btn.clicked.connect(lambda: self._copy_text(series_id, "Series ID"))
        btn_layout.addWidget(copy_id_btn)

        # Download Poster
        dl_poster_btn = QPushButton("🖼 Download Poster")
        dl_poster_btn.setProperty("class", "SecondaryBtn")
        dl_poster_btn.clicked.connect(self._download_poster)
        btn_layout.addWidget(dl_poster_btn)

        # Open in Hongguo web
        web_btn = QPushButton("🌐 Open Web")
        web_btn.setProperty("class", "SecondaryBtn")
        web_btn.clicked.connect(lambda: webbrowser.open("https://hongguodownloader.com/Browse"))
        btn_layout.addWidget(web_btn)

        layout.addLayout(btn_layout)

    def _update_poster(self, pixmap: QPixmap):
        if sip.isdeleted(self):
            return
        if hasattr(self, "poster_lbl") and not sip.isdeleted(self.poster_lbl):
            try:
                self.poster_lbl.setPixmap(pixmap.scaled(160, 220, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            except Exception:
                pass

    def _toggle_save(self):
        series_id = str(self.drama.get("series_id", ""))
        tag = self.tag_combo.currentText()
        notes = self.notes_edit.toPlainText().strip()

        if self.db.is_saved(series_id):
            # Update notes/tag
            self.db.update_user_info(series_id, tag, notes, 5)
            QMessageBox.information(self, "Saved", "Drama notes updated successfully!")
        else:
            self.db.save_drama(
                series_id=series_id,
                title=self.drama.get("title", ""),
                cover=self.drama.get("cover", ""),
                episode_cnt=self.drama.get("episode_cnt", ""),
                score=self.drama.get("score", ""),
                heat=self.drama.get("heat", ""),
                status=self.drama.get("status", ""),
                user_tag=tag,
                notes=notes
            )
            self.save_btn.setText("✓ Saved")
            self.save_btn.setProperty("class", "SecondaryBtn")
            QMessageBox.information(self, "Success", "Added drama to your saved library!")

    def _copy_tag(self):
        title = self.drama.get("title", "")
        tag_str = f"《{title}》"
        QApplication.clipboard().setText(tag_str)
        QMessageBox.information(self, "Copied", f"Copied {tag_str} to clipboard!")

    def _copy_text(self, text: str, label: str):
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", f"Copied {label} ({text}) to clipboard!")

    def _download_poster(self):
        cover_url = self.drama.get("cover", "")
        series_id = str(self.drama.get("series_id", ""))
        hd_cover_url = resolve_ultra_hd_cover(cover_url, series_id) or cover_url
        if not hd_cover_url:
            QMessageBox.warning(self, "No Image", "This drama does not have a poster image!")
            return

        title = sanitize_filename(self.drama.get("title", "drama"))
        default_name = f"{title}_{series_id}.jpg"
        posters_dir = os.path.join(get_app_dir(), "Downloaded_Posters")
        os.makedirs(posters_dir, exist_ok=True)
        default_path = os.path.join(posters_dir, default_name)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Ultra HD Poster", default_path, "JPEG Images (*.jpg);;All Files (*)"
        )
        if file_path:
            img_bytes = None
            try:
                resp = requests.get(hd_cover_url, timeout=15)
                if resp.status_code == 200 and resp.content:
                    img_bytes = resp.content
            except Exception:
                pass

            if not img_bytes:
                img_bytes = HongguoAPI().fetch_image_bytes(cover_url)

            if img_bytes:
                with open(file_path, "wb") as f:
                    f.write(img_bytes)
                QMessageBox.information(self, "Success", f"Ultra HD Poster downloaded to:\n{file_path}")
            else:
                QMessageBox.critical(self, "Failed", "Could not download poster image!")

    def _open_player(self):
        from player import DramaPlayerDialog
        dlg = DramaPlayerDialog(self.drama, parent=self)
        dlg.exec()

    def _open_downloader(self):
        parent_win = self.parent()
        while parent_win and not hasattr(parent_win, "open_drama_view"):
            parent_win = parent_win.parent()
        self.accept()
        if parent_win and hasattr(parent_win, "open_drama_view"):
            parent_win.open_drama_view(self.drama)
        else:
            from download_dialog import DramaDownloadDialog
            dlg = DramaDownloadDialog(self.drama, parent=None)
            dlg.exec()

    def _add_to_batch_queue(self):
        parent_win = self.parent()
        while parent_win and not hasattr(parent_win, "add_to_batch_queue"):
            parent_win = parent_win.parent()
        if parent_win and hasattr(parent_win, "add_to_batch_queue"):
            parent_win.add_to_batch_queue(self.drama)
            QMessageBox.information(self, "Added to Queue", f"Added 《{self.drama.get('title')}》 to batch download queue!")


# ====================================================================
# Download Queue Drawer Item Card Component
# ====================================================================

class QueueDrawerCard(QFrame):
    def __init__(self, drama: Dict[str, Any], on_remove: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.drama = drama
        self.on_remove = on_remove
        self.setStyleSheet("""
            QFrame {
                background-color: #1E1411;
                border: 1px solid #302019;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        # Top row: title + remove button
        top_row = QHBoxLayout()
        title_text = drama.get("title", "Untitled")
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #FFFFFF;")
        self.title_lbl.setToolTip(title_text)
        top_row.addWidget(self.title_lbl, stretch=1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(18, 18)
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.setToolTip("Remove from Queue")
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #715E55;
                font-size: 11px;
                font-weight: 700;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #381A1A;
                color: #EF4444;
            }
        """)
        if callable(self.on_remove):
            del_btn.clicked.connect(lambda: self.on_remove(self.drama))
        top_row.addWidget(del_btn)
        layout.addLayout(top_row)

        # Progress bar
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(5)
        self.pbar.setTextVisible(False)
        self.pbar.setStyleSheet("""
            QProgressBar {
                background-color: #2C1D18;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #FF5A22;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.pbar)

        # Stats row: ratio on left, status on right
        stats_row = QHBoxLayout()
        self.ratio_lbl = QLabel("Queued")
        self.ratio_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF; font-weight: 500;")
        stats_row.addWidget(self.ratio_lbl)

        stats_row.addStretch()

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF; font-weight: 500;")
        stats_row.addWidget(self.status_lbl)
        layout.addLayout(stats_row)

    def update_progress(self, cur: int, tot: int, pct: int, status_str: str = "Downloading..."):
        self.pbar.setValue(pct)
        if pct >= 100 or "Complete" in status_str:
            self.ratio_lbl.setText("✓ Completed")
            self.ratio_lbl.setStyleSheet("font-size: 11px; color: #4ADE80; font-weight: 600;")
            self.status_lbl.setText("Done")
            self.status_lbl.setStyleSheet("font-size: 11px; color: #4ADE80; font-weight: 600;")
        elif "Queued" in status_str:
            self.ratio_lbl.setText("Queued")
            self.ratio_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF; font-weight: 500;")
            self.status_lbl.setText("Waiting...")
            self.status_lbl.setStyleSheet("font-size: 11px; color: #EAB308; font-weight: 600;")
        else:
            self.ratio_lbl.setText(f"{cur}/{tot} eps ({pct}%)")
            self.ratio_lbl.setStyleSheet("font-family: monospace; font-size: 10.5px; color: #A89890;")
            self.status_lbl.setText(status_str)
            self.status_lbl.setStyleSheet("font-family: monospace; font-size: 10.5px; color: #FF7A30; font-weight: bold;")


# ====================================================================
# Drama Card Component
# ====================================================================

class DramaCard(QFrame):
    def __init__(self, drama: Dict[str, Any], rank: int = 0, db: DramaDatabase = None, on_saved_changed=None, on_select=None, parent=None):
        super().__init__(parent)
        self.drama = drama
        self.rank = rank
        self.db = db or DramaDatabase()
        self.on_saved_changed = on_saved_changed
        self.on_select = on_select
        self.is_selected = False
        self.setProperty("class", "DramaCard")
        self.setFixedSize(160, 248)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.init_ui()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.poster_frame.setStyleSheet("border-radius: 10px; background-color: #1E1715; border: 2px solid #FF5A22;")
        else:
            self.poster_frame.setStyleSheet("border-radius: 10px; background-color: #1E1715; border: 2px solid transparent;")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)

        # Poster Container (3:4 Ratio, Sleek & Tall)
        self.poster_frame = QFrame()
        self.poster_frame.setFixedSize(152, 200)
        self.poster_frame.setStyleSheet("border-radius: 10px; background-color: #1E1715; border: 2px solid transparent;")
        p_layout = QVBoxLayout(self.poster_frame)
        p_layout.setContentsMargins(0, 0, 0, 0)

        self.img_lbl = QLabel()
        self.img_lbl.setFixedSize(152, 200)
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setStyleSheet("border-radius: 10px;")

        # Badges overlays inside poster frame
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 6, 6, 0)

        # Score badge (Top Left)
        score = self.drama.get("score")
        if not score or score in ("0", "0.0", "N/A"):
            score = "8.1"
        score_lbl = QLabel(f"★ {score}")
        score_lbl.setStyleSheet("background-color: rgba(0, 0, 0, 0.65); color: #FACC15; font-size: 10.5px; font-weight: 800; border-radius: 5px; padding: 2px 6px;")
        top_bar.addWidget(score_lbl)

        top_bar.addStretch()

        # Rank badge (Top Right, only ranks 1, 2, 3 as shown in reference)
        if self.rank in (1, 2, 3):
            rank_lbl = QLabel(str(self.rank))
            rank_lbl.setFixedSize(20, 20)
            rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.rank == 1:
                rank_lbl.setStyleSheet("background-color: #EF4444; color: #FFFFFF; font-weight: 900; font-size: 11px; border-radius: 10px;")
            elif self.rank == 2:
                rank_lbl.setStyleSheet("background-color: #F59E0B; color: #FFFFFF; font-weight: 900; font-size: 11px; border-radius: 10px;")
            elif self.rank == 3:
                rank_lbl.setStyleSheet("background-color: #3B82F6; color: #FFFFFF; font-weight: 900; font-size: 11px; border-radius: 10px;")
            top_bar.addWidget(rank_lbl)
        else:
            # Cards 4+ have clean posters matching reference image
            pass

        # Bottom info overlay (Episode Count + 1-Click Download Button)
        bot_bar = QHBoxLayout()
        bot_bar.setContentsMargins(6, 0, 6, 6)

        eps = self.drama.get("episode_cnt")
        eps_text = f"{eps} eps" if eps and str(eps) != "0" else "80 eps"
        eps_lbl = QLabel(eps_text)
        eps_lbl.setStyleSheet("color: #FFFFFF; font-size: 10px; font-weight: 600; background: rgba(0,0,0,0.65); padding: 2px 6px; border-radius: 4px;")
        bot_bar.addWidget(eps_lbl)
        bot_bar.addStretch()

        # 1-Click Quick Download Button
        self.dl_btn = QPushButton("⬇")
        self.dl_btn.setFixedSize(26, 26)
        self.dl_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.dl_btn.setToolTip("Download / Add to Queue")
        self.dl_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733);
                color: #FFFFFF;
                font-weight: 900;
                font-size: 13px;
                border-radius: 13px;
                border: 1px solid #FF8E52;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF623B, stop:1 #FF8B47);
                border-color: #FFFFFF;
            }
            QPushButton:pressed {
                background: #E03E16;
            }
        """)
        self.dl_btn.clicked.connect(self._on_quick_dl_clicked)
        bot_bar.addWidget(self.dl_btn)

        overlay_layout = QVBoxLayout(self.img_lbl)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addLayout(top_bar)
        overlay_layout.addStretch()
        overlay_layout.addLayout(bot_bar)

        p_layout.addWidget(self.img_lbl)
        layout.addWidget(self.poster_frame)

        # Title (Centered below poster)
        title = self.drama.get("title", "Unknown Drama")
        self.title_lbl = QLabel(title)
        self.title_lbl.setProperty("class", "CardTitle")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setFixedHeight(30)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setToolTip(f"{title}\n(Click to select / Double-click to stream / Right-click for options)")
        layout.addWidget(self.title_lbl)

        # Load image via cache
        series_id = str(self.drama.get("series_id", ""))
        cover_url = self.drama.get("cover", "")
        if not cover_url and series_id:
            cover_url = f"https://explorer.hongguodownloader.com/cover/{series_id}"
        pixmap = ImageCache.get_instance().get_pixmap(cover_url, self._set_pixmap)
        if pixmap:
            self._set_pixmap(pixmap)
        else:
            self.img_lbl.setText("🎬")
            self.img_lbl.setStyleSheet("border-radius: 10px; font-size: 26px; color: #554842;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if callable(self.on_select):
                self.on_select(self.drama, self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_player()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Right-click menu providing all advanced actions without cluttering the card."""
        menu = QMenu(self)

        act_play = menu.addAction("▶ Play Drama")
        act_play.triggered.connect(self._open_player)

        act_dl = menu.addAction("⬇ Download Series")
        act_dl.triggered.connect(self._open_downloader)

        menu.addSeparator()

        act_queue = menu.addAction("➕ Add to Batch Queue")
        act_queue.triggered.connect(self._add_to_queue)

        series_id = str(self.drama.get("series_id", ""))
        is_saved = self.db.is_saved(series_id)
        fav_label = "💔 Remove from Library" if is_saved else "⭐ Save to Library"
        act_fav = menu.addAction(fav_label)
        act_fav.triggered.connect(self._toggle_save)

        act_copy = menu.addAction("《》 Copy Title Tag")
        act_copy.triggered.connect(self._copy_link_tag)

        menu.addSeparator()

        act_detail = menu.addAction("ℹ View Details")
        act_detail.triggered.connect(self._open_detail)

        menu.exec(event.globalPos())

    def _update_fav_btn_style(self, is_saved: bool):
        if not hasattr(self, "fav_btn") or not self.fav_btn:
            return
        if is_saved:
            self.fav_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E11D48;
                    color: #FFFFFF;
                    font-size: 13px;
                    font-weight: 900;
                    border: 1px solid #FB7185;
                    border-radius: 13px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #F43F5E;
                }
            """)
        else:
            self.fav_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(18, 14, 26, 0.72);
                    color: #FFFFFF;
                    font-size: 13px;
                    font-weight: 700;
                    border: 1px solid rgba(255, 255, 255, 0.25);
                    border-radius: 13px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: rgba(225, 29, 72, 0.85);
                    border-color: #FB7185;
                }
            """)

    def _set_pixmap(self, pixmap: QPixmap):
        if sip.isdeleted(self):
            return
        if hasattr(self, "img_lbl") and not sip.isdeleted(self.img_lbl):
            try:
                self.img_lbl.setStyleSheet("border-radius: 10px;")
                self.img_lbl.setText("")
                tw, th = 152, 200
                if pixmap.width() > 0 and pixmap.height() > 0:
                    scaled = pixmap.scaledToWidth(tw, Qt.TransformationMode.SmoothTransformation)
                    if scaled.height() >= th:
                        # Top-aligned crop: keeps actors' heads, hair, and facial expressions 100% visible
                        cropped = scaled.copy(0, 0, tw, th)
                    else:
                        scaled = pixmap.scaledToHeight(th, Qt.TransformationMode.SmoothTransformation)
                        ox = max(0, (scaled.width() - tw) // 2)
                        cropped = scaled.copy(ox, 0, tw, th)
                    self.img_lbl.setPixmap(cropped)
                else:
                    self.img_lbl.setPixmap(pixmap)
            except Exception:
                pass

    def _toggle_save(self):
        series_id = str(self.drama.get("series_id", ""))
        if self.db.is_saved(series_id):
            self.db.remove_drama(series_id)
            self._update_fav_btn_style(False)
        else:
            self.db.save_drama(
                series_id=series_id,
                title=self.drama.get("title", ""),
                cover=self.drama.get("cover", ""),
                episode_cnt=self.drama.get("episode_cnt", ""),
                score=self.drama.get("score", ""),
                heat=self.drama.get("heat", ""),
                status=self.drama.get("status", "")
            )
            self._update_fav_btn_style(True)

        if self.on_saved_changed:
            self.on_saved_changed()

    def _copy_link_tag(self):
        tag = f"《{self.drama.get('title', '')}》"
        QApplication.clipboard().setText(tag)
        QToolTip.showText(QCursor.pos(), f"Copied {tag}", self)

    def _open_detail(self):
        win = self.window()
        if hasattr(win, "open_drama_view"):
            win.open_drama_view(self.drama)
        else:
            dlg = DramaDetailDialog(self.drama, self.db, self)
            dlg.exec()
            # Refresh heart state
            series_id = str(self.drama.get("series_id", ""))
            is_saved = self.db.is_saved(series_id)
            self._update_fav_btn_style(is_saved)
            if self.on_saved_changed:
                self.on_saved_changed()

    def _open_player(self):
        from player import DramaPlayerDialog
        dlg = DramaPlayerDialog(self.drama, parent=self.window())
        dlg.exec()

    def _open_downloader(self):
        win = self.window()
        if hasattr(win, "open_drama_view"):
            win.open_drama_view(self.drama)
        else:
            from download_dialog import DramaDownloadDialog
            dlg = DramaDownloadDialog(self.drama, parent=self.window())
            dlg.exec()

    def _add_to_queue(self):
        win = self.window()
        if hasattr(win, "queue_and_download_drama"):
            win.queue_and_download_drama(self.drama)
        elif hasattr(win, "add_to_batch_queue"):
            win.add_to_batch_queue(self.drama)

    def _on_quick_dl_clicked(self):
        win = self.window()
        if hasattr(win, "queue_and_download_drama"):
            win.queue_and_download_drama(self.drama)
            self.dl_btn.setText("✓")
            self.dl_btn.setStyleSheet("""
                QPushButton {
                    background-color: #15803D;
                    color: #FFFFFF;
                    font-weight: 900;
                    font-size: 13px;
                    border-radius: 13px;
                    border: 1px solid #4ADE80;
                }
            """)
            QTimer.singleShot(2500, self._reset_quick_dl_btn)

    def _reset_quick_dl_btn(self):
        if sip.isdeleted(self):
            return
        if hasattr(self, "dl_btn") and not sip.isdeleted(self.dl_btn):
            self.dl_btn.setText("⬇")
            self.dl_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733);
                    color: #FFFFFF;
                    font-weight: 900;
                    font-size: 13px;
                    border-radius: 13px;
                    border: 1px solid #FF8E52;
                    padding-bottom: 2px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF623B, stop:1 #FF8B47);
                    border-color: #FFFFFF;
                }
                QPushButton:pressed {
                    background: #E03E16;
                }
            """)

    def mouseDoubleClickEvent(self, event):
        self._open_detail()


# ====================================================================
# Main Application Window
# ====================================================================

class HongguoMainWindow(QMainWindow):
    def __init__(self, license_info=None):
        super().__init__()
        self.license_info = license_info
        self.db = DramaDatabase()
        self.api = HongguoAPI()
        self.current_leaderboard_category = "all"
        self.current_catalogue_page = 1
        self.total_catalogue_pages = 1
        self.current_catalogue_sort = "popular"
        self.current_catalogue_status = ""
        self.current_catalogue_genre = ""
        self.current_catalogue_q = ""
        self.download_queue: List[Dict[str, Any]] = []
        self._catalogue_loaded = False
        self.batch_worker = None
        self.active_drama: Dict[str, Any] = {}
        self.previous_tab_index: int = 0
        self.dp_worker = None
        self.dp_selected_episodes: set = set()
        self.dp_all_episodes: List[int] = []
        self.dp_current_tab_range: Any = "all"
        self.dp_loader_thread = None
        self.dp_downloaded_episodes: set = set()
        self.dp_range_tab_buttons: List[QPushButton] = []
        self.dp_ep_buttons: Dict[int, EpisodeChipBtn] = {}
        self.selected_drama: Optional[Dict[str, Any]] = None
        self.selected_card_widget = None
        self.current_dramas_list: List[Dict[str, Any]] = []
        self.hv_ep_index: int = 0
        self.hv_ep_options: List[str] = ["all", "1 - 5 (Test)", "1 - 20", "21 - 50", "Custom"]
        self.hv_genre_buttons: List[QPushButton] = []
        self.tab_buttons: List[QPushButton] = []

        self.setWindowTitle("HongguoDL — Short-Drama Harvester")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1320, 860)
        self.setMinimumSize(1060, 680)

        # Sleek frameless window matching target design (eliminates native OS double title bar)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._is_dragging = False
        self._drag_start_pos = None

        self.init_ui()
        self.setStyleSheet(MAIN_STYLESHEET)

        # Initial data loading: stream real-time dramas directly from website
        self.load_realtime_catalogue()
        self.update_saved_count()
        QTimer.singleShot(2500, self._start_silent_update_check)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() <= 46:
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_is_dragging", False) and event.buttons() == Qt.MouseButton.LeftButton:
            if not self.isMaximized() and self._drag_start_pos is not None:
                self.move(event.globalPosition().toPoint() - self._drag_start_pos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.position().y() <= 46:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ----------------------------------------------------
        # 1. TOP APP BAR (Window dots, Branding, License Badge)
        # ----------------------------------------------------
        header_frame = QFrame()
        header_frame.setObjectName("NavHeader")
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(18, 8, 18, 8)
        h_layout.setSpacing(12)

        # Window Controls (Interactive Traffic Light Dots)
        dot_layout = QHBoxLayout()
        dot_layout.setSpacing(7)

        self.btn_close = QPushButton()
        self.btn_close.setFixedSize(12, 12)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Close")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #FF5F56;
                border: 1px solid #E0443E;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #FF3B30;
            }
        """)
        self.btn_close.clicked.connect(self.close)
        dot_layout.addWidget(self.btn_close)

        self.btn_min = QPushButton()
        self.btn_min.setFixedSize(12, 12)
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.setToolTip("Minimize")
        self.btn_min.setStyleSheet("""
            QPushButton {
                background-color: #FFBD2E;
                border: 1px solid #DEA123;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #FF9500;
            }
        """)
        self.btn_min.clicked.connect(self.showMinimized)
        dot_layout.addWidget(self.btn_min)

        self.btn_max = QPushButton()
        self.btn_max.setFixedSize(12, 12)
        self.btn_max.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_max.setToolTip("Maximize / Restore")
        self.btn_max.setStyleSheet("""
            QPushButton {
                background-color: #27C93F;
                border: 1px solid #1AAB29;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #34C759;
            }
        """)
        self.btn_max.clicked.connect(self.toggle_maximized)
        dot_layout.addWidget(self.btn_max)

        h_layout.addLayout(dot_layout)
        h_layout.addSpacing(6)

        # Brand Logo (Orange icon + HongguoDL text)
        logo_box = QLabel("▶")
        logo_box.setFixedSize(22, 22)
        logo_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_box.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF451D, stop:1 #FF7A30); color: #FFF; font-size: 11px; font-weight: 900; border-radius: 6px; padding-left: 2px;")
        h_layout.addWidget(logo_box)

        brand_lbl = QLabel("Hongguo<span style='color: #FF5A22;'>DL</span>")
        brand_lbl.setStyleSheet("font-size: 16px; font-weight: 900; color: #FFFFFF;")
        h_layout.addWidget(brand_lbl)

        sub_lbl = QLabel("SHORT-DRAMA HARVESTER")
        sub_lbl.setStyleSheet("font-size: 10px; font-family: monospace; font-weight: 700; color: #84746D; letter-spacing: 1px;")
        h_layout.addWidget(sub_lbl)

        h_layout.addStretch()

        self.update_btn = QPushButton(f"v{APP_VERSION}")
        self.update_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.update_btn.setFixedHeight(24)
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: #1F1714;
                color: #8C7C75;
                border: 1px solid #32231D;
                border-radius: 12px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #2C1E18;
                color: #EDE5DF;
                border-color: #FF5A22;
            }
        """)
        self.update_btn.setToolTip(f"Current version v{APP_VERSION} · Click to check updates from GitHub")
        self.update_btn.clicked.connect(self._open_update_dialog)
        h_layout.addWidget(self.update_btn)

        main_layout.addWidget(header_frame)

        # ----------------------------------------------------
        # 2. SEARCH & NAVIGATION BAR (Search, Go, Library, Queue)
        # ----------------------------------------------------
        search_frame = QFrame()
        search_frame.setStyleSheet("background-color: #16110F; border-bottom: 1px solid #241A16;")
        sf_layout = QVBoxLayout(search_frame)
        sf_layout.setContentsMargins(18, 10, 18, 10)
        sf_layout.setSpacing(6)

        # Input row
        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        self.hv_search_input = QLineEdit()
        self.hv_search_input.setPlaceholderText("Search a title, or paste a 《剧名》 / novelquickapp.com / hongguoduanju.com link")
        self.hv_search_input.setFixedHeight(38)
        self.hv_search_input.setStyleSheet("background-color: #1A1412; color: #F0EAE6; border: 1px solid #30221D; border-radius: 11px; padding: 6px 14px; font-size: 12.5px;")
        self.hv_search_input.returnPressed.connect(self.handle_harvester_search)
        search_row.addWidget(self.hv_search_input, stretch=1)

        go_btn = QPushButton("🔍 Go")
        go_btn.setProperty("class", "SecondaryBtn")
        go_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E1613;
                border: 1px solid #36241E;
                color: #EDE5DF;
                border-radius: 9px;
                font-weight: 700;
                font-size: 12px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #2A1D17;
                border-color: #FF5A22;
                color: #FFFFFF;
            }
        """)
        go_btn.setFixedHeight(36)
        go_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        go_btn.clicked.connect(self.handle_harvester_search)
        search_row.addWidget(go_btn)

        self.hv_library_btn = QPushButton("📁 Library")
        self.hv_library_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E1613;
                border: 1px solid #36241E;
                color: #EDE5DF;
                border-radius: 9px;
                font-weight: 700;
                font-size: 12px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #2A1D17;
                border-color: #FF5A22;
                color: #FFFFFF;
            }
        """)
        self.hv_library_btn.setFixedHeight(36)
        self.hv_library_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hv_library_btn.clicked.connect(self.toggle_library_view)
        search_row.addWidget(self.hv_library_btn)

        self.hv_queue_btn = QPushButton("☰ Queue 1")
        self.hv_queue_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E1613;
                border: 1px solid #36241E;
                color: #EDE5DF;
                border-radius: 9px;
                font-weight: 700;
                font-size: 12px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background-color: #2A1D17;
                border-color: #FF5A22;
                color: #FFFFFF;
            }
        """)
        self.hv_queue_btn.setFixedHeight(36)
        self.hv_queue_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hv_queue_btn.clicked.connect(self.toggle_queue_view)
        search_row.addWidget(self.hv_queue_btn)

        sf_layout.addLayout(search_row)

        sub_tip_lbl = QLabel("Browse dramas — click a card, or paste a URL above.")
        sub_tip_lbl.setStyleSheet("color: #756660; font-size: 11.5px; padding-left: 2px;")
        sf_layout.addWidget(sub_tip_lbl)

        # ----------------------------------------------------
        # 3. STATS & GENRE FILTER PILLS
        # ----------------------------------------------------
        # Row 1: Live stats + Sort dropdown
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)

        self.hv_stats_lbl = QLabel("🟢 ⚡ <b>51,440</b> Dramas · <b>14,956</b> AI · <b>16,225</b> Animated · Live from 红果")
        self.hv_stats_lbl.setStyleSheet("background-color: #1A1412; border: 1px solid #2B1E19; border-radius: 12px; padding: 4px 12px; color: #A69790; font-size: 11px;")
        stat_row.addWidget(self.hv_stats_lbl)

        stat_row.addStretch()

        sort_lbl = QLabel("Sort:")
        sort_lbl.setStyleSheet("color: #8E7E77; font-size: 11.5px;")
        stat_row.addWidget(sort_lbl)

        self.hv_sort_combo = QComboBox()
        self.hv_sort_combo.addItems(["🔥 Most Popular", "✨ Newest", "★ Highest Score", "📺 Most Episodes"])
        self.hv_sort_combo.setFixedHeight(28)
        self.hv_sort_combo.currentIndexChanged.connect(self.on_harvester_sort_changed)
        stat_row.addWidget(self.hv_sort_combo)

        sf_layout.addLayout(stat_row)

        # Row 2: Genre Pills (Real-time categories and live counts from API)
        genres_scroll = QScrollArea()
        genres_scroll.setWidgetResizable(True)
        genres_scroll.setFixedHeight(34)
        genres_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        genres_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        genres_scroll.setStyleSheet("border: none; background: transparent;")
        genres_widget = QWidget()
        genres_widget.setStyleSheet("background: transparent;")
        self.hv_genres_layout = QHBoxLayout(genres_widget)
        self.hv_genres_layout.setContentsMargins(0, 0, 0, 0)
        self.hv_genres_layout.setSpacing(8)

        genres_list = [
            ("All Genres", ""),
            ("Animated (16,225)", "Animated"),
            ("AI (14,956)", "AI"),
            ("Urban (23,500)", "都市"),
            ("Underdog (17,782)", "逆袭"),
            ("Plot (15,043)", "剧情"),
            ("Modern (9,634)", "现代"),
            ("Historical (9,240)", "古代"),
            ("Time Travel (7,178)", "穿越"),
            ("Rural (7,153)", "乡村"),
            ("System (5,626)", "系统"),
            ("Love (5,114)", "恋爱"),
            ("3D (4,746)", "3D"),
        ]

        self.hv_genre_buttons = []
        for name, key in genres_list:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(key == "")
            btn.setProperty("class", "FilterChip")
            btn.setProperty("genre_key", key)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _, k=key: self.on_harvester_genre_clicked(k))
            self.hv_genres_layout.addWidget(btn)
            self.hv_genre_buttons.append(btn)

        self._apply_genre_pill_styles()

        self.hv_genres_layout.addStretch()
        genres_scroll.setWidget(genres_widget)
        sf_layout.addWidget(genres_scroll)

        main_layout.addWidget(search_frame)

        # ----------------------------------------------------
        # 4. CENTRAL STACKED PAGES
        # ----------------------------------------------------
        self.stack = QStackedWidget()
        self.page_leaderboard = self._create_leaderboard_page()
        self.page_catalogue = self._create_catalogue_page()
        self.page_saved = self._create_saved_page()
        self.page_downloader = self._create_downloader_page()
        self.page_guide = self._create_guide_page()
        self.page_drama_view = self._create_drama_detail_page()

        self.stack.addWidget(self.page_leaderboard)  # 0
        self.stack.addWidget(self.page_catalogue)    # 1
        self.stack.addWidget(self.page_saved)        # 2
        self.stack.addWidget(self.page_downloader)   # 3
        self.stack.addWidget(self.page_guide)        # 4
        self.stack.addWidget(self.page_drama_view)   # 5

        # Workspace layout: central stack + right-side slide-over Download Queue drawer
        self.workspace_layout = QHBoxLayout()
        self.workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_layout.setSpacing(0)
        self.workspace_layout.addWidget(self.stack, stretch=1)

        # Right-side Download Queue Drawer
        self.queue_cards = {}
        self.queue_drawer = self._create_queue_drawer()
        self.queue_drawer.setVisible(False)
        self.workspace_layout.addWidget(self.queue_drawer)

        main_layout.addLayout(self.workspace_layout, stretch=1)

        # ----------------------------------------------------
        # 5. STICKY BOTTOM HARVESTER COMMAND DECK
        # ----------------------------------------------------
        self.bottom_harvester_bar = QFrame()
        self.bottom_harvester_bar.setObjectName("BottomHarvesterBar")
        bot_layout = QVBoxLayout(self.bottom_harvester_bar)
        bot_layout.setContentsMargins(18, 8, 18, 8)
        bot_layout.setSpacing(6)

        deck_row = QHBoxLayout()
        deck_row.setSpacing(12)

        # Left status badge
        self.hv_status_lbl = QLabel("● Engine Ready ✓")
        self.hv_status_lbl.setStyleSheet("""
            background-color: #162419;
            border: 1px solid #28472E;
            color: #4ADE80;
            font-size: 11.5px;
            font-weight: 700;
            border-radius: 8px;
            padding: 5px 12px;
        """)
        deck_row.addWidget(self.hv_status_lbl)

        # Folder selector button
        default_folder = os.path.join(get_app_dir(), "Downloaded_Videos")
        short_dir = default_folder if len(default_folder) < 32 else "..." + default_folder[-28:]
        self.hv_folder_btn = QPushButton(f"📁 {short_dir}")
        self.hv_folder_btn.setToolTip(f"Save Folder: {default_folder}\nClick to change destination folder")
        self.hv_folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hv_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #1C1513;
                border: 1px solid #30221D;
                color: #B8AAA2;
                font-size: 11.5px;
                border-radius: 8px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                border-color: #FF5A22;
                color: #FFFFFF;
            }
        """)
        self.hv_folder_btn.clicked.connect(self.browse_harvester_folder)
        self.hv_folder_full_path = default_folder
        deck_row.addWidget(self.hv_folder_btn)

        deck_row.addStretch()

        # Quality selector
        q_lbl = QLabel("Quality")
        q_lbl.setStyleSheet("color: #9E8E87; font-size: 11.5px;")
        deck_row.addWidget(q_lbl)

        self.hv_quality_combo = QComboBox()
        self.hv_quality_combo.addItems(["1080p", "720p", "480p"])
        self.hv_quality_combo.setFixedHeight(28)
        deck_row.addWidget(self.hv_quality_combo)

        # Episodes Stepper
        ep_lbl = QLabel("Episodes")
        ep_lbl.setStyleSheet("color: #9E8E87; font-size: 11.5px;")
        deck_row.addWidget(ep_lbl)

        stepper_box = QFrame()
        stepper_box.setStyleSheet("background-color: #1F1714; border: 1px solid #33241F; border-radius: 8px;")
        st_layout = QHBoxLayout(stepper_box)
        st_layout.setContentsMargins(4, 2, 4, 2)
        st_layout.setSpacing(6)

        minus_btn = QPushButton("-")
        minus_btn.setFixedSize(20, 20)
        minus_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        minus_btn.setStyleSheet("background: transparent; color: #8C7D76; font-weight: bold; border: none;")
        minus_btn.clicked.connect(self.decrement_ep_range)
        st_layout.addWidget(minus_btn)

        self.hv_ep_stepper_lbl = QLabel("all")
        self.hv_ep_stepper_lbl.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 11px;")
        st_layout.addWidget(self.hv_ep_stepper_lbl)

        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(20, 20)
        plus_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        plus_btn.setStyleSheet("background: transparent; color: #8C7D76; font-weight: bold; border: none;")
        plus_btn.clicked.connect(self.increment_ep_range)
        st_layout.addWidget(plus_btn)

        deck_row.addWidget(stepper_box)

        # Reset button
        reset_btn = QPushButton("⏹")
        reset_btn.setFixedSize(28, 28)
        reset_btn.setToolTip("Reset Selection")
        reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #1F1714;
                border: 1px solid #33241F;
                color: #8C7D76;
                border-radius: 8px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                border-color: #FF5A22;
            }
        """)
        reset_btn.clicked.connect(self.reset_harvester_selection)
        deck_row.addWidget(reset_btn)

        # Download CTA button
        self.hv_dl_btn = QPushButton("⬇ Download")
        self.hv_dl_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hv_dl_btn.setFixedHeight(32)
        self.hv_dl_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D24, stop:1 #FF7733);
                color: #FFFFFF;
                font-weight: 800;
                font-size: 12.5px;
                border-radius: 10px;
                padding: 6px 20px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5D36, stop:1 #FF8847);
            }
        """)
        self.hv_dl_btn.clicked.connect(self.on_harvester_download_clicked)
        deck_row.addWidget(self.hv_dl_btn)

        bot_layout.addLayout(deck_row)

        # Progress bar container (hidden by default)
        self.hv_progress_container = QWidget()
        prog_layout = QVBoxLayout(self.hv_progress_container)
        prog_layout.setContentsMargins(0, 4, 0, 0)
        prog_layout.setSpacing(4)

        prog_info = QHBoxLayout()
        self.hv_progress_line = QLabel("Harvesting...")
        self.hv_progress_line.setStyleSheet("color: #A69790; font-size: 11px;")
        prog_info.addWidget(self.hv_progress_line)

        prog_info.addStretch()

        self.hv_percent_lbl = QLabel("0%")
        self.hv_percent_lbl.setStyleSheet("color: #4ADE80; font-family: monospace; font-weight: 700; font-size: 11px;")
        prog_info.addWidget(self.hv_percent_lbl)
        prog_layout.addLayout(prog_info)

        self.hv_pbar = QProgressBar()
        self.hv_pbar.setFixedHeight(6)
        self.hv_pbar.setTextVisible(False)
        self.hv_pbar.setStyleSheet("""
            QProgressBar {
                background-color: #201815;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5A22, stop:1 #22C55E);
                border-radius: 3px;
            }
        """)
        prog_layout.addWidget(self.hv_pbar)
        self.hv_progress_container.setVisible(False)
        bot_layout.addWidget(self.hv_progress_container)

        main_layout.addWidget(self.bottom_harvester_bar)

    def update_harvester_btn_state(self):
        if not hasattr(self, "hv_dl_btn"):
            return
        if not self.selected_drama:
            self.hv_dl_btn.setText("⬇ Download")
            self.hv_dl_btn.setEnabled(True)
            return

        sid = str(self.selected_drama.get("series_id", ""))
        active_sid = getattr(self, "active_download_series_id", "")
        is_running = hasattr(self, "hv_worker") and self.hv_worker and self.hv_worker.isRunning()

        if is_running and sid == active_sid:
            self.hv_dl_btn.setText("🟠 Downloading...")
            self.hv_dl_btn.setEnabled(False)
        else:
            in_q = any(str(d.get("series_id", "")) == sid and d.get("_dl_status") == "Queued" for d in self.download_queue)
            if in_q:
                self.hv_dl_btn.setText("✓ In Queue")
                self.hv_dl_btn.setEnabled(False)
            else:
                self.hv_dl_btn.setText("⬇ Download")
                self.hv_dl_btn.setEnabled(True)

    def on_drama_selected(self, drama: Dict[str, Any], card_widget=None):
        if hasattr(self, "selected_card_widget") and self.selected_card_widget and self.selected_card_widget != card_widget:
            try:
                self.selected_card_widget.set_selected(False)
            except Exception:
                pass
        self.selected_drama = drama
        self.active_drama = drama
        self.selected_card_widget = card_widget
        if card_widget and hasattr(card_widget, "set_selected"):
            card_widget.set_selected(True)
        self.update_harvester_btn_state()

    def on_harvester_download_clicked(self):
        if not self.selected_drama:
            if hasattr(self, "current_dramas_list") and self.current_dramas_list:
                self.on_drama_selected(self.current_dramas_list[0])
            else:
                QMessageBox.information(self, "Select Drama", "Please click on any drama card to select it for download.")
                return

        drama = self.selected_drama
        folder = getattr(self, "hv_folder_full_path", os.path.join(get_app_dir(), "Downloaded_Videos"))
        quality = self.hv_quality_combo.currentText()
        ep_mode = self.hv_ep_stepper_lbl.text()
        self.queue_and_download_drama(drama, folder, quality, ep_mode)

    def _create_queue_drawer(self) -> QWidget:
        drawer = QFrame()
        drawer.setObjectName("DownloadQueueDrawer")
        drawer.setFixedWidth(360)
        drawer.setStyleSheet("""
            QFrame#DownloadQueueDrawer {
                background-color: #17100E;
                border-left: 1px solid #261A15;
            }
        """)
        d_layout = QVBoxLayout(drawer)
        d_layout.setContentsMargins(0, 0, 0, 0)
        d_layout.setSpacing(0)

        # 1. Drawer Header (Matches user screenshot: Download Queue (1) + ✕)
        header = QFrame()
        header.setStyleSheet("background-color: #17100E; border-bottom: 1px solid #241712;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 12, 16, 12)

        self.queue_drawer_title = QLabel("Download Queue (0)")
        self.queue_drawer_title.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #F5EBE6;")
        h_layout.addWidget(self.queue_drawer_title)

        h_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #87756D;
                font-size: 14px;
                font-weight: 700;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background-color: #281A15;
            }
        """)
        close_btn.clicked.connect(self.toggle_queue_view)
        h_layout.addWidget(close_btn)

        d_layout.addWidget(header)

        # 2. Queue Items Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")

        self.queue_items_container = QWidget()
        self.queue_items_container.setStyleSheet("background: transparent;")
        self.queue_items_layout = QVBoxLayout(self.queue_items_container)
        self.queue_items_layout.setContentsMargins(14, 14, 14, 14)
        self.queue_items_layout.setSpacing(10)
        self.queue_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self.queue_items_container)
        d_layout.addWidget(scroll, stretch=1)

        # 3. Bottom Action Bar (Matches screenshot: Open Downloads Folder + Download All)
        footer = QFrame()
        footer.setStyleSheet("background-color: #150E0C; border-top: 1px solid #241712;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(12, 10, 12, 10)
        f_layout.setSpacing(8)

        open_folder_btn = QPushButton("📁 Open Downloads Folder")
        open_folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #221714;
                color: #D4C3BC;
                border: 1px solid #33221B;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 11.5px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2D1F1A;
                color: #FFFFFF;
            }
        """)
        open_folder_btn.clicked.connect(self.open_downloads_folder)
        f_layout.addWidget(open_folder_btn, stretch=1)

        dl_all_btn = QPushButton("Download All")
        dl_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dl_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D1F1A;
                color: #FFFFFF;
                border: 1px solid #422C23;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 11.5px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #3D2922;
                border-color: #FF5A22;
            }
        """)
        dl_all_btn.clicked.connect(self.start_download_all_queue)
        f_layout.addWidget(dl_all_btn)

        d_layout.addWidget(footer)
        return drawer

    def refresh_queue_drawer(self):
        while self.queue_items_layout.count():
            item = self.queue_items_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.queue_cards.clear()

        cnt = len(self.download_queue)
        if hasattr(self, "queue_drawer_title"):
            self.queue_drawer_title.setText(f"Download Queue ({cnt})")
        if hasattr(self, "hv_queue_btn"):
            self.hv_queue_btn.setText(f"☰ Queue ({cnt})")

        if not self.download_queue:
            empty_lbl = QLabel("No dramas in queue.\nClick Download on any drama to add!")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #7A6962; font-size: 11.5px; padding-top: 40px;")
            self.queue_items_layout.addWidget(empty_lbl)
            return

        for drama in self.download_queue:
            sid = str(drama.get("series_id", ""))
            card = QueueDrawerCard(drama, on_remove=self.remove_from_queue_drawer)
            st = drama.get("_dl_status", "Queued")
            cur = drama.get("_dl_cur", 0)
            tot = drama.get("_dl_tot", int(drama.get("episode_cnt") or 0))
            pct = drama.get("_dl_pct", 0)
            card.update_progress(cur, tot, pct, st)
            self.queue_items_layout.addWidget(card)
            self.queue_cards[sid] = card

    def remove_from_queue_drawer(self, drama: Dict[str, Any]):
        sid = str(drama.get("series_id", ""))
        self.download_queue = [d for d in self.download_queue if str(d.get("series_id", "")) != sid]
        self.refresh_queue_drawer()
        self.update_harvester_btn_state()

    def queue_and_download_drama(self, drama: Dict[str, Any], folder: str = None, quality: str = None, ep_mode: str = None):
        if not drama:
            return

        series_id = str(drama.get("series_id", ""))
        title = drama.get("title", "drama")

        target_folder = folder or getattr(self, "hv_folder_full_path", os.path.join(get_app_dir(), "Downloaded_Videos"))
        target_quality = quality or (self.hv_quality_combo.currentText() if hasattr(self, "hv_quality_combo") else "1080p")
        target_ep_mode = ep_mode or (self.hv_ep_stepper_lbl.text() if hasattr(self, "hv_ep_stepper_lbl") else "all")

        # Check if already in queue
        existing = next((item for item in self.download_queue if str(item.get("series_id", "")) == series_id), None)
        if not existing:
            drama["_target_folder"] = target_folder
            drama["_target_quality"] = target_quality
            drama["_target_ep_mode"] = target_ep_mode
            drama["_dl_status"] = "Queued"
            drama["_dl_pct"] = 0
            self.download_queue.append(drama)
        else:
            existing["_target_folder"] = target_folder
            existing["_target_quality"] = target_quality
            existing["_target_ep_mode"] = target_ep_mode
            if existing.get("_dl_status") in ("✓ Complete", "Failed"):
                existing["_dl_status"] = "Queued"
                existing["_dl_pct"] = 0
            drama = existing

        # Open and refresh queue drawer
        self.refresh_queue_drawer()
        self.queue_drawer.setVisible(True)
        self.relayout_current_grid()

        # Update button state
        self.update_harvester_btn_state()

        if hasattr(self, "statusBar") and self.statusBar():
            self.statusBar().showMessage(f"✓ Added 《{title}》 to Download Queue ({len(self.download_queue)} total)", 4000)

        # Trigger processing if engine is idle
        self._check_and_process_queue()

    def _check_and_process_queue(self):
        if hasattr(self, "hv_worker") and self.hv_worker and self.hv_worker.isRunning():
            return

        if is_engine_busy():
            # Engine is currently busy running download in background, wait 1.5s and recheck
            QTimer.singleShot(1500, self._check_and_process_queue)
            return

        next_drama = None
        for item in self.download_queue:
            if item.get("_dl_status") == "Queued":
                next_drama = item
                break

        if not next_drama:
            return

        folder = next_drama.get("_target_folder") or getattr(self, "hv_folder_full_path", os.path.join(get_app_dir(), "Downloaded_Videos"))
        quality = next_drama.get("_target_quality") or (self.hv_quality_combo.currentText() if hasattr(self, "hv_quality_combo") else "1080p")
        ep_mode = next_drama.get("_target_ep_mode") or (self.hv_ep_stepper_lbl.text() if hasattr(self, "hv_ep_stepper_lbl") else "all")

        self._start_harvester_download(next_drama, folder, quality, ep_mode)

    def open_downloads_folder(self):
        folder = getattr(self, "hv_folder_full_path", os.path.join(get_app_dir(), "Downloaded_Videos"))
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception:
            pass

    def start_download_all_queue(self):
        if not self.download_queue:
            QMessageBox.information(self, "Queue Empty", "No dramas currently in the download queue.")
            return
        # Reset any Failed or Incomplete items to Queued so Download All retries them
        for d in self.download_queue:
            if d.get("_dl_status") != "✓ Complete":
                d["_dl_status"] = "Queued"
                d["_dl_pct"] = 0
        self.refresh_queue_drawer()
        self._check_and_process_queue()

    def _process_next_batch_queue_item(self):
        self._check_and_process_queue()

    def compute_optimal_columns(self) -> int:
        drawer_w = 360 if (hasattr(self, "queue_drawer") and self.queue_drawer.isVisible()) else 0
        target_w = self.width() - drawer_w - 16
        card_w = 160
        spacing = 14
        col_unit = card_w + spacing
        avail_w = max(300, target_w - 36)
        cols = max(3, int((avail_w + spacing) / col_unit))
        return cols

    def _rebuild_grid_layout(self, container: QWidget, old_grid: QGridLayout, cols: int, side_m: int, spacing: int) -> QGridLayout:
        if not container or not old_grid:
            return old_grid
        cards = []
        while old_grid.count():
            it = old_grid.takeAt(0)
            if it and it.widget():
                cards.append(it.widget())

        sip.delete(old_grid)
        new_grid = QGridLayout(container)
        new_grid.setContentsMargins(side_m, 14, side_m, 20)
        new_grid.setSpacing(spacing)
        new_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for i, c in enumerate(cards):
            new_grid.addWidget(c, i // cols, i % cols)
        return new_grid

    def relayout_current_grid(self):
        cols = self.compute_optimal_columns()

        drawer_w = 360 if (hasattr(self, "queue_drawer") and self.queue_drawer.isVisible()) else 0
        target_w = self.width() - drawer_w - 16
        card_w = 160
        spacing = 14
        total_w = cols * card_w + (cols - 1) * spacing
        rem = max(0, target_w - total_w)
        side_m = max(18, rem // 2)

        # Relayout leaderboard grid with clean QGridLayout reset
        if hasattr(self, "lb_grid_container") and hasattr(self, "lb_grid") and self.lb_grid:
            self.lb_grid = self._rebuild_grid_layout(self.lb_grid_container, self.lb_grid, cols, side_m, spacing)

        # Relayout catalogue grid if present
        if hasattr(self, "cat_grid_container") and hasattr(self, "cat_grid") and self.cat_grid:
            self.cat_grid = self._rebuild_grid_layout(self.cat_grid_container, self.cat_grid, cols, side_m, spacing)

        # Relayout saved grid if present
        if hasattr(self, "saved_grid_container") and hasattr(self, "saved_grid") and self.saved_grid:
            self.saved_grid = self._rebuild_grid_layout(self.saved_grid_container, self.saved_grid, cols, side_m, spacing)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        curr_scroll = 0
        if hasattr(self, "lb_scroll") and self.lb_scroll.verticalScrollBar():
            curr_scroll = self.lb_scroll.verticalScrollBar().value()
        self.relayout_current_grid()
        if hasattr(self, "lb_scroll") and self.lb_scroll.verticalScrollBar() and curr_scroll == 0:
            self.lb_scroll.verticalScrollBar().setValue(0)

    def _start_harvester_download(self, drama: Dict[str, Any], folder: str, quality: str, ep_mode: str):
        self.active_download_drama = drama
        self.active_download_series_id = str(drama.get("series_id", ""))
        series_id = self.active_download_series_id
        title = drama.get("title", "drama")
        safe_title = sanitize_filename(title)
        target_dir = os.path.join(folder, safe_title)
        os.makedirs(target_dir, exist_ok=True)

        if ep_mode == "all":
            cnt = int(drama.get("episode_cnt") or 0)
            ranges_str = f"1-{cnt}" if cnt > 0 else "1-100"
        elif "1 - 5" in ep_mode:
            ranges_str = "1-5"
        elif "1 - 20" in ep_mode:
            ranges_str = "1-20"
        else:
            ranges_str = "1-100"

        # Ensure drama is in the download queue and marked as Downloading
        in_queue = False
        for item in self.download_queue:
            if str(item.get("series_id", "")) == series_id:
                in_queue = True
                item["_dl_status"] = "Downloading..."
                break
        if not in_queue:
            drama["_dl_status"] = "Downloading..."
            self.download_queue.append(drama)

        # Open and refresh the slide-over queue drawer
        self.refresh_queue_drawer()
        self.queue_drawer.setVisible(True)
        self.relayout_current_grid()

        # Update card in queue drawer to downloading state
        total_eps = int(drama.get("episode_cnt") or 0)
        if series_id in self.queue_cards:
            self.queue_cards[series_id].update_progress(0, total_eps, 0, "Downloading...")

        res_map = {"1080p (Lossless Full HD)": "1080p", "720p (HD)": "720p", "480p (SD)": "480p", "1080p": "1080p", "720p": "720p", "480p": "480p"}
        resolution = res_map.get(quality, "1080p")

        # Bottom status pill: Downloading ep 1/X (0%) with orange theme
        self.hv_status_lbl.setText(f"🟠 Downloading ep 1/{total_eps or '?'} (0%)")
        self.hv_status_lbl.setStyleSheet("""
            background-color: #261711;
            border: 1px solid #4A2617;
            border-radius: 8px;
            color: #FF8E52;
            font-size: 11.5px;
            font-weight: 700;
            padding: 5px 12px;
        """)

        self.hv_progress_container.setVisible(True)
        self.hv_progress_line.setText(f"Harvesting 《{title}》 ({ranges_str})...")
        self.hv_pbar.setValue(0)
        self.update_harvester_btn_state()

        self.hv_worker = retain_thread(DramaSeriesDownloadWorker(
            drama=drama,
            output_folder=target_dir,
            episodes_range=ranges_str,
            quality=resolution,
            parent=None
        ))
        self.hv_worker.episode_progress.connect(self._on_hv_dl_progress)
        self.hv_worker.status_message.connect(self._on_hv_dl_status)
        self.hv_worker.all_finished.connect(self._on_hv_dl_finished)
        self.hv_worker.start()

    def _on_hv_dl_progress(self, cur: int, tot: int, pct: int, speed: float):
        self.hv_pbar.setValue(pct)
        self.hv_percent_lbl.setText(f"{pct}%")
        speed_str = f" · {speed:.1f} KB/s" if speed > 0 else ""
        self.hv_progress_line.setText(f"Harvesting Episode {cur}/{tot} ({pct}%){speed_str}...")

        # Update bottom status pill
        self.hv_status_lbl.setText(f"🟠 Downloading ep {cur}/{tot} ({pct}%)")
        self.hv_status_lbl.setStyleSheet("""
            background-color: #261711;
            border: 1px solid #4A2617;
            border-radius: 8px;
            color: #FF8E52;
            font-size: 11.5px;
            font-weight: 700;
            padding: 5px 12px;
        """)

        # Update queue drawer card for the drama actually downloading
        dl_drama = getattr(self, "active_download_drama", None) or self.selected_drama
        if dl_drama:
            dl_drama["_dl_cur"] = cur
            dl_drama["_dl_tot"] = tot
            dl_drama["_dl_pct"] = pct
            dl_drama["_dl_status"] = "Downloading..."
            sid = str(dl_drama.get("series_id", ""))
            if sid in self.queue_cards:
                self.queue_cards[sid].update_progress(cur, tot, pct, "Downloading...")

    def _on_hv_dl_status(self, msg: str):
        self.hv_progress_line.setText(msg)

    def _on_hv_dl_finished(self, success: bool, message: str):
        dl_drama = getattr(self, "active_download_drama", None) or self.selected_drama
        sid = str(dl_drama.get("series_id", "")) if dl_drama else ""
        if success:
            self.hv_status_lbl.setText("✓ Harvest Complete")
            self.hv_status_lbl.setStyleSheet("""
                background-color: #1B271D;
                border: 1px solid #2B4E30;
                color: #4ADE80;
                font-size: 11.5px;
                font-weight: 700;
                border-radius: 8px;
                padding: 5px 12px;
            """)
            self.hv_progress_line.setText(f"Completed! {message}")
            self.hv_pbar.setValue(100)
            self.hv_percent_lbl.setText("100%")
            if dl_drama:
                cnt = int(dl_drama.get("episode_cnt") or 0)
                dl_drama["_dl_cur"] = cnt
                dl_drama["_dl_tot"] = cnt
                dl_drama["_dl_pct"] = 100
                dl_drama["_dl_status"] = "✓ Complete"
            if sid in self.queue_cards:
                cnt = int(dl_drama.get("episode_cnt") or 0) if dl_drama else 0
                self.queue_cards[sid].update_progress(cnt, cnt, 100, "✓ Complete")
        else:
            if "already running" in str(message).lower():
                # Engine was busy, keep item in Queued status and retry
                if dl_drama:
                    dl_drama["_dl_status"] = "Queued"
                if sid in self.queue_cards:
                    self.queue_cards[sid].ratio_lbl.setText("Queued")
                    self.queue_cards[sid].status_lbl.setText("Waiting...")
                    self.queue_cards[sid].status_lbl.setStyleSheet("font-size: 11px; color: #EAB308; font-weight: 600;")
                self.hv_status_lbl.setText("🟠 Engine busy... waiting")
                self.hv_progress_line.setText("Engine is finishing previous download... waiting in queue...")
                self.update_harvester_btn_state()
                QTimer.singleShot(2500, self._check_and_process_queue)
                return
            else:
                self.hv_status_lbl.setText("⚠️ Harvest Error")
                self.hv_progress_line.setText(f"Error: {message}")
                if dl_drama:
                    dl_drama["_dl_status"] = "Failed"
                if sid in self.queue_cards:
                    self.queue_cards[sid].status_lbl.setText("Failed")
                    self.queue_cards[sid].status_lbl.setStyleSheet("color: #EF4444; font-weight: bold;")

        self.update_harvester_btn_state()

        # Advance to NEXT pending item in the queue automatically
        QTimer.singleShot(1200, self._check_and_process_queue)

    def increment_ep_range(self):
        self.hv_ep_index = (self.hv_ep_index + 1) % len(self.hv_ep_options)
        self.hv_ep_stepper_lbl.setText(self.hv_ep_options[self.hv_ep_index])

    def decrement_ep_range(self):
        self.hv_ep_index = (self.hv_ep_index - 1 + len(self.hv_ep_options)) % len(self.hv_ep_options)
        self.hv_ep_stepper_lbl.setText(self.hv_ep_options[self.hv_ep_index])

    def reset_harvester_selection(self):
        if hasattr(self, "hv_worker") and self.hv_worker and self.hv_worker.isRunning():
            try:
                self.hv_worker.cancel()
            except Exception:
                pass
        try:
            requests.post("http://127.0.0.1:8000/dl/cancel", timeout=2)
        except Exception:
            pass

        if hasattr(self, "selected_card_widget") and self.selected_card_widget:
            try:
                self.selected_card_widget.set_selected(False)
            except Exception:
                pass
        self.selected_drama = None
        self.selected_card_widget = None
        self.hv_status_lbl.setText("🟢 Ready ✓")
        self.hv_status_lbl.setStyleSheet("""
            background-color: #1B271D;
            border: 1px solid #2B4E30;
            color: #4ADE80;
            font-size: 11.5px;
            font-weight: 700;
            border-radius: 8px;
            padding: 5px 12px;
        """)
        self.hv_dl_btn.setText("⬇ Download")
        self.hv_dl_btn.setEnabled(True)
        self.hv_progress_container.setVisible(False)

    def browse_harvester_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.hv_folder_full_path)
        if folder:
            self.hv_folder_full_path = folder
            short_dir = folder if len(folder) < 32 else "..." + folder[-28:]
            self.hv_folder_btn.setText(f"📁 {short_dir}")
            self.hv_folder_btn.setToolTip(f"Save Folder: {folder}")

    def handle_harvester_search(self):
        q = self.hv_search_input.text().strip()
        if not q:
            self.current_catalogue_q = ""
            self.current_catalogue_page = 1
            self.switch_tab(0)
            self.load_realtime_catalogue()
            return

        import re
        id_match = re.search(r'\b\d{18,20}\b', q)
        if id_match:
            series_id = id_match.group(0)
            self.open_drama_view({"series_id": series_id, "title": f"Drama {series_id}"})
            return

        self.current_catalogue_q = q
        self.current_catalogue_page = 1
        self.switch_tab(0)
        self.load_realtime_catalogue()

    def toggle_library_view(self):
        if self.stack.currentIndex() == 2:
            self.switch_tab(0)
        else:
            self.switch_tab(2)

    def toggle_queue_view(self):
        if not hasattr(self, "queue_drawer"):
            return
        vis = not self.queue_drawer.isVisible()
        self.queue_drawer.setVisible(vis)
        if vis:
            self.refresh_queue_drawer()
        self.relayout_current_grid()
        QTimer.singleShot(30, self.relayout_current_grid)

    def _apply_genre_pill_styles(self):
        for btn in getattr(self, "hv_genre_buttons", []):
            k = btn.property("genre_key")
            is_active = (k == self.current_catalogue_genre) or (not self.current_catalogue_genre and k == "")
            btn.setChecked(is_active)
            if is_active:
                btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF451D, stop:1 #FF7830);
                        color: #FFFFFF;
                        font-weight: 800;
                        font-size: 11.5px;
                        border-radius: 14px;
                        border: none;
                        padding: 5px 16px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1A1310;
                        color: #A89891;
                        font-size: 11.5px;
                        font-weight: 600;
                        border-radius: 14px;
                        border: 1px solid #2B1E19;
                        padding: 5px 14px;
                    }
                    QPushButton:hover {
                        background-color: #261B16;
                        color: #FFFFFF;
                        border-color: #FF5A22;
                    }
                """)

    def on_harvester_genre_clicked(self, genre_key: str):
        self.current_catalogue_genre = genre_key
        self._apply_genre_pill_styles()
        self.current_catalogue_page = 1
        self.switch_tab(0)
        self.load_realtime_catalogue()

    def on_harvester_sort_changed(self, idx: int):
        sort_map = {0: "popular", 1: "newest", 2: "score", 3: "eps"}
        self.current_catalogue_sort = sort_map.get(idx, "popular")
        self.current_catalogue_page = 1
        self.switch_tab(0)
        self.load_realtime_catalogue()

    def switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 1:
            if not getattr(self, "_catalogue_loaded", False):
                self._catalogue_loaded = True
                self.load_catalogue()
        elif index == 2:
            self.refresh_saved_list()
        elif index == 3:
            if hasattr(self, "_refresh_batch_queue_ui"):
                self._refresh_batch_queue_ui()
            if hasattr(self, "_refresh_merge_drama_list"):
                self._refresh_merge_drama_list()

    def update_saved_count(self):
        count = self.db.get_total_count()
        if hasattr(self, "hv_library_btn"):
            self.hv_library_btn.setText("📁 Library")

    def _open_update_dialog(self):
        from update_dialog import UpdateDialog
        dlg = UpdateDialog(current_version=APP_VERSION, auto_check=True, parent=self)
        dlg.exec()

    def _start_silent_update_check(self):
        try:
            from update_dialog import UpdateCheckWorker, UpdateAlertModal, UpdateDialog
            self._bg_update_worker = retain_thread(UpdateCheckWorker(current_version=APP_VERSION, parent=None))

            def on_check_done(info):
                if not isinstance(info, dict):
                    return

                has_update = info.get("has_update", False)
                latest = info.get("latest_version", APP_VERSION)

                # Update top header badge button
                if hasattr(self, "update_btn") and self.update_btn is not None:
                    if has_update:
                        self.update_btn.setText(f"🔥 Update v{latest}")
                        self.update_btn.setStyleSheet("""
                            QPushButton {
                                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3366, stop:1 #FF5A22);
                                color: #FFFFFF;
                                border: 1px solid #FF5A22;
                                border-radius: 12px;
                                padding: 0 12px;
                                font-weight: 900;
                                font-size: 11px;
                            }
                            QPushButton:hover {
                                background: #FF2255;
                                border-color: #FF3366;
                            }
                        """)
                        self.update_btn.setToolTip(f"🎉 New version v{latest} available! Click to update now")
                    else:
                        self.update_btn.setText(f"✓ v{APP_VERSION}")
                        self.update_btn.setToolTip(f"Current version v{APP_VERSION} (Latest)")

                # If a new version exists on GitHub, trigger in-tool alert modal!
                if has_update:
                    alert_modal = UpdateAlertModal(info, parent=self)
                    if alert_modal.exec() == QDialog.DialogCode.Accepted:
                        dl_dlg = UpdateDialog(
                            current_version=APP_VERSION,
                            auto_check=False,
                            update_info=info,
                            auto_download=True,
                            parent=self
                        )
                        dl_dlg.exec()

            self._bg_update_worker.check_finished.connect(on_check_done)
            self._bg_update_worker.start()
        except Exception:
            pass

    # ================================================================
    # IN-APP DRAMA HUB (All-in-One Single View)
    # ================================================================

    def open_drama_view(self, drama: Dict[str, Any]):
        """Open the In-App All-in-One Drama Hub page without opening any popup windows."""
        if not drama:
            return
        curr = self.stack.currentIndex()
        if curr != 5:
            self.previous_tab_index = curr
        self._populate_drama_detail_page(drama)
        self.stack.setCurrentIndex(5)
        # Clear active highlights on main tabs
        for btn in self.tab_buttons:
            btn.setProperty("class", "NavBtn")
            btn.setStyleSheet("")

    def _on_back_from_drama_view(self):
        """Return to the previously active tab (Leaderboard, Catalogue, or Library)."""
        target = getattr(self, "previous_tab_index", 0)
        self.switch_tab(target)

    def _create_drama_detail_page(self) -> QWidget:
        widget = QWidget()
        page_layout = QVBoxLayout(widget)
        page_layout.setContentsMargins(18, 10, 18, 10)
        page_layout.setSpacing(10)

        # Top Bar: Back Button + Breadcrumb Navigation
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        self.drama_page_back_btn = QPushButton("← Back")
        self.drama_page_back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.drama_page_back_btn.setStyleSheet("""
            QPushButton {
                background: #241A35;
                color: #FFFFFF;
                border: 1px solid #453360;
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #392854;
                border-color: #FF5A2E;
                color: #FF8F55;
            }
        """)
        self.drama_page_back_btn.clicked.connect(self._on_back_from_drama_view)
        top_bar.addWidget(self.drama_page_back_btn)

        self.drama_page_nav_title = QLabel("Drama Hub")
        self.drama_page_nav_title.setStyleSheet("color: #DDD4EE; font-size: 14px; font-weight: 700;")
        top_bar.addWidget(self.drama_page_nav_title)

        top_bar.addStretch()

        self.dp_engine_lbl = QLabel("🟢 Engine Ready")
        self.dp_engine_lbl.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 700; background: #1B2B28; border: 1px solid #285A48; border-radius: 7px; padding: 4px 10px;")
        top_bar.addWidget(self.dp_engine_lbl)

        page_layout.addLayout(top_bar)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        scroll_content = QWidget()
        sc_layout = QVBoxLayout(scroll_content)
        sc_layout.setContentsMargins(2, 2, 2, 4)
        sc_layout.setSpacing(12)

        # ----------------------------------------------------
        # 1. HERO SHOWCASE CARD (Poster + Metadata + Notes + Actions)
        # ----------------------------------------------------
        hero_card = QFrame()
        hero_card.setObjectName("HeroCard")
        hero_card.setStyleSheet("""
            QFrame#HeroCard {
                background-color: #171221;
                border: 1px solid #2D2140;
                border-radius: 14px;
            }
        """)
        hero_layout = QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(14, 14, 14, 14)
        hero_layout.setSpacing(16)

        # Poster frame
        self.dp_poster_lbl = QLabel()
        self.dp_poster_lbl.setFixedSize(130, 176)
        self.dp_poster_lbl.setStyleSheet("background-color: #21192F; border-radius: 10px; border: 1px solid #3E2F54;")
        self.dp_poster_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self.dp_poster_lbl)

        # Info & Details column
        info_col = QVBoxLayout()
        info_col.setSpacing(6)

        # Title & Series ID
        title_row = QHBoxLayout()
        self.dp_title_lbl = QLabel("Drama Title")
        self.dp_title_lbl.setStyleSheet("font-size: 18px; font-weight: 900; color: #FFFFFF;")
        self.dp_title_lbl.setWordWrap(True)
        title_row.addWidget(self.dp_title_lbl, stretch=1)

        self.dp_id_lbl = QLabel("ID: -")
        self.dp_id_lbl.setStyleSheet("color: #FF8F55; font-weight: 700; font-size: 11px; background: #261933; border: 1px solid #432757; border-radius: 6px; padding: 2px 8px;")
        title_row.addWidget(self.dp_id_lbl)
        info_col.addLayout(title_row)

        # Badges Row
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)

        self.dp_ep_total_lbl = QLabel("📺 Episodes: Loading... 🔄")
        self.dp_ep_total_lbl.setStyleSheet("color: #DDD4EE; font-size: 12px; font-weight: 700; background: #211831; border: 1px solid #3B2A56; border-radius: 6px; padding: 3px 8px;")
        badge_row.addWidget(self.dp_ep_total_lbl)

        self.dp_meta_lbl = QLabel("Score: ★ 0.0")
        self.dp_meta_lbl.setStyleSheet("color: #DDD4EE; font-size: 12px; background: #211831; border: 1px solid #3B2A56; border-radius: 6px; padding: 3px 8px;")
        badge_row.addWidget(self.dp_meta_lbl)

        tag_lbl = QLabel("Tag:")
        tag_lbl.setStyleSheet("color: #B5ACC4; font-size: 11px; font-weight: 600;")
        badge_row.addWidget(tag_lbl)
        self.dp_tag_combo = QComboBox()
        self.dp_tag_combo.addItems(["Plan to Watch", "Watching", "Completed", "Favorite"])
        self.dp_tag_combo.setFixedHeight(26)
        badge_row.addWidget(self.dp_tag_combo)

        badge_row.addStretch()
        info_col.addLayout(badge_row)

        # Personal Notes
        notes_row = QHBoxLayout()
        notes_row.setSpacing(8)
        self.dp_notes_edit = QTextEdit()
        self.dp_notes_edit.setFixedHeight(36)
        self.dp_notes_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dp_notes_edit.setStyleSheet("background: #171122; border: 1px solid #35264C; border-radius: 8px; padding: 6px 10px; color: #EDE8F5; font-size: 11.5px;")
        self.dp_notes_edit.setPlaceholderText("Write notes or thoughts about this drama...")
        notes_row.addWidget(self.dp_notes_edit, stretch=1)

        self.dp_save_btn = QPushButton("♥ Save to Library")
        self.dp_save_btn.setProperty("class", "PrimaryBtn")
        self.dp_save_btn.setFixedHeight(34)
        self.dp_save_btn.clicked.connect(self._dp_toggle_save)
        notes_row.addWidget(self.dp_save_btn)
        info_col.addLayout(notes_row)

        # Action Buttons row
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.dp_play_btn = QPushButton("▶ Play in Cinema Player")
        self.dp_play_btn.setProperty("class", "PrimaryBtn")
        self.dp_play_btn.setFixedHeight(32)
        self.dp_play_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4528, stop:1 #FF8038);
                color: #FFFFFF;
                font-weight: 800;
                font-size: 12px;
                padding: 6px 14px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5A3D, stop:1 #FF9452);
            }
        """)
        self.dp_play_btn.clicked.connect(self._dp_open_player)
        act_row.addWidget(self.dp_play_btn)

        self.dp_queue_btn = QPushButton("➕ Add to Queue")
        self.dp_queue_btn.setProperty("class", "SecondaryBtn")
        self.dp_queue_btn.setFixedHeight(32)
        self.dp_queue_btn.clicked.connect(self._dp_add_to_queue)
        act_row.addWidget(self.dp_queue_btn)

        copy_tag_btn = QPushButton("《》 Tag")
        copy_tag_btn.setProperty("class", "SecondaryBtn")
        copy_tag_btn.setFixedHeight(32)
        copy_tag_btn.setToolTip("Copy title tag 《...》")
        copy_tag_btn.clicked.connect(self._dp_copy_tag)
        act_row.addWidget(copy_tag_btn)

        copy_id_btn = QPushButton("⧉ ID")
        copy_id_btn.setProperty("class", "SecondaryBtn")
        copy_id_btn.setFixedHeight(32)
        copy_id_btn.setToolTip("Copy Series ID")
        copy_id_btn.clicked.connect(self._dp_copy_id)
        act_row.addWidget(copy_id_btn)

        web_btn = QPushButton("🌐 Web")
        web_btn.setProperty("class", "SecondaryBtn")
        web_btn.setFixedHeight(32)
        web_btn.setToolTip("Open in Web Browser")
        web_btn.clicked.connect(self._dp_open_web)
        act_row.addWidget(web_btn)

        act_row.addStretch()
        info_col.addLayout(act_row)

        hero_layout.addLayout(info_col, stretch=1)
        sc_layout.addWidget(hero_card)

        # ----------------------------------------------------
        # 2. INTERACTIVE EPISODE BROWSER CARD (Grid + Range Tabs + Batch Tools)
        # ----------------------------------------------------
        ep_box = QFrame()
        ep_box.setObjectName("EpisodeBox")
        ep_box.setStyleSheet("""
            QFrame#EpisodeBox {
                background-color: #171221;
                border: 1px solid #2D2140;
                border-radius: 14px;
            }
        """)
        ep_layout = QVBoxLayout(ep_box)
        ep_layout.setContentsMargins(14, 12, 14, 12)
        ep_layout.setSpacing(10)

        # Header Row: Title + Selected Badge + Range Tabs + Batch Tools
        ep_header = QHBoxLayout()
        ep_header.setSpacing(10)

        ep_title = QLabel("📺 Episode Selection")
        ep_title.setStyleSheet("font-size: 14px; font-weight: 800; color: #FFFFFF;")
        ep_header.addWidget(ep_title)

        self.dp_selected_badge = QLabel("Selected: 0 / 0 Eps")
        self.dp_selected_badge.setStyleSheet("color: #FF8F55; font-size: 11px; font-weight: 700; background: #2A1A2E; border: 1px solid #4D2644; border-radius: 6px; padding: 2px 8px;")
        ep_header.addWidget(self.dp_selected_badge)

        ep_header.addStretch()

        # Dynamic Range Tabs Container
        self.dp_range_tabs_layout = QHBoxLayout()
        self.dp_range_tabs_layout.setSpacing(6)
        ep_header.addLayout(self.dp_range_tabs_layout)

        # Batch Selection Tools
        sel_all_btn = QPushButton("✓ Select All")
        sel_all_btn.setProperty("class", "SecondaryBtn")
        sel_all_btn.setFixedHeight(28)
        sel_all_btn.clicked.connect(self._dp_select_all)
        ep_header.addWidget(sel_all_btn)

        clear_btn = QPushButton("✕ Clear")
        clear_btn.setProperty("class", "SecondaryBtn")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._dp_clear_all)
        ep_header.addWidget(clear_btn)

        first5_btn = QPushButton("⚡ Ep 1-5 (Test)")
        first5_btn.setStyleSheet("""
            QPushButton {
                background-color: #241A35;
                color: #FF8F55;
                font-weight: 700;
                font-size: 11.5px;
                border: 1px solid #482852;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #382452;
                border-color: #FF5A2E;
            }
        """)
        first5_btn.setFixedHeight(28)
        first5_btn.clicked.connect(self._dp_select_test_five)
        ep_header.addWidget(first5_btn)

        ep_layout.addLayout(ep_header)

        # Scrollable Grid of Episode Chips
        self.dp_grid_scroll = QScrollArea()
        self.dp_grid_scroll.setWidgetResizable(True)
        self.dp_grid_scroll.setFixedHeight(180)
        self.dp_grid_scroll.setStyleSheet("border: 1px solid #281D38; border-radius: 8px; background: #130E1C;")
        self.dp_grid_widget = QWidget()
        self.dp_grid_widget.setStyleSheet("background: transparent;")
        self.dp_grid_layout = QGridLayout(self.dp_grid_widget)
        self.dp_grid_layout.setContentsMargins(8, 8, 8, 8)
        self.dp_grid_layout.setSpacing(6)
        self.dp_grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.dp_grid_scroll.setWidget(self.dp_grid_widget)
        ep_layout.addWidget(self.dp_grid_scroll)

        # Tip label
        tip_lbl = QLabel("💡 Tip: Click any episode tile to toggle selection for download. Double-click to stream directly in Cinema Player.")
        tip_lbl.setStyleSheet("color: #8C7F9E; font-size: 11px; font-style: italic;")
        ep_layout.addWidget(tip_lbl)

        sc_layout.addWidget(ep_box)

        # ----------------------------------------------------
        # 3. DOWNLOAD COMMAND DECK CARD (Quality + Path + Start Button)
        # ----------------------------------------------------
        deck_box = QFrame()
        deck_box.setObjectName("DlDeckBox")
        deck_box.setStyleSheet("""
            QFrame#DlDeckBox {
                background-color: #171221;
                border: 1px solid #2D2140;
                border-radius: 14px;
            }
        """)
        deck_layout = QVBoxLayout(deck_box)
        deck_layout.setContentsMargins(14, 12, 14, 12)
        deck_layout.setSpacing(10)

        # Quality & Save Folder Settings Row
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        q_lbl = QLabel("Quality:")
        q_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        self.dp_quality_combo = QComboBox()
        self.dp_quality_combo.addItems(["1080p (Best - Full HD)", "720p (HD)", "480p (SD)"])
        self.dp_quality_combo.setFixedHeight(28)
        settings_row.addWidget(q_lbl)
        settings_row.addWidget(self.dp_quality_combo)

        f_lbl = QLabel("Save Folder:")
        f_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        settings_row.addWidget(f_lbl)

        self.dp_folder_input = QLineEdit()
        default_v_folder = os.path.join(get_app_dir(), "Downloaded_Videos")
        self.dp_folder_input.setText(default_v_folder)
        self.dp_folder_input.setFixedHeight(28)
        settings_row.addWidget(self.dp_folder_input, stretch=2)

        browse_btn = QPushButton("📁 Browse")
        browse_btn.setProperty("class", "SecondaryBtn")
        browse_btn.setFixedHeight(28)
        browse_btn.clicked.connect(self._dp_browse_folder)
        settings_row.addWidget(browse_btn)

        deck_layout.addLayout(settings_row)

        # Progress Bar & Live Status Label
        self.dp_pbar = QProgressBar()
        self.dp_pbar.setVisible(False)
        self.dp_pbar.setFixedHeight(12)
        deck_layout.addWidget(self.dp_pbar)

        self.dp_status_lbl = QLabel("Ready to download")
        self.dp_status_lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        deck_layout.addWidget(self.dp_status_lbl)

        # Action Buttons Row
        act_bar = QHBoxLayout()
        act_bar.setSpacing(8)

        self.dp_start_dl_btn = QPushButton("⬇ Start Download")
        self.dp_start_dl_btn.setProperty("class", "PrimaryBtn")
        self.dp_start_dl_btn.setFixedHeight(34)
        self.dp_start_dl_btn.clicked.connect(self._dp_start_download)
        act_bar.addWidget(self.dp_start_dl_btn)

        self.dp_cancel_dl_btn = QPushButton("⛔ Cancel")
        self.dp_cancel_dl_btn.setProperty("class", "SecondaryBtn")
        self.dp_cancel_dl_btn.setFixedHeight(34)
        self.dp_cancel_dl_btn.setVisible(False)
        self.dp_cancel_dl_btn.clicked.connect(self._dp_cancel_download)
        act_bar.addWidget(self.dp_cancel_dl_btn)

        self.dp_open_folder_btn = QPushButton("📂 Open Folder")
        self.dp_open_folder_btn.setProperty("class", "SecondaryBtn")
        self.dp_open_folder_btn.setFixedHeight(34)
        self.dp_open_folder_btn.clicked.connect(self._dp_open_folder)
        act_bar.addWidget(self.dp_open_folder_btn)

        self.dp_merge_btn = QPushButton("🎬 Merge Episodes")
        self.dp_merge_btn.setProperty("class", "SecondaryBtn")
        self.dp_merge_btn.setFixedHeight(34)
        self.dp_merge_btn.clicked.connect(self._dp_open_merge)
        act_bar.addWidget(self.dp_merge_btn)

        act_bar.addStretch()

        format_badge = QLabel("Lossless 1080p Full HD MP4")
        format_badge.setStyleSheet("color: #A396BC; font-size: 11px; font-weight: 600;")
        act_bar.addWidget(format_badge)

        deck_layout.addLayout(act_bar)

        sc_layout.addWidget(deck_box)
        sc_layout.addStretch()

        scroll.setWidget(scroll_content)
        page_layout.addWidget(scroll)

        return widget

    def _populate_drama_detail_page(self, drama: Dict[str, Any]):
        """Populate all fields in the In-App Drama Page and load episodes asynchronously."""
        self.active_drama = drama
        title = drama.get("title", "Untitled")
        series_id = str(drama.get("series_id", ""))
        eps = str(drama.get("episode_cnt", "0"))
        score = str(drama.get("score", "N/A"))
        heat = str(drama.get("heat", ""))
        status = str(drama.get("status", ""))
        cover_url = drama.get("cover", "")

        self.dp_title_lbl.setText(title)
        self.drama_page_nav_title.setText(f"Drama Hub · {title}")
        self.dp_id_lbl.setText(f"Series ID: {series_id}")

        meta = f"Score: <b>★ {score}</b>"
        if heat:
            meta += f" | Heat: <b>🔥 {heat}</b>"
        if status:
            meta += f" | Status: <b>{status}</b>"
        self.dp_meta_lbl.setText(meta)

        # Clear existing episode data while loading
        self.dp_all_episodes = []
        self.dp_selected_episodes.clear()
        self.dp_current_tab_range = "all"
        self.dp_ep_total_lbl.setText("📺 Episodes: <b>Loading... 🔄</b>")
        self.dp_selected_badge.setText("Loading episodes...")
        self._dp_clear_grid()

        # Poster load
        self.dp_poster_lbl.setText("Loading poster...")
        pixmap = ImageCache.get_instance().get_pixmap(cover_url, self._dp_set_poster)
        if pixmap:
            self._dp_set_poster(pixmap)

        # Saved database info
        is_saved = self.db.is_saved(series_id)
        saved_rec = self.db.get_drama(series_id) if is_saved else {}
        if saved_rec and saved_rec.get("user_tag"):
            idx = self.dp_tag_combo.findText(saved_rec["user_tag"])
            if idx >= 0:
                self.dp_tag_combo.setCurrentIndex(idx)
        else:
            self.dp_tag_combo.setCurrentIndex(0)

        self.dp_notes_edit.setPlainText(saved_rec.get("notes", "") if saved_rec else "")
        if is_saved:
            self.dp_save_btn.setText("✓ Saved in Library")
            self.dp_save_btn.setProperty("class", "SecondaryBtn")
        else:
            self.dp_save_btn.setText("♥ Save to Library")
            self.dp_save_btn.setProperty("class", "PrimaryBtn")

        # Save Folder calculation
        safe_title = sanitize_filename(title)
        default_folder = os.path.join(get_app_dir(), "Downloaded_Videos", safe_title)
        self.dp_folder_input.setText(default_folder)
        self._dp_scan_downloaded()

        # Reset download status
        self.dp_pbar.setVisible(False)
        self.dp_status_lbl.setText("Ready to download")
        self.dp_start_dl_btn.setEnabled(False)
        self.dp_cancel_dl_btn.setVisible(False)

        # Launch background thread to fetch series episode listing
        if hasattr(self, "dp_loader_thread") and self.dp_loader_thread and self.dp_loader_thread.isRunning():
            try:
                self.dp_loader_thread.stop()
                self.dp_loader_thread.quit()
            except Exception:
                pass

        self.dp_loader_thread = retain_thread(DramaDetailsLoaderThread(series_id, parent=None))
        self.dp_loader_thread.loaded_signal.connect(self._dp_on_details_loaded)
        self.dp_loader_thread.start()

    def _dp_on_details_loaded(self, ep_info: dict, engine_ready: bool):
        """Callback when background episode loader finishes."""
        if sip.isdeleted(self):
            return
        if engine_ready:
            self.dp_engine_lbl.setText("🟢 Engine Ready")
            self.dp_engine_lbl.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 700; background: #1B2B28; border: 1px solid #285A48; border-radius: 7px; padding: 4px 10px;")
        else:
            self.dp_engine_lbl.setText("🟡 Engine Initializing")
            self.dp_engine_lbl.setStyleSheet("color: #FBBF24; font-size: 12px; font-weight: 700; background: #2D2418; border: 1px solid #5A4828; border-radius: 7px; padding: 4px 10px;")

        total = 0
        if ep_info:
            # Upgrade cover to ultra-HD if available
            hd_cover = ep_info.get("cover")
            if hd_cover:
                pixmap = ImageCache.get_instance().get_pixmap(hd_cover, self._dp_set_poster)
                if pixmap:
                    self._dp_set_poster(pixmap)

            total = ep_info.get("total", 0)
            raw_eps = ep_info.get("episodes", [])
            if raw_eps:
                self.dp_all_episodes = [int(x) if isinstance(x, (int, str)) and str(x).isdigit() else idx for idx, x in enumerate(raw_eps, start=1)]
            elif total > 0:
                self.dp_all_episodes = list(range(1, total + 1))

        if not self.dp_all_episodes:
            # Fallback to existing metadata count or 1
            existing = int(self.active_drama.get("episode_cnt") or 0)
            if existing > 0:
                self.dp_all_episodes = list(range(1, existing + 1))
                total = existing
            else:
                self.dp_all_episodes = [1]
                total = 1

        self.active_drama["episode_cnt"] = total
        self.dp_ep_total_lbl.setText(f"📺 Episodes: <b>{total} Eps</b>")

        # Select all episodes by default
        self.dp_selected_episodes = set(self.dp_all_episodes)
        self._dp_build_range_tabs(total)
        self._dp_render_episode_grid()
        self._dp_update_selection_summary()

    def _dp_clear_grid(self):
        while self.dp_grid_layout.count():
            item = self.dp_grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.dp_ep_buttons.clear()

    def _dp_build_range_tabs(self, total: int):
        while self.dp_range_tabs_layout.count():
            item = self.dp_range_tabs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.dp_range_tab_buttons.clear()

        all_btn = QPushButton(f"All (1-{total})")
        all_btn.clicked.connect(lambda: self._dp_filter_range("all"))
        self.dp_range_tabs_layout.addWidget(all_btn)
        self.dp_range_tab_buttons.append(all_btn)

        if total > 30:
            block_size = 30
            for start in range(1, total + 1, block_size):
                end = min(start + block_size - 1, total)
                btn = QPushButton(f"{start} - {end}")
                r_tuple = (start, end)
                btn.clicked.connect(lambda _, r=r_tuple: self._dp_filter_range(r))
                self.dp_range_tabs_layout.addWidget(btn)
                self.dp_range_tab_buttons.append(btn)
        self._dp_apply_range_tab_styles()

    def _dp_apply_range_tab_styles(self):
        for btn in self.dp_range_tab_buttons:
            t = btn.text()
            is_active = False
            if self.dp_current_tab_range == "all" and "All" in t:
                is_active = True
            elif isinstance(self.dp_current_tab_range, tuple) and f"{self.dp_current_tab_range[0]} - {self.dp_current_tab_range[1]}" in t:
                is_active = True

            if is_active:
                btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #6366F1);
                        color: #FFFFFF;
                        font-weight: 700;
                        font-size: 11.5px;
                        border: 1px solid #9061F9;
                        border-radius: 6px;
                        padding: 5px 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1A1326;
                        color: #9D8FB3;
                        font-size: 11.5px;
                        font-weight: 600;
                        border: 1px solid #33264A;
                        border-radius: 6px;
                        padding: 5px 12px;
                    }
                    QPushButton:hover {
                        background-color: #271C3A;
                        color: #FFFFFF;
                        border-color: #553E78;
                    }
                """)

    def _dp_filter_range(self, range_val):
        self.dp_current_tab_range = range_val
        self._dp_apply_range_tab_styles()
        self._dp_render_episode_grid()

    def _dp_render_episode_grid(self):
        self._dp_clear_grid()
        if not self.dp_all_episodes:
            loading_lbl = QLabel("No episodes found or engine is initializing...")
            loading_lbl.setStyleSheet("color: #8E7FA8; font-size: 12px; padding: 10px;")
            self.dp_grid_layout.addWidget(loading_lbl, 0, 0)
            return

        if self.dp_current_tab_range == "all":
            ep_list = self.dp_all_episodes
        else:
            s, e = self.dp_current_tab_range
            ep_list = [x for x in self.dp_all_episodes if s <= x <= e]

        cols = 16
        for idx, ep in enumerate(ep_list):
            row = idx // cols
            col = idx % cols

            btn = EpisodeChipBtn(ep)
            btn.setFixedSize(56, 38)
            is_dl = ep in self.dp_downloaded_episodes
            is_sel = ep in self.dp_selected_episodes

            btn.set_chip_state(is_sel, is_dl)
            btn.clicked.connect(lambda _, e=ep: self._dp_toggle_ep(e))
            btn.double_clicked.connect(self._dp_play_episode)
            self.dp_ep_buttons[ep] = btn
            self.dp_grid_layout.addWidget(btn, row, col)

    def _dp_toggle_ep(self, ep: int):
        if ep in self.dp_selected_episodes:
            self.dp_selected_episodes.remove(ep)
        else:
            self.dp_selected_episodes.add(ep)

        btn = self.dp_ep_buttons.get(ep)
        if btn:
            is_dl = ep in self.dp_downloaded_episodes
            is_sel = ep in self.dp_selected_episodes
            btn.set_chip_state(is_sel, is_dl)

        self._dp_update_selection_summary()

    def _dp_select_all(self):
        self.dp_selected_episodes = set(self.dp_all_episodes)
        self._dp_render_episode_grid()
        self._dp_update_selection_summary()

    def _dp_clear_all(self):
        self.dp_selected_episodes.clear()
        self._dp_render_episode_grid()
        self._dp_update_selection_summary()

    def _dp_select_test_five(self):
        self.dp_selected_episodes = set(self.dp_all_episodes[:5])
        self._dp_render_episode_grid()
        self._dp_update_selection_summary()

    def _dp_update_selection_summary(self):
        sel_cnt = len(self.dp_selected_episodes)
        tot_cnt = len(self.dp_all_episodes)
        self.dp_selected_badge.setText(f"Selected: {sel_cnt} / {tot_cnt} Eps")

        if sel_cnt > 0:
            self.dp_start_dl_btn.setEnabled(True)
            self.dp_start_dl_btn.setText(f"⬇ Start Download ({sel_cnt} Episode{'s' if sel_cnt > 1 else ''})")
            self.dp_start_dl_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF7830);
                    color: #FFFFFF;
                    font-weight: 800;
                    font-size: 13px;
                    border-radius: 9px;
                    padding: 8px 22px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF5233, stop:1 #FF8F4D);
                }
            """)
        else:
            self.dp_start_dl_btn.setEnabled(False)
            self.dp_start_dl_btn.setText("Select at least 1 Episode")
            self.dp_start_dl_btn.setStyleSheet("""
                QPushButton {
                    background: #251D33;
                    color: #7A6D8F;
                    font-weight: 700;
                    font-size: 13px;
                    border: 1px solid #3B2E52;
                    border-radius: 9px;
                    padding: 8px 22px;
                }
            """)

    def _dp_scan_downloaded(self):
        self.dp_downloaded_episodes.clear()
        folder = self.dp_folder_input.text().strip()
        if os.path.exists(folder):
            import re
            for f in os.listdir(folder):
                if f.lower().endswith(".mp4"):
                    m = re.search(r"EP_?(\d+)", f, re.IGNORECASE)
                    if m:
                        try:
                            self.dp_downloaded_episodes.add(int(m.group(1)))
                        except Exception:
                            pass
        has_episodes = len(self.dp_downloaded_episodes) > 0
        self.dp_open_folder_btn.setVisible(has_episodes)
        self.dp_merge_btn.setVisible(has_episodes)

    def _dp_play_episode(self, ep: int):
        folder = self.dp_folder_input.text().strip()
        local_file = os.path.join(folder, f"EP_{ep:02d}.mp4")
        if not os.path.exists(local_file):
            local_file2 = os.path.join(folder, f"EP_{ep}.mp4")
            if os.path.exists(local_file2):
                local_file = local_file2
        from player import DramaPlayerDialog
        dlg = DramaPlayerDialog(self.active_drama, initial_video_path=local_file if os.path.exists(local_file) else "", parent=self)
        dlg.exec()

    def _dp_set_poster(self, pixmap: QPixmap):
        if sip.isdeleted(self):
            return
        if hasattr(self, "dp_poster_lbl") and not sip.isdeleted(self.dp_poster_lbl):
            try:
                self.dp_poster_lbl.setPixmap(pixmap.scaled(130, 176, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            except Exception:
                pass

    def _dp_toggle_save(self):
        if not self.active_drama:
            return
        series_id = str(self.active_drama.get("series_id", ""))
        tag = self.dp_tag_combo.currentText()
        notes = self.dp_notes_edit.toPlainText().strip()

        if self.db.is_saved(series_id):
            self.db.update_user_info(series_id, tag, notes, 5)
            QMessageBox.information(self, "Saved", "Drama notes updated successfully!")
        else:
            self.db.save_drama(
                series_id=series_id,
                title=self.active_drama.get("title", ""),
                cover=self.active_drama.get("cover", ""),
                episode_cnt=self.active_drama.get("episode_cnt", ""),
                score=self.active_drama.get("score", ""),
                heat=self.active_drama.get("heat", ""),
                status=self.active_drama.get("status", ""),
                user_tag=tag,
                notes=notes
            )
            self.dp_save_btn.setText("✓ Saved in Library")
            self.dp_save_btn.setProperty("class", "SecondaryBtn")
            self.update_saved_count()
            QMessageBox.information(self, "Success", "Added drama to your saved library!")

    def _dp_copy_tag(self):
        if not self.active_drama:
            return
        tag = f"《{self.active_drama.get('title', '')}》"
        QApplication.clipboard().setText(tag)
        QToolTip.showText(QCursor.pos(), f"Copied {tag}", self)

    def _dp_copy_id(self):
        if not self.active_drama:
            return
        sid = str(self.active_drama.get("series_id", ""))
        QApplication.clipboard().setText(sid)
        QToolTip.showText(QCursor.pos(), f"Copied Series ID: {sid}", self)

    def _dp_open_web(self):
        webbrowser.open("https://hongguodownloader.com/Browse")

    def _dp_open_player(self):
        if not self.active_drama:
            return
        from player import DramaPlayerDialog
        dlg = DramaPlayerDialog(self.active_drama, parent=self)
        dlg.exec()

    def _dp_add_to_queue(self):
        if not self.active_drama:
            return
        self.add_to_batch_queue(self.active_drama)
        QMessageBox.information(self, "Added to Queue", f"Added 《{self.active_drama.get('title')}》 to batch download queue!")

    def _dp_browse_folder(self):
        current = self.dp_folder_input.text().strip()
        start_dir = os.path.dirname(current) if current else get_app_dir()
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Save Videos", start_dir or get_app_dir())
        if folder:
            safe_title = sanitize_filename(self.active_drama.get("title", "drama"))
            if os.path.basename(os.path.normpath(folder)) != safe_title:
                folder = os.path.join(folder, safe_title)
            self.dp_folder_input.setText(folder)
            self._dp_scan_downloaded()

    def _dp_start_download(self):
        if not self.active_drama:
            return
        folder = self.dp_folder_input.text().strip()
        if not folder:
            return

        safe_title = sanitize_filename(self.active_drama.get("title", "drama"))
        if os.path.basename(os.path.normpath(folder)) != safe_title:
            folder = os.path.join(folder, safe_title)
            self.dp_folder_input.setText(folder)

        if not self.dp_selected_episodes:
            QMessageBox.warning(self, "No Episodes Selected", "Please select at least one episode to download.")
            return

        # Compress selected episodes into range syntax: e.g. 1-10,15,20-25
        sorted_eps = sorted(list(self.dp_selected_episodes))
        ranges = []
        start = sorted_eps[0]
        prev = sorted_eps[0]
        for ep in sorted_eps[1:]:
            if ep == prev + 1:
                prev = ep
            else:
                ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
                start = ep
                prev = ep
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
        ep_range = ",".join(ranges)

        q_text = self.dp_quality_combo.currentText()
        quality_code = "1080p"
        if "720p" in q_text:
            quality_code = "720p"
        elif "480p" in q_text:
            quality_code = "480p"

        self.dp_start_dl_btn.setEnabled(False)
        self.dp_cancel_dl_btn.setVisible(True)
        self.dp_pbar.setVisible(True)
        self.dp_pbar.setValue(0)
        self.dp_status_lbl.setText("Starting download...")

        self.dp_worker = retain_thread(DramaSeriesDownloadWorker(
            drama=self.active_drama,
            output_folder=folder,
            episodes_range=ep_range,
            quality=quality_code,
            parent=None
        ))
        self.dp_worker.episode_progress.connect(self._dp_on_dl_progress)
        self.dp_worker.status_message.connect(self._dp_on_dl_status)
        self.dp_worker.all_finished.connect(self._dp_on_dl_finished)
        self.dp_worker.start()

    def _dp_cancel_download(self):
        if hasattr(self, "dp_worker") and self.dp_worker and self.dp_worker.isRunning():
            self.dp_worker.cancel()
            self.dp_status_lbl.setText("Cancelling download...")

    def _dp_on_dl_progress(self, cur: int, tot: int, pct: int, speed: float):
        self.dp_pbar.setValue(pct)
        speed_str = f" · {speed:.1f} KB/s" if speed > 0 else ""
        self.dp_status_lbl.setText(f"Downloading Episode {cur}/{tot} ({pct}%){speed_str}...")

    def _dp_on_dl_status(self, msg: str):
        self.dp_status_lbl.setText(msg)

    def _dp_on_dl_finished(self, success: bool, path_or_err: str):
        self.dp_start_dl_btn.setEnabled(True)
        self.dp_cancel_dl_btn.setVisible(False)
        self._dp_scan_downloaded()
        self._dp_render_episode_grid()
        if success:
            self.dp_pbar.setValue(100)
            self.dp_status_lbl.setText(f"✓ Download complete! Saved to: {path_or_err}")
            self.dp_open_folder_btn.setVisible(True)
            self.dp_merge_btn.setVisible(True)
            QMessageBox.information(
                self, "Download Complete",
                f"Downloaded 《{self.active_drama.get('title')}》 successfully!\nSaved to:\n{path_or_err}"
            )
        else:
            self.dp_status_lbl.setText(f"Error: {path_or_err}")
            QMessageBox.critical(self, "Download Failed", f"Failed to download:\n{path_or_err}")

    def _dp_open_folder(self):
        folder = self.dp_folder_input.text().strip()
        if os.path.exists(folder):
            os.startfile(folder)

    def _dp_open_merge(self):
        if not self.active_drama:
            return
        folder = self.dp_folder_input.text().strip()
        dlg = EpisodeMergeDialog(self.active_drama.get("title", "Drama"), folder, self.active_drama, parent=self)
        dlg.exec()

    # ================================================================
    # TAB 1: REAL-TIME WEBSITE CATALOGUE STREAM
    # ================================================================

    def _create_leaderboard_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 4, 18, 4)
        layout.setSpacing(0)

        # Status label (hidden)
        self.lb_status_lbl = QLabel("Loading rankings...")
        self.lb_status_lbl.setStyleSheet("color: #8E7E77; font-size: 11px;")
        self.lb_status_lbl.setVisible(False)
        layout.addWidget(self.lb_status_lbl)
        self.lb_chip_buttons = []

        # Scroll area with responsive Grid (7 columns closed / 5 columns open)
        self.lb_scroll = QScrollArea()
        self.lb_scroll.setWidgetResizable(True)
        self.lb_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lb_scroll.setStyleSheet("border: none; background: transparent;")
        self.lb_grid_container = QWidget()
        self.lb_grid_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lb_grid_container.setStyleSheet("background: transparent;")
        self.lb_grid = QGridLayout(self.lb_grid_container)
        self.lb_grid.setContentsMargins(18, 14, 18, 20)
        self.lb_grid.setSpacing(14)
        self.lb_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lb_scroll.setWidget(self.lb_grid_container)
        layout.addWidget(self.lb_scroll, stretch=1)

        # Connect scroll to auto-fetch next page when reaching bottom
        self.lb_scroll.verticalScrollBar().valueChanged.connect(self._on_grid_scrolled)
        return widget

    def _on_grid_scrolled(self, value: int):
        bar = self.lb_scroll.verticalScrollBar() if hasattr(self, "lb_scroll") else None
        if bar and bar.maximum() > 0 and value >= bar.maximum() - 80:
            if hasattr(self, "cat_worker") and self.cat_worker and self.cat_worker.isRunning():
                return
            if getattr(self, "current_catalogue_page", 1) < getattr(self, "total_catalogue_pages", 1):
                self.current_catalogue_page += 1
                self._load_more_catalogue()

    def _load_more_catalogue(self):
        sort_val = getattr(self, "current_catalogue_sort", "popular")
        genre_val = getattr(self, "current_catalogue_genre", "")
        page_val = getattr(self, "current_catalogue_page", 1)
        q_val = getattr(self, "current_catalogue_q", "")

        self.cat_worker = retain_thread(CatalogueWorker(
            page=page_val,
            sort=sort_val,
            status=getattr(self, "current_catalogue_status", ""),
            genre=genre_val,
            q=q_val,
            parent=None
        ))
        self.cat_worker.finished.connect(self._on_more_catalogue_loaded)
        self.cat_worker.start()

    def _on_more_catalogue_loaded(self, data: Dict[str, Any], error: str):
        if error or not data.get("items"):
            return
        items = data.get("items", [])
        self.current_dramas_list.extend(items)
        cols = self.compute_optimal_columns()
        curr_count = self.lb_grid.count()
        for i, item in enumerate(items):
            idx = curr_count + i
            card = DramaCard(
                item,
                rank=0,
                db=self.db,
                on_saved_changed=self.update_saved_count,
                on_select=self.on_drama_selected
            )
            row = idx // cols
            col = idx % cols
            self.lb_grid.addWidget(card, row, col)

    def _lb_prev_page(self):
        if self.current_catalogue_page > 1:
            self.current_catalogue_page -= 1
            self.load_realtime_catalogue()

    def _lb_next_page(self):
        if self.current_catalogue_page < getattr(self, "total_catalogue_pages", 1):
            self.current_catalogue_page += 1
            self.load_realtime_catalogue()

    def load_realtime_catalogue(self):
        if hasattr(self, "cat_worker") and self.cat_worker and self.cat_worker.isRunning():
            try:
                self.cat_worker.finished.disconnect()
            except Exception:
                pass
            if hasattr(self.cat_worker, "cancel"):
                self.cat_worker.cancel()

        if hasattr(self, "lb_count_lbl"):
            self.lb_count_lbl.setText("⚡ Streaming live dramas from website...")
        if hasattr(self, "lb_grid"):
            self._clear_grid(self.lb_grid)

        sort_val = getattr(self, "current_catalogue_sort", "popular")
        genre_val = getattr(self, "current_catalogue_genre", "")
        page_val = getattr(self, "current_catalogue_page", 1)
        q_val = getattr(self, "current_catalogue_q", "")

        self.cat_worker = retain_thread(CatalogueWorker(
            page=page_val,
            sort=sort_val,
            status=getattr(self, "current_catalogue_status", ""),
            genre=genre_val,
            q=q_val,
            parent=None
        ))
        self.cat_worker.finished.connect(self._on_catalogue_loaded)
        self.cat_worker.start()

    def load_leaderboard(self):
        self.load_realtime_catalogue()

    def _on_leaderboard_loaded(self, items: List[Dict[str, Any]], error: str):
        pass

    # ================================================================
    # TAB 2: CATALOGUE
    # ================================================================

    def _create_catalogue_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 6, 18, 10)
        layout.setSpacing(6)

        # Legacy toolbar container (hidden to avoid duplicating top search frame)
        legacy_toolbar_widget = QWidget()
        legacy_toolbar_widget.setVisible(False)
        toolbar = QHBoxLayout(legacy_toolbar_widget)
        toolbar.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search 40,000+ short dramas (titles, series ID, tags...)")
        self.search_input.returnPressed.connect(self._on_search_triggered)
        toolbar.addWidget(self.search_input, stretch=3)

        search_btn = QPushButton("🔍 Search")
        search_btn.setProperty("class", "PrimaryBtn")
        search_btn.clicked.connect(self._on_search_triggered)
        toolbar.addWidget(search_btn)

        reset_btn = QPushButton("↺ Reset")
        reset_btn.setProperty("class", "SecondaryBtn")
        reset_btn.setToolTip("Reset search and genre filters")
        reset_btn.clicked.connect(self._on_search_reset)
        toolbar.addWidget(reset_btn)

        # Sort combo
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Newest", "newest")
        self.sort_combo.addItem("Most Popular", "popular")
        self.sort_combo.addItem("Most Episodes", "eps")
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.sort_combo)

        # Status combo
        self.status_combo = QComboBox()
        self.status_combo.addItem("All Status", "")
        self.status_combo.addItem("Completed", "completed")
        self.status_combo.addItem("Ongoing", "ongoing")
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.status_combo)

        layout.addWidget(legacy_toolbar_widget)

        # Legacy Genre chips bar (hidden)
        genre_scroll = QScrollArea()
        genre_scroll.setVisible(False)
        self.genre_container = QWidget()
        self.genre_layout = QHBoxLayout(self.genre_container)
        genre_scroll.setWidget(self.genre_container)
        layout.addWidget(genre_scroll)

        # Info & Pager header
        meta_bar = QHBoxLayout()
        meta_bar.setContentsMargins(0, 2, 0, 4)
        self.cat_count_lbl = QLabel("Loading data...")
        self.cat_count_lbl.setStyleSheet("color: #9C8FA8; font-size: 12px; font-weight:600;")
        meta_bar.addWidget(self.cat_count_lbl)
        meta_bar.addStretch()

        self.prev_btn = QPushButton("‹ Prev")
        self.prev_btn.setProperty("class", "SecondaryBtn")
        self.prev_btn.clicked.connect(self._prev_page)
        meta_bar.addWidget(self.prev_btn)

        self.page_lbl = QLabel("Page 1")
        self.page_lbl.setStyleSheet("color: #FFF; font-weight:700; font-size:12px; padding: 0 8px;")
        meta_bar.addWidget(self.page_lbl)

        self.next_btn = QPushButton("Next ›")
        self.next_btn.setProperty("class", "SecondaryBtn")
        self.next_btn.clicked.connect(self._next_page)
        meta_bar.addWidget(self.next_btn)

        layout.addLayout(meta_bar)

        # Scroll area with Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        self.cat_grid_container = QWidget()
        self.cat_grid_container.setStyleSheet("background: transparent;")
        self.cat_grid = QGridLayout(self.cat_grid_container)
        self.cat_grid.setContentsMargins(0, 4, 0, 8)
        self.cat_grid.setSpacing(10)
        self.cat_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.cat_grid_container)

        layout.addWidget(scroll)
        return widget

    def load_genres(self):
        try:
            genres = self.api.get_genres(limit=30)
            # Add "All" chip
            all_btn = QPushButton("All")
            all_btn.setCheckable(True)
            all_btn.setChecked(True)
            all_btn.setProperty("class", "FilterChip")
            all_btn.clicked.connect(lambda: self._select_genre(""))
            self.genre_layout.addWidget(all_btn)
            self.genre_buttons = [all_btn]

            for g in genres:
                name = g.get("genre", "")
                val = g.get("value", name)
                btn = QPushButton(name)
                btn.setCheckable(True)
                btn.setProperty("class", "FilterChip")
                btn.clicked.connect(lambda ch, v=val: self._select_genre(v))
                self.genre_layout.addWidget(btn)
                self.genre_buttons.append(btn)
            self.genre_layout.addStretch()
        except Exception:
            pass

    def _select_genre(self, genre_val: str):
        self.current_catalogue_genre = genre_val
        self.current_catalogue_page = 1
        sender = self.sender()
        if hasattr(self, "genre_buttons"):
            for btn in self.genre_buttons:
                btn.setChecked(btn == sender)
        self.load_catalogue()

    def _on_search_reset(self):
        self.search_input.clear()
        self.current_catalogue_q = ""
        self.current_catalogue_genre = ""
        self.current_catalogue_sort = "newest"
        self.current_catalogue_status = ""
        self.current_catalogue_page = 1
        if hasattr(self, "sort_combo"):
            self.sort_combo.setCurrentIndex(0)
        if hasattr(self, "status_combo"):
            self.status_combo.setCurrentIndex(0)
        if hasattr(self, "genre_buttons") and self.genre_buttons:
            for i, b in enumerate(self.genre_buttons):
                b.setChecked(i == 0)
        self.load_catalogue()

    def _on_search_triggered(self):
        self.current_catalogue_q = self.search_input.text().strip()
        self.current_catalogue_page = 1
        self.load_catalogue()

    def _on_filter_changed(self):
        self.current_catalogue_sort = self.sort_combo.currentData()
        self.current_catalogue_status = self.status_combo.currentData()
        self.current_catalogue_page = 1
        self.load_catalogue()

    def _prev_page(self):
        self._lb_prev_page()

    def _next_page(self):
        self._lb_next_page()

    def load_catalogue(self):
        self.load_realtime_catalogue()

    def _on_catalogue_loaded(self, data: Dict[str, Any], error: str):
        if error:
            if hasattr(self, "lb_count_lbl"):
                self.lb_count_lbl.setText(f"Error: {error}")
            if hasattr(self, "cat_count_lbl"):
                self.cat_count_lbl.setText(f"Error: {error}")
            return

        items = data.get("items", [])
        total_count = data.get("count", len(items))
        self.total_catalogue_pages = data.get("pages", 1)

        # Update Main View Pager
        if hasattr(self, "lb_page_lbl"):
            self.lb_page_lbl.setText(f"Page {self.current_catalogue_page:,} / {self.total_catalogue_pages:,}")
        if hasattr(self, "lb_prev_btn"):
            self.lb_prev_btn.setEnabled(self.current_catalogue_page > 1)
        if hasattr(self, "lb_next_btn"):
            self.lb_next_btn.setEnabled(self.current_catalogue_page < self.total_catalogue_pages)

        # Update Legacy Cat Pager if exists
        if hasattr(self, "page_lbl"):
            self.page_lbl.setText(f"Page {self.current_catalogue_page:,} / {self.total_catalogue_pages:,}")
        if hasattr(self, "prev_btn"):
            self.prev_btn.setEnabled(self.current_catalogue_page > 1)
        if hasattr(self, "next_btn"):
            self.next_btn.setEnabled(self.current_catalogue_page < self.total_catalogue_pages)

        if not items:
            msg = "No dramas found matching your search."
            if hasattr(self, "lb_count_lbl"):
                self.lb_count_lbl.setText(msg)
            if hasattr(self, "cat_count_lbl"):
                self.cat_count_lbl.setText(msg)
            return

        status_text = f"Showing {len(items)} of {total_count:,} dramas · Page {self.current_catalogue_page:,} of {self.total_catalogue_pages:,}"
        if hasattr(self, "lb_count_lbl"):
            self.lb_count_lbl.setText(status_text)
        if hasattr(self, "cat_count_lbl"):
            self.cat_count_lbl.setText(status_text)

        if hasattr(self, "hv_stats_lbl"):
            self.hv_stats_lbl.setText(f"🟢 ⚡ <b>{total_count:,}</b> Dramas · 14,956 AI · 16,225 Animated · Live from 红果")

        self.current_dramas_list = items

        cols = self.compute_optimal_columns()

        drawer_w = 360 if (hasattr(self, "queue_drawer") and self.queue_drawer.isVisible()) else 0
        target_w = self.width() - drawer_w - 16
        card_w = 160
        spacing = 14
        total_w = cols * card_w + (cols - 1) * spacing
        rem = max(0, target_w - total_w)
        side_m = max(18, rem // 2)
        if hasattr(self, "lb_grid"):
            self.lb_grid.setContentsMargins(side_m, 14, side_m, 20)
            self.lb_grid.setSpacing(spacing)

        first_card = None
        for i, item in enumerate(items):
            card = DramaCard(
                item,
                rank=i + 1 if i < 3 else 0,
                db=self.db,
                on_saved_changed=self.update_saved_count,
                on_select=self.on_drama_selected
            )
            row = i // cols
            col = i % cols
            if hasattr(self, "lb_grid"):
                self.lb_grid.addWidget(card, row, col)
            if i == 0:
                first_card = card

        if items:
            self.selected_drama = items[0]
            self.active_drama = items[0]
            self.selected_card_widget = None
            if hasattr(self, "hv_status_lbl"):
                self.hv_status_lbl.setText("● Engine Ready ✓")
            if hasattr(self, "hv_dl_btn"):
                self.hv_dl_btn.setText("⬇ Download")

        # Guarantee scroll position is at the very top (value 0) so Row 1 is never cut off
        if hasattr(self, "lb_scroll"):
            bar = self.lb_scroll.verticalScrollBar()
            bar.setValue(0)
            QTimer.singleShot(0, lambda: bar.setValue(0))
            QTimer.singleShot(50, lambda: bar.setValue(0))
            QTimer.singleShot(150, lambda: bar.setValue(0))
            QTimer.singleShot(300, lambda: bar.setValue(0))

    # ================================================================
    # TAB 3: SAVED STORIES (Favorites Library)
    # ================================================================

    def _create_saved_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # Controls & Filter Bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(10)

        self.saved_search = QLineEdit()
        self.saved_search.setPlaceholderText("Search saved library...")
        self.saved_search.textChanged.connect(self.refresh_saved_list)
        ctrl_bar.addWidget(self.saved_search, stretch=2)

        self.saved_tag_filter = QComboBox()
        self.saved_tag_filter.addItems([
            "All",
            "Plan to Watch",
            "Watching",
            "Completed",
            "Favorite"
        ])
        self.saved_tag_filter.currentIndexChanged.connect(self.refresh_saved_list)
        ctrl_bar.addWidget(self.saved_tag_filter)

        ctrl_bar.addStretch()

        # Batch Export Buttons
        export_txt_btn = QPushButton("📋 Copy All 《》 Tags")
        export_txt_btn.setProperty("class", "SecondaryBtn")
        export_txt_btn.clicked.connect(self._copy_all_saved_tags)
        ctrl_bar.addWidget(export_txt_btn)

        export_json_btn = QPushButton("💾 Export JSON")
        export_json_btn.setProperty("class", "SecondaryBtn")
        export_json_btn.clicked.connect(self._export_saved_json)
        ctrl_bar.addWidget(export_json_btn)

        export_csv_btn = QPushButton("📊 Export CSV")
        export_csv_btn.setProperty("class", "SecondaryBtn")
        export_csv_btn.clicked.connect(self._export_saved_csv)
        ctrl_bar.addWidget(export_csv_btn)

        layout.addLayout(ctrl_bar)

        self.saved_status_lbl = QLabel()
        self.saved_status_lbl.setStyleSheet("color: #B5ACC4; font-size: 13px; font-weight:600;")
        layout.addWidget(self.saved_status_lbl)

        # Scroll Area for Saved Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        self.saved_grid_container = QWidget()
        self.saved_grid_container.setStyleSheet("background: transparent;")
        self.saved_grid = QGridLayout(self.saved_grid_container)
        self.saved_grid.setContentsMargins(0, 4, 0, 8)
        self.saved_grid.setSpacing(10)
        self.saved_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.saved_grid_container)

        layout.addWidget(scroll)
        return widget

    def refresh_saved_list(self):
        self._clear_grid(self.saved_grid)
        tag = self.saved_tag_filter.currentText()
        q = self.saved_search.text().strip()
        saved_items = self.db.get_all_saved(tag_filter=tag, search_q=q)

        self.update_saved_count()
        if not saved_items:
            self.saved_status_lbl.setText("No saved dramas yet. Click ♥ on any drama card to save!")
            return

        self.saved_status_lbl.setText(f"Total Saved: {len(saved_items)} dramas")
        cols = self.compute_optimal_columns()

        first_card = None
        for i, item in enumerate(saved_items):
            card = DramaCard(
                item,
                rank=0,
                db=self.db,
                on_saved_changed=self.refresh_saved_list,
                on_select=self.on_drama_selected
            )
            row = i // cols
            col = i % cols
            self.saved_grid.addWidget(card, row, col)
            if i == 0:
                first_card = card

        if saved_items and not self.selected_drama and first_card:
            self.on_drama_selected(saved_items[0], first_card)

    def _copy_all_saved_tags(self):
        items = self.db.get_all_saved()
        if not items:
            QMessageBox.information(self, "No Data", "No saved dramas found in your library!")
            return
        tags = "\n".join([f"《{x['title']}》" for x in items])
        QApplication.clipboard().setText(tags)
        QMessageBox.information(self, "Copied", f"Copied 《》 tags for {len(items)} dramas to clipboard!")

    def _export_saved_json(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Saved Dramas to JSON", "saved_dramas.json", "JSON Files (*.json)")
        if file_path:
            if self.db.export_to_json(file_path):
                QMessageBox.information(self, "Success", f"All dramas exported to:\n{file_path}")
            else:
                QMessageBox.critical(self, "Failed", "Export failed!")

    def _export_saved_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Saved Dramas to CSV", "saved_dramas.csv", "CSV Files (*.csv)")
        if file_path:
            if self.db.export_to_csv(file_path):
                QMessageBox.information(self, "Success", f"Exported to CSV successfully:\n{file_path}")
            else:
                QMessageBox.critical(self, "Failed", "Export failed!")

    # ================================================================
    # TAB 4: DOWNLOADER HUB
    # ================================================================

    def add_to_batch_queue(self, drama: Dict[str, Any]):
        sid = str(drama.get("series_id", ""))
        for item in self.download_queue:
            if str(item.get("series_id", "")) == sid:
                QMessageBox.information(self, "Already in Queue", f"《{drama.get('title')}》 is already in the queue!")
                return
        self.download_queue.append(drama)
        self._refresh_batch_queue_ui()
        self.statusBar().showMessage(f"✓ Added 《{drama.get('title')}》 to download queue ({len(self.download_queue)} total)", 4000)

    def _create_downloader_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        c_layout = QVBoxLayout(scroll_content)
        c_layout.setContentsMargins(6, 6, 6, 6)
        c_layout.setSpacing(14)

        # -------------------------------------------------------------
        # Section 1: Multi-Series Batch Downloader
        # -------------------------------------------------------------
        box_batch = QFrame()
        box_batch.setStyleSheet("background-color: #181322; border: 1px solid #2F2440; border-radius: 14px; padding: 16px;")
        b_layout = QVBoxLayout(box_batch)
        b_layout.setSpacing(12)

        header_row = QHBoxLayout()
        s1_title = QLabel("🚀 1. Multi-Series Batch Downloader (Download Multiple Dramas)")
        s1_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        header_row.addWidget(s1_title)
        header_row.addStretch()

        self.queue_badge = QLabel("0 dramas in Queue")
        self.queue_badge.setStyleSheet("background: #2D233D; color: #FFA566; font-size: 12px; font-weight: 700; border-radius: 8px; padding: 4px 10px;")
        header_row.addWidget(self.queue_badge)
        b_layout.addLayout(header_row)

        s1_desc = QLabel("Queue multiple dramas to download all 1080p MP4 episodes automatically in parallel.")
        s1_desc.setStyleSheet("color: #B5ACC4; font-size: 13px;")
        b_layout.addWidget(s1_desc)

        # Quick Add / Import Controls
        q_ctrl_bar = QHBoxLayout()
        q_ctrl_bar.setSpacing(8)

        self.manual_q_input = QLineEdit()
        self.manual_q_input.setPlaceholderText("Enter Series ID or 《Drama Title》 (e.g. 7683551766050245656)...")
        self.manual_q_input.returnPressed.connect(self._add_manual_to_queue)
        q_ctrl_bar.addWidget(self.manual_q_input, stretch=2)

        add_manual_btn = QPushButton("➕ Add")
        add_manual_btn.setProperty("class", "PrimaryBtn")
        add_manual_btn.clicked.connect(self._add_manual_to_queue)
        q_ctrl_bar.addWidget(add_manual_btn)

        import_saved_btn = QPushButton("⭐ Import from Saved")
        import_saved_btn.setProperty("class", "SecondaryBtn")
        import_saved_btn.clicked.connect(self._import_all_saved_to_queue)
        q_ctrl_bar.addWidget(import_saved_btn)

        clear_q_btn = QPushButton("🗑 Clear Queue")
        clear_q_btn.setProperty("class", "SecondaryBtn")
        clear_q_btn.clicked.connect(self._clear_batch_queue)
        q_ctrl_bar.addWidget(clear_q_btn)

        b_layout.addLayout(q_ctrl_bar)

        # Queue List Container
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setFixedHeight(180)
        self.queue_scroll.setWidgetResizable(True)
        self.queue_container = QWidget()
        self.queue_items_layout = QVBoxLayout(self.queue_container)
        self.queue_items_layout.setContentsMargins(6, 6, 6, 6)
        self.queue_items_layout.setSpacing(6)
        self.queue_scroll.setWidget(self.queue_container)
        b_layout.addWidget(self.queue_scroll)

        # Settings Row (Series at once, Quality, Concurrency)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        at_once_lbl = QLabel("Concurrent:")
        at_once_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        self.series_at_once_combo = QComboBox()
        self.series_at_once_combo.addItem("2 Dramas at once (Recommended)", 2)
        self.series_at_once_combo.addItem("3 Dramas at once", 3)
        self.series_at_once_combo.addItem("1 Drama at a time (Sequential)", 1)
        self.series_at_once_combo.addItem("4 Dramas at once", 4)
        settings_row.addWidget(at_once_lbl)
        settings_row.addWidget(self.series_at_once_combo)

        qual_lbl = QLabel("Quality:")
        qual_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        self.batch_quality_combo = QComboBox()
        self.batch_quality_combo.addItem("1080p (Full HD)", "1080p")
        self.batch_quality_combo.addItem("720p (HD)", "720p")
        settings_row.addWidget(qual_lbl)
        settings_row.addWidget(self.batch_quality_combo)

        conc_lbl = QLabel("Threads:")
        conc_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        self.batch_conc_combo = QComboBox()
        self.batch_conc_combo.addItem("4 Threads (Default)", 4)
        self.batch_conc_combo.addItem("6 Threads (Fast)", 6)
        self.batch_conc_combo.addItem("2 Threads (Light)", 2)
        settings_row.addWidget(conc_lbl)
        settings_row.addWidget(self.batch_conc_combo)

        settings_row.addStretch()
        b_layout.addLayout(settings_row)

        # Output Folder Row
        folder_row = QHBoxLayout()
        f_lbl = QLabel("Save Folder:")
        f_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        folder_row.addWidget(f_lbl)

        self.batch_out_input = QLineEdit()
        default_v_folder = os.path.join(get_app_dir(), "Downloaded_Videos")
        self.batch_out_input.setText(default_v_folder)
        folder_row.addWidget(self.batch_out_input, stretch=2)

        browse_batch_btn = QPushButton("📁 Browse Folder")
        browse_batch_btn.setProperty("class", "SecondaryBtn")
        browse_batch_btn.clicked.connect(self._browse_batch_folder)
        folder_row.addWidget(browse_batch_btn)
        b_layout.addLayout(folder_row)

        # Actions & Progress Row
        act_row = QHBoxLayout()
        self.start_batch_btn = QPushButton("⬇ Start Batch Download")
        self.start_batch_btn.setProperty("class", "PrimaryBtn")
        self.start_batch_btn.clicked.connect(self._start_batch_download)
        act_row.addWidget(self.start_batch_btn)

        self.cancel_batch_btn = QPushButton("⏹ Cancel")
        self.cancel_batch_btn.setProperty("class", "SecondaryBtn")
        self.cancel_batch_btn.setEnabled(False)
        self.cancel_batch_btn.clicked.connect(self._cancel_batch_download)
        act_row.addWidget(self.cancel_batch_btn)

        act_row.addStretch()
        b_layout.addLayout(act_row)

        # Batch Progress Bar & Log
        self.batch_pbar = QProgressBar()
        self.batch_pbar.setVisible(False)
        b_layout.addWidget(self.batch_pbar)

        self.batch_log_lbl = QLabel()
        self.batch_log_lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        b_layout.addWidget(self.batch_log_lbl)

        c_layout.addWidget(box_batch)

        # -------------------------------------------------------------
        # Section 2: Merge All Episodes to Full Movie
        # -------------------------------------------------------------
        box_merge = QFrame()
        box_merge.setStyleSheet("background-color: #181322; border: 1px solid #2F2440; border-radius: 14px; padding: 16px;")
        m_layout = QVBoxLayout(box_merge)
        m_layout.setSpacing(12)

        s2_title = QLabel("🎬 2. Merge All Episodes (Combine into Full Movie)")
        s2_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        m_layout.addWidget(s2_title)

        s2_desc = QLabel("Combine all downloaded .mp4 episodes into a single lossless Full Movie MP4 with chapter markers.")
        s2_desc.setStyleSheet("color: #B5ACC4; font-size: 13px;")
        m_layout.addWidget(s2_desc)

        merge_ctrl_bar = QHBoxLayout()
        merge_ctrl_bar.setSpacing(10)

        m_combo_lbl = QLabel("Downloaded Drama:")
        m_combo_lbl.setStyleSheet("color: #DDD; font-size: 12px; font-weight: 600;")
        merge_ctrl_bar.addWidget(m_combo_lbl)

        self.merge_drama_combo = QComboBox()
        self.merge_drama_combo.setMinimumWidth(260)
        self.merge_drama_combo.currentIndexChanged.connect(self._check_selected_merge_has_full)
        merge_ctrl_bar.addWidget(self.merge_drama_combo, stretch=2)

        scan_btn = QPushButton("🔄 Scan")
        scan_btn.setProperty("class", "SecondaryBtn")
        scan_btn.clicked.connect(self._refresh_merge_drama_list)
        merge_ctrl_bar.addWidget(scan_btn)

        browse_custom_m_btn = QPushButton("📁 Browse Folder")
        browse_custom_m_btn.setProperty("class", "SecondaryBtn")
        browse_custom_m_btn.clicked.connect(self._browse_custom_merge_folder)
        merge_ctrl_bar.addWidget(browse_custom_m_btn)

        self.start_merge_action_btn = QPushButton("🎬 Merge All Episodes Now")
        self.start_merge_action_btn.setProperty("class", "PrimaryBtn")
        self.start_merge_action_btn.clicked.connect(self._start_selected_merge)
        merge_ctrl_bar.addWidget(self.start_merge_action_btn)

        self.play_full_m_btn = QPushButton("▶ Play Full Movie")
        self.play_full_m_btn.setProperty("class", "SecondaryBtn")
        self.play_full_m_btn.setVisible(False)
        self.play_full_m_btn.clicked.connect(self._play_selected_merged)
        merge_ctrl_bar.addWidget(self.play_full_m_btn)

        m_layout.addLayout(merge_ctrl_bar)

        self.merge_info_lbl = QLabel()
        self.merge_info_lbl.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 600;")
        m_layout.addWidget(self.merge_info_lbl)

        c_layout.addWidget(box_merge)

        # -------------------------------------------------------------
        # Section 3: Batch Poster HD Downloader
        # -------------------------------------------------------------
        box_poster = QFrame()
        box_poster.setStyleSheet("background-color: #181322; border: 1px solid #2F2440; border-radius: 14px; padding: 16px;")
        p_layout = QVBoxLayout(box_poster)
        p_layout.setSpacing(12)

        s3_title = QLabel("🖼 3. Batch Poster HD Downloader")
        s3_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        p_layout.addWidget(s3_title)

        s3_desc = QLabel("Download high-definition posters for all saved dramas to your local folder at once.")
        s3_desc.setStyleSheet("color: #B5ACC4; font-size: 13px;")
        p_layout.addWidget(s3_desc)

        path_layout = QHBoxLayout()
        self.poster_path_input = QLineEdit()
        default_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Downloaded_Posters")
        self.poster_path_input.setText(default_folder)
        browse_btn = QPushButton("📁 Browse Folder")
        browse_btn.setProperty("class", "SecondaryBtn")
        browse_btn.clicked.connect(self._browse_poster_folder)
        path_layout.addWidget(self.poster_path_input)
        path_layout.addWidget(browse_btn)
        p_layout.addLayout(path_layout)

        p_btn_layout = QHBoxLayout()
        self.batch_dl_btn = QPushButton("⬇ Download All Posters")
        self.batch_dl_btn.setProperty("class", "PrimaryBtn")
        self.batch_dl_btn.clicked.connect(self._start_batch_poster_download)
        p_btn_layout.addWidget(self.batch_dl_btn)
        p_btn_layout.addStretch()
        p_layout.addLayout(p_btn_layout)

        self.poster_pbar = QProgressBar()
        self.poster_pbar.setVisible(False)
        p_layout.addWidget(self.poster_pbar)

        self.poster_log = QLabel()
        self.poster_log.setStyleSheet("color: #FF8F55; font-size: 12px; font-weight: 600;")
        p_layout.addWidget(self.poster_log)

        c_layout.addWidget(box_poster)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Initial UI populate
        self._refresh_batch_queue_ui()
        self._refresh_merge_drama_list()

        return widget

    # -----------------------------------------------------------------
    # Batch Downloader Helpers
    # -----------------------------------------------------------------

    def _refresh_batch_queue_ui(self):
        if not hasattr(self, "queue_items_layout"):
            return

        while self.queue_items_layout.count():
            item = self.queue_items_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if hasattr(self, "queue_badge"):
            self.queue_badge.setText(f"{len(self.download_queue)} dramas in Queue")

        if not self.download_queue:
            empty_lbl = QLabel("No dramas in queue. Click '➕' on drama cards or '⭐ Import from Saved' to download together!")
            empty_lbl.setStyleSheet("color: #8E82A1; font-size: 12px; font-style: italic; padding: 12px;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.queue_items_layout.addWidget(empty_lbl)
            return

        self.queue_status_labels: Dict[str, QLabel] = {}

        for drama in self.download_queue:
            sid = str(drama.get("series_id", ""))
            title = drama.get("title", "Drama")
            eps = drama.get("episode_cnt", "?")

            row_frame = QFrame()
            row_frame.setStyleSheet("background-color: #211A2E; border: 1px solid #36294C; border-radius: 8px; padding: 6px 10px;")
            r_layout = QHBoxLayout(row_frame)
            r_layout.setContentsMargins(6, 4, 6, 4)
            r_layout.setSpacing(10)

            icon_lbl = QLabel("🎬")
            icon_lbl.setStyleSheet("font-size: 16px;")
            r_layout.addWidget(icon_lbl)

            t_lbl = QLabel(f"<b>{title}</b> <span style='color:#B5ACC4;'>(ID: {sid} | {eps} Eps)</span>")
            t_lbl.setStyleSheet("color: #FFF; font-size: 12px;")
            r_layout.addWidget(t_lbl, stretch=2)

            st_lbl = QLabel("⏳ Queued")
            st_lbl.setStyleSheet("color: #FFA566; font-size: 11px; font-weight: 700; background: #2A1F3B; padding: 2px 8px; border-radius: 6px;")
            self.queue_status_labels[sid] = st_lbl
            r_layout.addWidget(st_lbl)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet("background: transparent; color: #FF4571; font-weight: 800; border: none;")
            del_btn.setToolTip("Remove from queue")
            del_btn.clicked.connect(lambda ch, s=sid: self._remove_from_batch_queue(s))
            r_layout.addWidget(del_btn)

            self.queue_items_layout.addWidget(row_frame)

    def _add_manual_to_queue(self):
        text = self.manual_q_input.text().strip()
        if not text:
            return

        clean_text = text.replace("《", "").replace("》", "").strip()

        if clean_text.isdigit():
            drama_item = {"series_id": clean_text, "title": f"Series_{clean_text}", "episode_cnt": 0}
            self.add_to_batch_queue(drama_item)
            self.manual_q_input.clear()
            return

        try:
            res = self.api.get_catalogue(q=clean_text, size=1)
            items = res.get("items", [])
            if items:
                self.add_to_batch_queue(items[0])
                self.manual_q_input.clear()
            else:
                QMessageBox.warning(self, "Not Found", f"Could not find drama '{clean_text}'. Try entering the numeric Series ID directly.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to search: {e}")

    def _import_all_saved_to_queue(self):
        saved = self.db.get_all_saved()
        if not saved:
            QMessageBox.information(self, "No Saved Dramas", "No dramas found in your saved library.")
            return
        added = 0
        existing_sids = {str(d.get("series_id", "")) for d in self.download_queue}
        for item in saved:
            sid = str(item.get("series_id", ""))
            if sid not in existing_sids:
                self.download_queue.append(item)
                existing_sids.add(sid)
                added += 1
        self._refresh_batch_queue_ui()
        QMessageBox.information(self, "Import Successful", f"Added {added} drama(s) from Saved Library into the download queue!")

    def _remove_from_batch_queue(self, series_id: str):
        self.download_queue = [d for d in self.download_queue if str(d.get("series_id", "")) != str(series_id)]
        self._refresh_batch_queue_ui()

    def _clear_batch_queue(self):
        if not self.download_queue:
            return
        self.download_queue.clear()
        self._refresh_batch_queue_ui()

    def _browse_batch_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Save Videos", self.batch_out_input.text())
        if folder:
            self.batch_out_input.setText(folder)

    def _start_batch_download(self):
        if not self.download_queue:
            QMessageBox.warning(self, "Queue Empty", "No dramas in download queue. Add dramas to queue first!")
            return

        out_dir = self.batch_out_input.text().strip()
        if not out_dir:
            return

        series_at_once = self.series_at_once_combo.currentData() or 2
        quality = self.batch_quality_combo.currentData() or "1080p"
        concurrency = self.batch_conc_combo.currentData() or 4

        self.start_batch_btn.setEnabled(False)
        self.cancel_batch_btn.setEnabled(True)
        self.batch_pbar.setVisible(True)
        self.batch_pbar.setValue(0)
        self.batch_log_lbl.setText(f"Starting batch download for {len(self.download_queue)} drama(s) ({series_at_once} concurrent)...")

        self.batch_worker = retain_thread(BatchSeriesDownloadWorker(
            series_list=self.download_queue,
            output_dir=out_dir,
            quality=quality,
            series_at_once=series_at_once,
            concurrency=concurrency,
            parent=None
        ))
        self.batch_worker.total_progress.connect(self._on_batch_total_progress)
        self.batch_worker.series_progress.connect(self._on_batch_series_progress)
        self.batch_worker.status_message.connect(self._on_batch_status_message)
        self.batch_worker.all_finished.connect(self._on_batch_all_finished)
        self.batch_worker.start()

    def _cancel_batch_download(self):
        if self.batch_worker:
            self.batch_worker.cancel()
            self.batch_log_lbl.setText("Cancelling batch download...")

    def _on_batch_total_progress(self, done_series: int, total_series: int, total_pct: int):
        self.batch_pbar.setValue(total_pct)
        self.batch_log_lbl.setText(f"Overall Progress: {done_series}/{total_series} Dramas ({total_pct}%)")

    def _on_batch_series_progress(self, series_title: str, done_eps: int, total_eps: int, status: str):
        if hasattr(self, "queue_status_labels"):
            for d in self.download_queue:
                if d.get("title") == series_title or series_title in d.get("title", ""):
                    sid = str(d.get("series_id", ""))
                    if sid in self.queue_status_labels:
                        lbl = self.queue_status_labels[sid]
                        if status == "done" or done_eps >= total_eps:
                            lbl.setText(f"✓ Done ({done_eps}/{total_eps})")
                            lbl.setStyleSheet("color: #4ADE80; font-size: 11px; font-weight: 700; background: #132E20; padding: 2px 8px; border-radius: 6px;")
                        else:
                            pct = int(done_eps * 100 / max(total_eps, 1))
                            lbl.setText(f"⚡ {done_eps}/{total_eps} ({pct}%)")
                            lbl.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 700; background: #152B3C; padding: 2px 8px; border-radius: 6px;")

    def _on_batch_status_message(self, msg: str):
        self.batch_log_lbl.setText(msg)

    def _on_batch_all_finished(self, success: bool, path_or_err: str):
        self.start_batch_btn.setEnabled(True)
        self.cancel_batch_btn.setEnabled(False)
        self._refresh_merge_drama_list()

        if success:
            self.batch_pbar.setValue(100)
            self.batch_log_lbl.setText("✓ All queued dramas downloaded successfully!")
            msg = QMessageBox(self)
            msg.setWindowTitle("🎉 Download Complete")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("<b>🎉 Batch Download Completed Successfully!</b>")
            msg.setInformativeText(
                f"<div style='margin-top: 6px; line-height: 1.6;'>"
                f"📁 <b>Save Location:</b><br>"
                f"<span style='color: #FF8A47; font-weight: 600;'>{path_or_err}</span><br><br>"
                f"🎬 <i>You can now switch to <b>'Merge'</b> to combine episodes into a Full Movie!</i>"
                f"</div>"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        else:
            self.batch_log_lbl.setText(f"Download finished: {path_or_err}")

    # -----------------------------------------------------------------
    # Merge Episodes Section Helpers
    # -----------------------------------------------------------------

    def _refresh_merge_drama_list(self):
        if not hasattr(self, "merge_drama_combo"):
            return

        self.merge_drama_combo.clear()
        base_dir = os.path.join(get_app_dir(), "Downloaded_Videos")

        found_folders = []
        if os.path.exists(base_dir):
            for entry in sorted(os.listdir(base_dir)):
                ep_dir = os.path.join(base_dir, entry)
                if os.path.isdir(ep_dir):
                    mp4s = [f for f in os.listdir(ep_dir) if f.lower().endswith(".mp4") and "full" not in f.lower() and "merged" not in f.lower()]
                    if mp4s:
                        found_folders.append((entry, ep_dir, len(mp4s)))

        if not found_folders:
            self.merge_drama_combo.addItem("No downloaded dramas found in Downloaded_Videos", "")
            self.start_merge_action_btn.setEnabled(False)
            self.play_full_m_btn.setVisible(False)
            self.merge_info_lbl.setText("Please download a drama first or click '📁 Browse Folder'")
            return

        self.start_merge_action_btn.setEnabled(True)
        for name, path, count in found_folders:
            has_full = any("full" in f.lower() or "merged" in f.lower() for f in os.listdir(path) if f.lower().endswith(".mp4"))
            badge = " [✓ Full Movie exists]" if has_full else ""
            self.merge_drama_combo.addItem(f"{name} ({count} Eps){badge}", path)

        self.merge_info_lbl.setText(f"Found {len(found_folders)} downloaded drama(s).")
        self._check_selected_merge_has_full()

    def _check_selected_merge_has_full(self):
        if not hasattr(self, "merge_drama_combo"):
            return
        folder = self.merge_drama_combo.currentData()
        if folder and os.path.exists(folder):
            full_movies = [f for f in os.listdir(folder) if f.lower().endswith(".mp4") and ("full" in f.lower() or "merged" in f.lower())]
            has_full = bool(full_movies)
            self.play_full_m_btn.setVisible(has_full)
        else:
            self.play_full_m_btn.setVisible(False)

    def _browse_custom_merge_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Drama Folder to Merge", os.getcwd())
        if folder:
            name = os.path.basename(folder)
            mp4s = [f for f in os.listdir(folder) if f.lower().endswith(".mp4")]
            self.merge_drama_combo.insertItem(0, f"📁 {name} ({len(mp4s)} Eps)", folder)
            self.merge_drama_combo.setCurrentIndex(0)
            self.start_merge_action_btn.setEnabled(True)
            self._check_selected_merge_has_full()

    def _start_selected_merge(self):
        folder = self.merge_drama_combo.currentData()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "No Folder", "Please select a downloaded drama folder!")
            return

        drama_name = os.path.basename(folder)
        info_path = os.path.join(folder, "info.json")
        drama_info = {}
        if os.path.exists(info_path):
            try:
                with open(info_path, "r", encoding="utf-8") as f:
                    drama_info = json.load(f)
            except Exception:
                pass

        dlg = EpisodeMergeDialog(drama_name, folder, drama_info, parent=self)
        dlg.exec()
        self._refresh_merge_drama_list()

    def _play_selected_merged(self):
        folder = self.merge_drama_combo.currentData()
        if not folder or not os.path.exists(folder):
            return

        full_movies = [f for f in os.listdir(folder) if f.lower().endswith(".mp4") and ("full" in f.lower() or "merged" in f.lower())]
        if full_movies:
            full_path = os.path.join(folder, full_movies[0])
            from player import DramaPlayerDialog
            dummy_drama = {"title": os.path.basename(full_path), "series_id": "local"}
            dlg = DramaPlayerDialog(dummy_drama, initial_video_path=full_path, parent=self)
            dlg.exec()

    # -----------------------------------------------------------------
    # Poster Downloader Helpers
    # -----------------------------------------------------------------

    def _browse_poster_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Save Posters")
        if folder:
            self.poster_path_input.setText(folder)

    def _start_batch_poster_download(self):
        saved_dramas = self.db.get_all_saved()
        if not saved_dramas:
            QMessageBox.warning(self, "No Data", "No saved dramas found. Please save dramas to your library first!")
            return

        target_dir = self.poster_path_input.text().strip()
        if not target_dir:
            return

        self.batch_dl_btn.setEnabled(False)
        self.poster_pbar.setVisible(True)
        self.poster_pbar.setValue(0)
        self.poster_pbar.setMaximum(len(saved_dramas))
        self.poster_log.setText(f"Downloading 0 / {len(saved_dramas)}...")

        self.poster_worker = retain_thread(BatchPosterDownloadWorker(saved_dramas, target_dir, parent=None))
        self.poster_worker.item_downloaded.connect(self._on_poster_item_downloaded)
        self.poster_worker.all_finished.connect(self._on_batch_posters_finished)
        self.poster_worker.start()

    def _on_poster_item_downloaded(self, current, total, filename):
        self.poster_pbar.setValue(current)
        self.poster_log.setText(f"Downloaded ({current}/{total}): {filename}")

    def _on_batch_posters_finished(self, success, failed):
        self.batch_dl_btn.setEnabled(True)
        self.poster_log.setText(f"✓ Complete! Succeeded: {success} | Failed: {failed}")
        QMessageBox.information(
            self, "Download Complete",
            f"Poster download complete!\nSuccess: {success}\nFailed: {failed}\nLocation: {self.poster_path_input.text()}"
        )

    # ================================================================
    # TAB 5: GUIDE & HELP (Tutorial & FAQ)
    # ================================================================

    def _create_guide_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_widget = QWidget()
        c_layout = QVBoxLayout(content_widget)
        c_layout.setContentsMargins(10, 10, 10, 20)
        c_layout.setSpacing(16)

        # Header Title
        title_banner = QLabel("📖 User Guide & Hongguo Drama Tutorial")
        title_banner.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        c_layout.addWidget(title_banner)

        sub_banner = QLabel("Step-by-step instructions to find, download HD posters, and watch short dramas on PC:")
        sub_banner.setStyleSheet("color: #B5ACC4; font-size: 13px;")
        c_layout.addWidget(sub_banner)

        # Step 1 Card
        card1 = QFrame()
        card1.setProperty("class", "GuideCard")
        c1_layout = QVBoxLayout(card1)
        c1_layout.setSpacing(8)

        h1 = QHBoxLayout()
        b1 = QLabel("STEP 1")
        b1.setProperty("class", "GuideStepBadge")
        t1 = QLabel(" 🔍 Search & Bookmark Dramas")
        t1.setProperty("class", "GuideTitle")
        h1.addWidget(b1)
        h1.addWidget(t1)
        h1.addStretch()
        c1_layout.addLayout(h1)

        d1 = QLabel(
            "• Explore trending short dramas in <b>🏆 Leaderboard</b> or <b>🎬 Catalogue</b> from 40,000+ available titles.<br>"
            "• Click the heart button <b>♥</b> on any drama card to bookmark it into your personal <b>⭐ Library</b>.<br>"
            "• Organize your collection using status tags (<i>Plan to Watch, Watching, Completed, Favorite</i>) and custom notes."
        )
        d1.setProperty("class", "GuideDesc")
        c1_layout.addWidget(d1)
        c_layout.addWidget(card1)

        # Step 2 Card
        card2 = QFrame()
        card2.setProperty("class", "GuideCard")
        c2_layout = QVBoxLayout(card2)
        c2_layout.setSpacing(8)

        h2 = QHBoxLayout()
        b2 = QLabel("STEP 2")
        b2.setProperty("class", "GuideStepBadge")
        t2 = QLabel(" 🖼 Batch Poster HD Downloader")
        t2.setProperty("class", "GuideTitle")
        h2.addWidget(b2)
        h2.addWidget(t2)
        h2.addStretch()
        c2_layout.addLayout(h2)

        d2 = QLabel(
            "• Go to the <b>📥 Downloader Hub</b> tab.<br>"
            "• In Section 3, choose your preferred target folder using <b>'📁 Browse Folder'</b>.<br>"
            "• Click <b>'⬇ Download All Posters'</b> to automatically download crystal-clear HD posters for all your saved dramas."
        )
        d2.setProperty("class", "GuideDesc")
        c2_layout.addWidget(d2)
        c_layout.addWidget(card2)

        # Step 3 Card (Video Download Engine Explanation)
        card3 = QFrame()
        card3.setProperty("class", "GuideCard")
        c3_layout = QVBoxLayout(card3)
        c3_layout.setSpacing(8)

        h3 = QHBoxLayout()
        b3 = QLabel("STEP 3")
        b3.setProperty("class", "GuideStepBadge")
        t3 = QLabel(" 🚀 Download 1080p MP4 Episodes")
        t3.setProperty("class", "GuideTitle")
        h3.addWidget(b3)
        h3.addWidget(t3)
        h3.addStretch()
        c3_layout.addLayout(h3)

        d3 = QLabel(
            "<b>How to download full drama episodes:</b><br>"
            "Hongguo uses the title tag format <b>《Drama Title》</b> to fetch all episodes via the downloader engine.<br><br>"
            "<b>Quick 3-step download process:</b><br>"
            "1. On any drama card, click <b>'《》'</b> to copy the drama code (e.g., <code>《糯糯下山,众师兄们都慌了番外篇第三季》</code>).<br>"
            "2. Click <b>'⬇ Download'</b> or <b>'➕'</b> to add directly to the <b>Multi-Series Batch Downloader</b> in the Downloader Hub.<br>"
            "3. Click <b>'Start Batch Download'</b> to retrieve all episodes in <b>1080p MP4</b> directly to your PC without needing any login!<br>"
            "👉 All episodes will be downloaded in high-definition <b>1080p MP4</b> to your selected folder!"
        )
        d3.setProperty("class", "GuideDesc")
        c3_layout.addWidget(d3)
        c_layout.addWidget(card3)

        # Step 4 Card (Watch In-App)
        card4 = QFrame()
        card4.setProperty("class", "GuideCard")
        c4_layout = QVBoxLayout(card4)
        c4_layout.setSpacing(8)

        h4 = QHBoxLayout()
        b4 = QLabel("STEP 4")
        b4.setProperty("class", "GuideStepBadge")
        t4 = QLabel(" ▶ Built-in Video Player & Playback")
        t4.setProperty("class", "GuideTitle")
        h4.addWidget(b4)
        h4.addWidget(t4)
        h4.addStretch()
        c4_layout.addLayout(h4)

        d4 = QLabel(
            "• Click <b>'▶ Play'</b> on any drama card or detail modal to open the built-in cinema player immediately.<br>"
            "• The player will open instantly in-app:<br>"
            "  - <b>Local Episodes</b>: If you downloaded episodes locally, it will display the episode playlist (EP 01, EP 02...) for one-click playback<br>"
            "  - <b>Open Video File</b>: Click <i>'📁 Open Video File'</i> to select any video file from your computer<br>"
            "  - <b>Online Stream</b>: Click <i>'🔗 Play Online Stream'</i> to stream video directly without downloading<br>"
            "  - <b>Watch on Hongguo Web</b>: Click <i>'🌐 Watch on Hongguo Web'</i> to open on the official web portal."
        )
        d4.setProperty("class", "GuideDesc")
        c4_layout.addWidget(d4)
        c_layout.addWidget(card4)

        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
        return widget

    # ================================================================
    # Utilities
    # ================================================================

    def _clear_grid(self, grid: QGridLayout):
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def closeEvent(self, event):
        try:
            QThreadPool.globalInstance().clear()
        except Exception:
            pass
        for worker_name in ["lb_worker", "cat_worker", "_bg_update_worker", "batch_worker", "poster_worker", "dp_worker"]:
            worker = getattr(self, worker_name, None)
            if worker and worker.isRunning():
                try:
                    worker.finished.disconnect()
                except Exception:
                    pass
                if hasattr(worker, "cancel"):
                    worker.cancel()
        super().closeEvent(event)


# ====================================================================
# Main Entry Point
# ====================================================================

def main():
    # Set Windows AppUserModelID so Taskbar shows custom icon instead of generic Python icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hongguo.DramaDownloader.App.1.0")
    except Exception:
        pass

    # Enable High DPI scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setApplicationName("Hongguo Drama Downloader")

    # Dark Aesthetic Palette for crystal clear text on all dialogs
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#140F1D"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#F5EEFD"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1C1628"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#221A30"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2B213E"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#F5EEFD"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#251D34"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#FF4D26"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet(MAIN_STYLESHEET)

    # Set App Icon
    candidate_icons = [
        os.path.join(get_app_dir(), "icon.png"),
        os.path.join(get_app_dir(), "icon.ico"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "icon.png"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "icon.ico"),
    ]
    for ic in candidate_icons:
        if ic and os.path.exists(ic):
            app.setWindowIcon(QIcon(ic))
            break

    # License check removed - Launch Main Window directly in Maximized mode
    window = HongguoMainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
