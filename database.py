import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

class Database:
    def __init__(self, db_path: str = "chat_history.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Таблица аккаунтов Telegram
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telegram_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT UNIQUE NOT NULL,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    session_name TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT,
                    is_active INTEGER DEFAULT 0
                )
            """)
            # Таблица пользователей (контакты)
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
                    account_id INTEGER,
                    chat_id TEXT,
                    sender_id INTEGER,
                    text TEXT,
                    media_path TEXT,
                    media_type TEXT,
                    timestamp TEXT,
                    is_outgoing INTEGER,
                    FOREIGN KEY (account_id) REFERENCES telegram_accounts(id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    account_id INTEGER,
                    title TEXT,
                    last_message TEXT,
                    last_message_time TEXT,
                    unread_count INTEGER DEFAULT 0,
                    FOREIGN KEY (account_id) REFERENCES telegram_accounts(id)
                )
            """)
            conn.commit()

    # === Методы для управления аккаунтами ===
    
    def create_account(self, account_name: str, api_id: int, api_hash: str, phone: str, session_name: str) -> int:
        """Создать новый аккаунт"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO telegram_accounts (account_name, api_id, api_hash, phone, session_name, is_active)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (account_name, api_id, api_hash, phone, session_name))
            conn.commit()
            return cursor.lastrowid

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Получить все аккаунты"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_accounts ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Получить активный аккаунт"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_accounts WHERE is_active = 1 LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_active_account(self, account_id: int):
        """Установить аккаунт как активный"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE telegram_accounts SET is_active = 0")
            cursor.execute("UPDATE telegram_accounts SET is_active = 1, last_used_at = ? WHERE id = ?", 
                          (datetime.now().isoformat(), account_id))
            conn.commit()

    def delete_account(self, account_id: int):
        """Удалить аккаунт"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telegram_accounts WHERE id = ?", (account_id,))
            conn.commit()

    def get_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        """Получить аккаунт по ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_accounts WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def has_accounts(self) -> bool:
        """Проверить, есть ли хоть один аккаунт"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM telegram_accounts")
            return cursor.fetchone()[0] > 0

    # === Методы для работы с пользователями ===

    def save_user(self, user_id: int, username: str, first_name: str, last_name: str = "", phone: str = "", photo_url: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users (id, username, first_name, last_name, phone, photo_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, first_name, last_name, phone, photo_url))
            conn.commit()

    def save_message(self, chat_id: str, message_id: int, sender_id: int, text: str,
                     media_path: str = "", media_type: str = "", is_outgoing: int = 0, account_id: int = None):
        timestamp = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO messages (id, account_id, chat_id, sender_id, text, media_path, media_type, timestamp, is_outgoing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, account_id, chat_id, sender_id, text, media_path, media_type, timestamp, is_outgoing))
            conn.commit()
            self.update_chat_last_message(chat_id, text, timestamp, account_id)

    def get_chat_history(self, chat_id: str, limit: int = 100, account_id: int = None) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if account_id is not None:
                cursor.execute("""
                    SELECT m.*, u.username, u.first_name, u.last_name, u.photo_url
                    FROM messages m
                    LEFT JOIN users u ON m.sender_id = u.id
                    WHERE m.chat_id = ? AND (m.account_id = ? OR m.account_id IS NULL)
                    ORDER BY m.timestamp ASC
                    LIMIT ?
                """, (chat_id, account_id, limit))
            else:
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

    def update_chat_last_message(self, chat_id: str, last_message: str, timestamp: str, account_id: int = None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if account_id is not None:
                cursor.execute("""
                    INSERT OR REPLACE INTO chats (id, account_id, last_message, last_message_time)
                    VALUES (?, ?, ?, ?)
                """, (chat_id, account_id, last_message[:100], timestamp))
            else:
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