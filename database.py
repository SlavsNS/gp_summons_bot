import sqlite3
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from config import DB_PATH

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tracked persons table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    full_name TEXT NOT NULL,
                    surname TEXT NOT NULL,
                    stem TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                    UNIQUE (user_id, full_name)
                )
            """)

            # Seen posts from gp.gov.ua
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_posts (
                    post_url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    date_published TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # History of sent notifications to avoid duplicates
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications_sent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    person_id INTEGER NOT NULL,
                    post_url TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, person_id, post_url)
                )
            """)
            conn.commit()

    # --- Async methods ---

    async def add_or_update_user(self, user_id: int, username: Optional[str], first_name: Optional[str]):
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (user_id, username, first_name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username=excluded.username,
                        first_name=excluded.first_name,
                        is_active=1
                """, (user_id, username, first_name))
                conn.commit()
        await asyncio.to_thread(_sync)

    async def add_tracked_person(self, user_id: int, full_name: str, surname: str, stem: str) -> Optional[int]:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO tracked_persons (user_id, full_name, surname, stem)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, full_name.strip(), surname.strip(), stem.strip()))
                    conn.commit()
                    return cursor.lastrowid
                except sqlite3.IntegrityError:
                    return None
        return await asyncio.to_thread(_sync)

    async def remove_tracked_person(self, user_id: int, person_id: int) -> bool:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM tracked_persons
                    WHERE id = ? AND user_id = ?
                """, (person_id, user_id))
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_sync)

    async def get_user_tracked_persons(self, user_id: int) -> List[Dict[str, Any]]:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, user_id, full_name, surname, stem, created_at
                    FROM tracked_persons
                    WHERE user_id = ?
                    ORDER BY id ASC
                """, (user_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        return await asyncio.to_thread(_sync)

    async def get_all_active_tracked_persons(self) -> List[Dict[str, Any]]:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT tp.id, tp.user_id, tp.full_name, tp.surname, tp.stem, u.first_name, u.username
                    FROM tracked_persons tp
                    JOIN users u ON tp.user_id = u.user_id
                    WHERE u.is_active = 1
                    ORDER BY tp.id ASC
                """)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        return await asyncio.to_thread(_sync)

    async def has_notification_been_sent(self, user_id: int, person_id: int, post_url: str) -> bool:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM notifications_sent
                    WHERE user_id = ? AND person_id = ? AND post_url = ?
                """, (user_id, person_id, post_url))
                return cursor.fetchone() is not None
        return await asyncio.to_thread(_sync)

    async def record_notification_sent(self, user_id: int, person_id: int, post_url: str):
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO notifications_sent (user_id, person_id, post_url)
                    VALUES (?, ?, ?)
                """, (user_id, person_id, post_url))
                conn.commit()
        await asyncio.to_thread(_sync)

    async def record_seen_post(self, post_url: str, title: str, date_published: Optional[str]):
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO seen_posts (post_url, title, date_published)
                    VALUES (?, ?, ?)
                """, (post_url, title, date_published))
                conn.commit()
        await asyncio.to_thread(_sync)

    async def get_stats(self) -> Dict[str, int]:
        def _sync():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
                active_users = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM tracked_persons")
                tracked_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM notifications_sent")
                notifications_count = cursor.fetchone()[0]
                return {
                    "active_users": active_users,
                    "tracked_persons": tracked_count,
                    "notifications_sent": notifications_count
                }
        return await asyncio.to_thread(_sync)

# Global database instance
db = Database()
