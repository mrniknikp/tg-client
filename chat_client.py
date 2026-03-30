import sys
import asyncio
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QTextEdit, QLineEdit,
                             QPushButton, QSplitter, QMessageBox, QInputDialog,
                             QFileDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QTextCursor
from plyer import notification
from database import Database
from telegram_client import TelegramClientWrapper
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramThread(QThread):
    message_received = pyqtSignal(dict)
    login_success = pyqtSignal()
    login_error = pyqtSignal(str)
    dialogs_ready = pyqtSignal(list)
    need_code = pyqtSignal()
    need_password = pyqtSignal()

    def __init__(self, api_id, api_hash, phone):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = TelegramClientWrapper(api_id, api_hash)
        self.loop = None
        self.code = None
        self.password = None
        self.code_event = asyncio.Event()
        self.password_event = asyncio.Event()
        self._stop_requested = False

    def set_code(self, code):
        self.code = code
        self.code_event.set()

    def set_password(self, password):
        self.password = password
        self.password_event.set()

    def reset_code_event(self):
        self.code_event.clear()
        self.code = None

    def reset_password_event(self):
        self.password_event.clear()
        self.password = None

    async def get_code_async(self):
        await self.code_event.wait()
        return self.code

    async def get_password_async(self):
        await self.password_event.wait()
        return self.password

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        try:
            while True:
                try:
                    await self.client.start(
                        self.phone,
                        self.get_code_async,
                        self.get_password_async
                    )
                    break  # Успешный вход
                except Exception as e:
                    err = str(e)
                    if err == "CODE_INVALID":
                        self.need_code.emit()
                        self.reset_code_event()
                        continue
                    elif err == "PASSWORD_INVALID":
                        self.need_password.emit()
                        self.reset_password_event()
                        continue
                    elif err == "PASSWORD_REQUIRED":
                        self.need_password.emit()
                        continue
                    else:
                        raise e
            self.client.message_callback = self.on_message
            self.loop = asyncio.get_running_loop()
            self.login_success.emit()
            asyncio.create_task(self._refresh_dialogs_periodically())
            await self.client.client.run_until_disconnected()
        except Exception as e:
            self.login_error.emit(str(e))

    async def _refresh_dialogs_periodically(self):
        while not self._stop_requested:
            try:
                dialogs = await self.client.get_dialogs()
                self.dialogs_ready.emit(dialogs)
            except Exception as e:
                logger.error(f"Error fetching dialogs: {e}")
            await asyncio.sleep(5)

    async def on_message(self, message):
        self.message_received.emit(message)

    def send_message(self, chat_id, text, file_path=None):
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(
                self.client.send_message(chat_id, text, file_path),
                self.loop
            )

    def request_dialogs_now(self):
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(
                self._refresh_dialogs_once(),
                self.loop
            )

    async def _refresh_dialogs_once(self):
        dialogs = await self.client.get_dialogs()
        self.dialogs_ready.emit(dialogs)

    def disconnect(self):
        self._stop_requested = True
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)

    def stop(self):
        self._stop_requested = True
        self.disconnect()

class ChatApp(QMainWindow):
    def __init__(self, api_id, api_hash):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.db = Database()
        self.telegram_thread = None
        self.current_chat_id = None
        self.dialogs_cache = {}
        self.init_ui()
        self.start_login()

    def init_ui(self):
        self.setWindowTitle("Telegram Messenger (via Proxy)")
        self.setGeometry(100, 100, 1000, 700)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self.on_chat_selected)
        splitter.addWidget(self.chat_list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        self.messages_area.setFont(QFont("Arial", 10))
        right_layout.addWidget(self.messages_area)
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message...")
        self.message_input.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.attach_button = QPushButton("📎")
        self.attach_button.clicked.connect(self.attach_file)
        input_layout.addWidget(self.attach_button)
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        right_layout.addLayout(input_layout)
        splitter.setSizes([300, 700])
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_chat_list)
        self.refresh_timer.start(5000)

    def start_login(self):
        phone, ok = QInputDialog.getText(self, "Login", "Enter phone number (e.g., +71234567890):")
        if not ok or not phone:
            sys.exit(0)
        self.telegram_thread = TelegramThread(self.api_id, self.api_hash, phone)
        self.telegram_thread.login_success.connect(self.on_login_success)
        self.telegram_thread.login_error.connect(self.on_login_error)
        self.telegram_thread.message_received.connect(self.on_message_received)
        self.telegram_thread.dialogs_ready.connect(self.on_dialogs_received)
        self.telegram_thread.need_code.connect(self.on_need_code)
        self.telegram_thread.need_password.connect(self.on_need_password)
        self.telegram_thread.start()
        self.request_code()

    def request_code(self):
        code, ok = QInputDialog.getText(self, "Verification Code", "Enter code from Telegram:")
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_code(code)

    def on_need_code(self):
        QMessageBox.warning(self, "Invalid Code", "The code you entered is incorrect. Please try again.")
        self.request_code()

    def request_password(self):
        pwd, ok = QInputDialog.getText(self, "2FA Password", "Enter your two-factor password:", QLineEdit.Password)
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_password(pwd)

    def on_need_password(self):
        QMessageBox.warning(self, "Invalid Password", "The two-factor password is incorrect. Please try again.")
        self.request_password()

    def on_login_success(self):
        QMessageBox.information(self, "Success", "Logged in successfully!")
        self.telegram_thread.request_dialogs_now()

    def on_login_error(self, error_msg):
        reply = QMessageBox.critical(self, "Error", f"Login failed: {error_msg}\n\nRetry?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.telegram_thread:
                self.telegram_thread.quit()
                self.telegram_thread.wait()
            self.start_login()
        else:
            sys.exit(1)

    def on_dialogs_received(self, dialogs):
        self.chat_list.clear()
        self.dialogs_cache.clear()
        for dialog in dialogs:
            chat_id = str(dialog['id'])
            self.dialogs_cache[chat_id] = dialog
            unread = self.db.get_unread_count(chat_id)
            text = dialog['name']
            if unread > 0:
                text += f" ✉️ {unread}"
            self.chat_list.addItem(text)
            self.chat_list.item(self.chat_list.count() - 1).setData(Qt.UserRole, chat_id)

    def refresh_chat_list(self):
        if self.telegram_thread and self.telegram_thread.isRunning():
            self.telegram_thread.request_dialogs_now()

    def on_message_received(self, msg):
        self.db.save_message(
            chat_id=msg['chat_id'],
            message_id=msg['id'],
            sender_id=msg['sender_id'],
            text=msg['text'],
            media_path=msg.get('media_path', ''),
            media_type=msg.get('media_type', ''),
            is_outgoing=0
        )
        self.db.save_user(
            user_id=msg['sender_id'],
            username=msg.get('sender_username', ''),
            first_name=msg.get('sender_name', '')
        )
        if self.current_chat_id != msg['chat_id']:
            self.db.increment_unread_count(msg['chat_id'])
        self.show_notification(msg)
        if self.current_chat_id == msg['chat_id']:
            self.display_message(msg)
        self.refresh_chat_list()

    def show_notification(self, msg):
        try:
            notification.notify(
                title=f"New message from {msg['sender_name']}",
                message=msg['text'][:100] if msg['text'] else "Media file",
                app_name="Telegram Messenger",
                timeout=5
            )
        except Exception as e:
            logger.error(f"Notification error: {e}")

    def on_chat_selected(self, item):
        chat_id = item.data(Qt.UserRole)
        if chat_id:
            self.current_chat_id = chat_id
            self.load_chat_history(chat_id)
            self.db.reset_unread_count(chat_id)
            self.refresh_chat_list()

    def load_chat_history(self, chat_id):
        self.messages_area.clear()
        for msg in self.db.get_chat_history(chat_id):
            self.display_message(msg)

    def display_message(self, msg):
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        color = "blue" if msg.get('is_outgoing') else "green"
        sender = msg.get('first_name', msg.get('sender_name', 'Unknown'))
        html = f"""
        <div style="margin:10px; padding:8px; border-radius:8px; background:#f0f0f0;">
            <b style="color:{color};">{sender}:</b><br/>
            <span>{msg.get('text', '')}</span>
        """
        if msg.get('media_path') and os.path.exists(msg['media_path']):
            html += f'<br/><a href="file://{msg["media_path"]}">📎 Open file</a>'
        html += "</div>"
        self.messages_area.insertHtml(html)
        self.messages_area.ensureCursorVisible()

    def send_message(self):
        if not self.current_chat_id:
            QMessageBox.warning(self, "Warning", "Select a chat first")
            return
        text = self.message_input.text().strip()
        if not text:
            return
        self.telegram_thread.send_message(int(self.current_chat_id), text)
        import time
        self.db.save_message(
            chat_id=self.current_chat_id,
            message_id=int(time.time()),
            sender_id=0,
            text=text,
            is_outgoing=1
        )
        self.display_message({'text': text, 'sender_name': 'You', 'is_outgoing': True})
        self.message_input.clear()

    def attach_file(self):
        if not self.current_chat_id:
            QMessageBox.warning(self, "Warning", "Select a chat first")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            self.telegram_thread.send_message(int(self.current_chat_id), "", path)

    def closeEvent(self, event):
        if self.telegram_thread:
            self.telegram_thread.stop()
            self.telegram_thread.quit()
            self.telegram_thread.wait()
        self.db.close()
        event.accept()