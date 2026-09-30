"""
SQLite Database module for saving Hongguo dramas locally.
Handles bookmarking, categorizing, user notes, and exports.
Guaranteed to be writable across all Windows environments (Program Files, AppData, Portable).
"""

import sqlite3
import json
import csv
import os
import sys
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional


def get_default_db_path() -> str:
    """
    Determine a guaranteed writable path for hongguo_saved.db:
    1. If AppData database exists, use it.
    2. Try local app directory (portable mode) if it has write permissions.
    3. Fallback to %APPDATA%/HongguoDownloader/hongguo_saved.db.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        appdata_dir = os.path.join(appdata, "HongguoDownloader")
    else:
        appdata_dir = os.path.join(os.path.expanduser("~"), ".config", "HongguoDownloader")

    appdata_db = os.path.join(appdata_dir, "hongguo_saved.db")

    # If already exists in AppData, use it directly
    if os.path.exists(appdata_db):
        return appdata_db

    # Check local application folder (portable / USB mode)
    try:
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        local_db = os.path.join(base_dir, "hongguo_saved.db")

        # Test if base_dir is writable
        test_file = os.path.join(base_dir, f".write_test_{os.getpid()}")
        try:
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            # Local dir is writable!
            return local_db
        except Exception:
            # Local dir is read-only (e.g. standard user in C:\Program Files\)
            pass
    except Exception:
        pass

    # Ensure AppData directory exists
    try:
        os.makedirs(appdata_dir, exist_ok=True)
    except Exception:
        pass

    return appdata_db


DB_FILE = get_default_db_path()


class DramaDatabase:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_default_db_path()
        # Ensure parent folder exists
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        except Exception:
            pass
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError:
            # Fallback to user temp directory if path is restricted
            fallback_dir = os.path.join(tempfile.gettempdir(), "HongguoDownloader")
            os.makedirs(fallback_dir, exist_ok=True)
            self.db_path = os.path.join(fallback_dir, "hongguo_saved.db")
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_dramas (
                    series_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    cover TEXT,
                    episode_cnt TEXT,
                    score TEXT,
                    heat TEXT,
                    status TEXT,
                    user_tag TEXT DEFAULT 'Plan to Watch',
                    notes TEXT DEFAULT '',
                    user_rating INTEGER DEFAULT 5,
                    saved_at TEXT,
                    downloaded_poster TEXT DEFAULT ''
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def save_drama(
        self,
        series_id: str,
        title: str,
        cover: str = "",
        episode_cnt: str = "",
        score: str = "",
        heat: str = "",
        status: str = "",
        user_tag: str = "Plan to Watch",
        notes: str = "",
        user_rating: int = 5,
        downloaded_poster: str = ""
    ) -> bool:
        """
        Save or update drama in the local database.
        """
        if not series_id or not title:
            return False

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                INSERT INTO saved_dramas (
                    series_id, title, cover, episode_cnt, score, heat,
                    status, user_tag, notes, user_rating, saved_at, downloaded_poster
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id) DO UPDATE SET
                    title=excluded.title,
                    cover=COALESCE(NULLIF(excluded.cover, ''), saved_dramas.cover),
                    episode_cnt=COALESCE(NULLIF(excluded.episode_cnt, ''), saved_dramas.episode_cnt),
                    score=COALESCE(NULLIF(excluded.score, ''), saved_dramas.score),
                    heat=COALESCE(NULLIF(excluded.heat, ''), saved_dramas.heat),
                    status=COALESCE(NULLIF(excluded.status, ''), saved_dramas.status),
                    user_tag=excluded.user_tag,
                    notes=excluded.notes,
                    user_rating=excluded.user_rating,
                    downloaded_poster=COALESCE(NULLIF(excluded.downloaded_poster, ''), saved_dramas.downloaded_poster)
            """, (
                str(series_id), title, cover, str(episode_cnt), str(score),
                str(heat), status, user_tag, notes, user_rating, saved_at, downloaded_poster
            ))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def remove_drama(self, series_id: str) -> bool:
        """Remove a drama from the saved list."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM saved_dramas WHERE series_id = ?", (str(series_id),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def is_saved(self, series_id: str) -> bool:
        """Check if a drama is in the database."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM saved_dramas WHERE series_id = ?", (str(series_id),))
            return cursor.fetchone() is not None
        except Exception:
            return False
        finally:
            conn.close()

    def get_all_saved(self, tag_filter: str = "All", sort_by: str = "saved_at DESC", search_q: str = "") -> List[Dict[str, Any]]:
        """Fetch saved dramas with optional tag filter, search filter, and sorting."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            allowed_sorts = {
                "saved_at DESC": "saved_at DESC",
                "saved_at ASC": "saved_at ASC",
                "title ASC": "title ASC",
                "user_rating DESC": "user_rating DESC",
                "score DESC": "CAST(score AS FLOAT) DESC",
            }
            order_clause = allowed_sorts.get(sort_by, "saved_at DESC")

            conditions = []
            params = []

            if tag_filter and tag_filter not in ("All", "ទាំងអស់ (All)"):
                conditions.append("(user_tag = ? OR user_tag LIKE ?)")
                params.extend([tag_filter, f"%{tag_filter}%"])

            if search_q and search_q.strip():
                conditions.append("(title LIKE ? OR series_id LIKE ? OR notes LIKE ?)")
                q_wildcard = f"%{search_q.strip()}%"
                params.extend([q_wildcard, q_wildcard, q_wildcard])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"SELECT * FROM saved_dramas {where_clause} ORDER BY {order_clause}"
            cursor.execute(query, params)

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def get_total_count(self) -> int:
        """Return total number of saved dramas."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM saved_dramas")
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def get_drama(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get single drama detail by series_id."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM saved_dramas WHERE series_id = ?", (str(series_id),))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def update_poster_path(self, series_id: str, poster_path: str) -> bool:
        """Update downloaded local poster file path."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE saved_dramas SET downloaded_poster = ? WHERE series_id = ?",
                (poster_path, str(series_id))
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def export_to_csv(self, filepath: str) -> bool:
        """Export all saved dramas to CSV."""
        items = self.get_all_saved()
        if not items:
            return False
        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(items[0].keys()))
                writer.writeheader()
                writer.writerows(items)
            return True
        except Exception:
            return False

    def export_to_json(self, filepath: str) -> bool:
        """Export all saved dramas to JSON."""
        items = self.get_all_saved()
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
