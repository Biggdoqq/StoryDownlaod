"""
Built-in Video Player for Hongguo Dramas (PyQt6 QtMultimedia)
Allows watching downloaded episodes, opening local video files,
or streaming direct URLs directly inside the application.
"""

import os
import webbrowser
from typing import Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFileDialog, QInputDialog, QMessageBox,
    QFrame, QListWidget, QListWidgetItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl, QTime
from PyQt6.QtGui import QIcon, QFont, QCursor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from downloader import sanitize_filename, get_app_dir


class DramaPlayerDialog(QDialog):
    def __init__(self, drama: Dict[str, Any], initial_video_path: str = "", parent=None):
        super().__init__(parent)
        self.drama = drama
        self.title = drama.get("title", "Hongguo Drama")
        self.series_id = str(drama.get("series_id", ""))
        self.initial_video_path = initial_video_path
        self._is_fullscreen = False

        self.setWindowTitle(f"▶ Cinema Player: {self.title}")
        self.resize(980, 620)
        self.setMinimumSize(800, 500)

        # Initialize Qt Multimedia Player
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.85)

        self.init_ui()
        self.init_connections()
        self._scan_local_episodes()

        if self.initial_video_path and os.path.exists(self.initial_video_path):
            self.load_video(self.initial_video_path)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # Left Column: Video Screen + Playback Controls
        left_box = QVBoxLayout()
        left_box.setSpacing(10)

        # Top Title Bar
        title_bar = QHBoxLayout()
        self.title_lbl = QLabel(f"🎬 {self.title}")
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        title_bar.addWidget(self.title_lbl)
        title_bar.addStretch()

        self.status_tag = QLabel("Ready")
        self.status_tag.setStyleSheet("color: #FF8F55; font-size: 12px; font-weight: 600;")
        title_bar.addWidget(self.status_tag)
        left_box.addLayout(title_bar)

        # Video Screen Container
        self.video_container = QFrame()
        self.video_container.setStyleSheet("background-color: #000000; border-radius: 12px; border: 1px solid #2F2440;")
        vc_layout = QVBoxLayout(self.video_container)
        vc_layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)
        vc_layout.addWidget(self.video_widget)
        left_box.addWidget(self.video_container, stretch=1)

        # Progress / Seek Slider
        seek_box = QHBoxLayout()
        seek_box.setSpacing(10)

        self.time_lbl = QLabel("00:00 / 00:00")
        self.time_lbl.setStyleSheet("color: #C2B6D4; font-size: 12px; font-weight: 600;")
        self.time_lbl.setFixedWidth(90)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        seek_box.addWidget(self.time_lbl)
        seek_box.addWidget(self.seek_slider)
        left_box.addLayout(seek_box)

        # Bottom Controls (Play/Pause, Stop, Volume, Fullscreen)
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(10)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setProperty("class", "PrimaryBtn")
        self.play_btn.clicked.connect(self.toggle_play)
        ctrl_bar.addWidget(self.play_btn)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setProperty("class", "SecondaryBtn")
        self.stop_btn.clicked.connect(self.stop_video)
        ctrl_bar.addWidget(self.stop_btn)

        ctrl_bar.addSpacing(15)

        # Volume Controls
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("color: #DDD; font-size: 14px;")
        ctrl_bar.addWidget(vol_icon)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(85)
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        ctrl_bar.addWidget(self.vol_slider)

        ctrl_bar.addStretch()

        # Fullscreen Button
        self.fs_btn = QPushButton("⛶ Fullscreen")
        self.fs_btn.setProperty("class", "SecondaryBtn")
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        ctrl_bar.addWidget(self.fs_btn)

        left_box.addLayout(ctrl_bar)
        main_layout.addLayout(left_box, stretch=3)

        # Right Column: Episodes Playlist & Source Actions
        right_box = QVBoxLayout()
        right_box.setSpacing(10)

        ep_header = QLabel("📺 Episodes")
        ep_header.setStyleSheet("font-size: 14px; font-weight: 800; color: #FFFFFF;")
        right_box.addWidget(ep_header)

        self.ep_list = QListWidget()
        self.ep_list.setStyleSheet("""
            QListWidget {
                background-color: #171320;
                border: 1px solid #2B2138;
                border-radius: 10px;
                padding: 6px;
                color: #DDD;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 6px;
                margin-bottom: 3px;
            }
            QListWidget::item:hover {
                background-color: #261D33;
                color: #FF7043;
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF3D1F, stop:1 #FF8038);
                color: #FFFFFF;
                font-weight: 700;
            }
        """)
        self.ep_list.itemDoubleClicked.connect(self._on_episode_double_clicked)
        right_box.addWidget(self.ep_list, stretch=1)

        # Source Action Buttons
        open_file_btn = QPushButton("📁 Open Video File (.mp4)")
        open_file_btn.setProperty("class", "SecondaryBtn")
        open_file_btn.clicked.connect(self._open_local_file)
        right_box.addWidget(open_file_btn)

        stream_url_btn = QPushButton("🔗 Play from URL")
        stream_url_btn.setProperty("class", "SecondaryBtn")
        stream_url_btn.clicked.connect(self._stream_online_url)
        right_box.addWidget(stream_url_btn)

        web_btn = QPushButton("🌐 Watch on Hongguo Web")
        web_btn.setProperty("class", "SecondaryBtn")
        web_btn.clicked.connect(self._open_hongguo_web)
        right_box.addWidget(web_btn)

        main_layout.addLayout(right_box, stretch=1)

    def init_connections(self):
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.seek_slider.sliderMoved.connect(self._set_position)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)

    def _scan_local_episodes(self):
        self.ep_list.clear()
        safe_title = sanitize_filename(self.title)

        # Search for potential video locations including subdirectories
        base_dl = os.path.join(get_app_dir(), "Downloaded_Videos")
        candidate_folders = [
            os.path.join(base_dl, safe_title),
            os.path.join(os.environ.get("USERPROFILE", ""), "Videos", "Hongguo"),
            base_dl,
        ]

        # Also search inside all subdirectories of Downloaded_Videos
        if os.path.exists(base_dl):
            for entry in os.listdir(base_dl):
                sub_p = os.path.join(base_dl, entry)
                if os.path.isdir(sub_p):
                    # Check if .series.json matches series_id
                    s_json = os.path.join(sub_p, ".series.json")
                    if os.path.exists(s_json):
                        try:
                            import json
                            with open(s_json, "r", encoding="utf-8") as jf:
                                jdata = json.load(jf)
                                if str(jdata.get("series_id", "")) == self.series_id:
                                    candidate_folders.insert(0, sub_p)
                        except Exception:
                            pass
                    candidate_folders.append(sub_p)

        found_any = False
        seen_paths = set()
        for folder in candidate_folders:
            if os.path.exists(folder):
                for f in sorted(os.listdir(folder)):
                    if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".ts", ".flv")):
                        full_p = os.path.join(folder, f)
                        if full_p not in seen_paths:
                            seen_paths.add(full_p)
                            item = QListWidgetItem(f"▶ {f}")
                            item.setData(Qt.ItemDataRole.UserRole, full_p)
                            self.ep_list.addItem(item)
                            found_any = True

        if not found_any:
            placeholder = QListWidgetItem("No local videos found (Click 'Open Video File')")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.ep_list.addItem(placeholder)
        else:
            # Auto load first episode if no initial video specified
            if not self.initial_video_path and self.ep_list.count() > 0:
                first_item = self.ep_list.item(0)
                path = first_item.data(Qt.ItemDataRole.UserRole)
                if path and os.path.exists(path):
                    self.load_video(path)

    def load_video(self, source_path_or_url: str):
        if source_path_or_url.startswith("http://") or source_path_or_url.startswith("https://"):
            url = QUrl(source_path_or_url)
            self.status_tag.setText("Streaming online...")
        else:
            url = QUrl.fromLocalFile(source_path_or_url)
            filename = os.path.basename(source_path_or_url)
            self.status_tag.setText(f"Playing: {filename}")

        self.media_player.setSource(url)
        self.media_player.play()
        self.play_btn.setText("⏸ Pause")

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setText("▶ Play")
            self.status_tag.setText("Paused")
        else:
            self.media_player.play()
            self.play_btn.setText("⏸ Pause")
            self.status_tag.setText("Playing")

    def stop_video(self):
        self.media_player.stop()
        self.play_btn.setText("▶ Play")
        self.status_tag.setText("Stopped")

    def _on_volume_changed(self, val: int):
        self.audio_output.setVolume(val / 100.0)

    def _on_position_changed(self, position: int):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self._update_time_label(position, self.media_player.duration())

    def _on_duration_changed(self, duration: int):
        self.seek_slider.setRange(0, duration)
        self._update_time_label(self.media_player.position(), duration)

    def _set_position(self, position: int):
        self.media_player.setPosition(position)

    def _update_time_label(self, pos_ms: int, dur_ms: int):
        cur_t = QTime(0, 0, 0).addMSecs(max(0, pos_ms))
        dur_t = QTime(0, 0, 0).addMSecs(max(0, dur_ms))
        format_str = "hh:mm:ss" if dur_ms >= 3600000 else "mm:ss"
        self.time_lbl.setText(f"{cur_t.toString(format_str)} / {dur_t.toString(format_str)}")

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸ Pause")
        else:
            self.play_btn.setText("▶ Play")

    def _on_episode_double_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self.load_video(path)

    def _open_local_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File to Play", "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.ts);;All Files (*)"
        )
        if file_path:
            self.load_video(file_path)
            # Add to playlist if not present
            item = QListWidgetItem(f"▶ {os.path.basename(file_path)}")
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            self.ep_list.addItem(item)

    def _stream_online_url(self):
        url, ok = QInputDialog.getText(
            self, "Play Video from URL", "Enter direct MP4 URL or stream link:"
        )
        if ok and url.strip():
            self.load_video(url.strip())

    def _open_hongguo_web(self):
        # Open Hongguo drama series page online
        web_url = f"https://hongguoduanju.com/series/{self.series_id}"
        webbrowser.open(web_url)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fs_btn.setText("⛶ Fullscreen")
        else:
            self.showFullScreen()
            self.fs_btn.setText("✕ Exit Fullscreen")

    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)
