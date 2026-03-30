import sqlite3
from datetime import datetime
from typing import List, Dict, Any

class Database:
    def __init__(self, db_path: str = "chat_history.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE,
                    first_name TEXT,
                    last_name TEXT,
                    phone TEXT,
                    photo_url TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    chat_id TEXT,
                    sender_id INTEGER,
                    text TEXT,
                    media_path TEXT,
                    media_type TEXT,
                    timestamp TEXT,
                    is_outgoing INTEGER
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    last_message TEXT,
                    last_message_time TEXT,
                    unread_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def save_user(self, user_id: int, username: str, first_name: str, last_name: str = "", phone: str = "", photo_url: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users (id, username, first_name, last_name, phone, photo_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, first_name, last_name, phone, photo_url))
            conn.commit()

    def save_message(self, chat_id: str, message_id: int, sender_id: int, text: str,
                     media_path: str = "", media_type: str = "", is_outgoing: int = 0):
        timestamp = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO messages (id, chat_id, sender_id, text, media_path, media_type, timestamp, is_outgoing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, chat_id, sender_id, text, media_path, media_type, timestamp, is_outgoing))
            conn.commit()
            self.update_chat_last_message(chat_id, text, timestamp)

    def get_chat_history(self, chat_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.*, u.username, u.first_name, u.last_name, u.photo_url
                FROM messages m
                LEFT JOIN users u ON m.sender_id = u.id
                WHERE m.chat_id = ?
                ORDER BY m.timestamp ASC
                LIMIT ?
            """, (chat_id, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_chat_last_message(self, chat_id: str, last_message: str, timestamp: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO chats (id, last_message, last_message_time)
                VALUES (?, ?, ?)
            """, (chat_id, last_message[:100], timestamp))
            conn.commit()

    def increment_unread_count(self, chat_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE chats SET unread_count = unread_count + 1 WHERE id = ?", (chat_id,))
            conn.commit()

    def reset_unread_count(self, chat_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE chats SET unread_count = 0 WHERE id = ?", (chat_id,))
            conn.commit()

    def get_unread_count(self, chat_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT unread_count FROM chats WHERE id = ?", (chat_id,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def close(self):
        pass