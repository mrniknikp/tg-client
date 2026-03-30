import sqlite3
import os
from datetime import datetime

class Database:
    def __init__(self, db_name="telegram_app.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        c = conn.cursor()
        
        # Таблица пользователей (аккаунтов)
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_id INTEGER NOT NULL,
                api_hash TEXT NOT NULL,
                phone TEXT NOT NULL,
                session_string TEXT,
                user_id_telegram INTEGER,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица настроек (текущий пользователь)
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Таблица чатов (метаданные)
        c.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY,
                user_account_id INTEGER,
                title TEXT,
                username TEXT,
                photo_path TEXT,
                last_message_date INTEGER,
                FOREIGN KEY(user_account_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(id, user_account_id)
            )
        ''')

        # Таблица сообщений
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                message_id_telegram INTEGER,
                sender_id INTEGER,
                text TEXT,
                media_path TEXT,
                media_type TEXT,
                is_outgoing INTEGER,
                date INTEGER,
                user_account_id INTEGER,
                FOREIGN KEY(chat_id, user_account_id) REFERENCES chats(id, user_account_id) ON DELETE CASCADE,
                UNIQUE(message_id_telegram, user_account_id)
            )
        ''')
        
        # Индексы для ускорения
        c.execute('CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id, user_account_id, date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_chat_user ON chats(user_account_id)')

        conn.commit()
        conn.close()

    # --- Управление пользователями ---
    def add_user(self, api_id, api_hash, phone, session_string=None, tg_user_id=None, username=None, first_name=None, last_name=None):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (api_id, api_hash, phone, session_string, user_id_telegram, username, first_name, last_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (api_id, api_hash, phone, session_string, tg_user_id, username, first_name, last_name))
        user_id = c.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def get_all_users(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM users')
        users = [dict(row) for row in c.fetchall()]
        conn.close()
        return users

    def get_user(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_user_session(self, user_id, session_string, tg_user_id=None, username=None, first_name=None, last_name=None):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            UPDATE users 
            SET session_string = ?, user_id_telegram = ?, username = ?, first_name = ?, last_name = ?
            WHERE id = ?
        ''', (session_string, tg_user_id, username, first_name, last_name, user_id))
        conn.commit()
        conn.close()

    def set_current_user(self, user_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('current_user_id', str(user_id)))
        conn.commit()
        conn.close()

    def get_current_user_id(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = ?', ('current_user_id',))
        row = c.fetchone()
        conn.close()
        return int(row['value']) if row else None

    # --- Чаты и Сообщения (с учетом user_account_id) ---
    def save_chat_meta(self, chat_id, user_account_id, title, username=None, photo_path=None):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO chats (id, user_account_id, title, username, photo_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, user_account_id, title, username, photo_path))
        conn.commit()
        conn.close()

    def get_chats(self, user_account_id, limit=50):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT * FROM chats 
            WHERE user_account_id = ? 
            ORDER BY last_message_date DESC 
            LIMIT ?
        ''', (user_account_id, limit))
        chats = [dict(row) for row in c.fetchall()]
        conn.close()
        return chats

    def save_message(self, chat_id, message_id, sender_id, text, media_path, media_type, is_outgoing, date, user_account_id):
        conn = self.get_connection()
        c = conn.cursor()
        # Проверка на дубликат перед вставкой
        c.execute('SELECT id FROM messages WHERE message_id_telegram = ? AND user_account_id = ?', (message_id, user_account_id))
        if c.fetchone():
            conn.close()
            return
        
        c.execute('''
            INSERT INTO messages (chat_id, message_id_telegram, sender_id, text, media_path, media_type, is_outgoing, date, user_account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, message_id, sender_id, text, media_path, media_type, is_outgoing, date, user_account_id))
        conn.commit()
        conn.close()

    def get_messages(self, chat_id, user_account_id, limit=100, offset_date=0):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT * FROM messages 
            WHERE chat_id = ? AND user_account_id = ? AND date > ?
            ORDER BY date ASC 
            LIMIT ?
        ''', (chat_id, user_account_id, offset_date, limit))
        messages = [dict(row) for row in c.fetchall()]
        conn.close()
        return messages
    
    def get_last_message_date(self, chat_id, user_account_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT MAX(date) FROM messages 
            WHERE chat_id = ? AND user_account_id = ?
        ''', (chat_id, user_account_id))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] else 0