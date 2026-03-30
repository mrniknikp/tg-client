import sys
import asyncio
import os
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QLineEdit,
                             QPushButton, QSplitter, QMessageBox, QInputDialog,
                             QFileDialog, QLabel, QListWidgetItem, QFrame, 
                             QScrollArea)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QFont
from plyer import notification
from database import Database
from telegram_client import TelegramClientWrapper
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatListItem(QWidget):
    def __init__(self, name, last_message, unread_count, timestamp=""):
        super().__init__()
        self.setFixedHeight(80)
        self.setup_ui(name, last_message, unread_count, timestamp)
        
    def setup_ui(self, name, last_message, unread_count, timestamp):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        avatar_label = QLabel(name[0].upper() if name else "?")
        avatar_label.setFixedSize(48, 48)
        avatar_label.setAlignment(Qt.AlignCenter)
        avatar_label.setStyleSheet("QLabel { background-color: #3390ec; color: white; border-radius: 24px; font-size: 20px; font-weight: bold; }")
        layout.addWidget(avatar_label)
        
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        
        header_layout = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #222222;")
        header_layout.addWidget(name_label)
        header_layout.addStretch()
        if timestamp:
            time_label = QLabel(timestamp)
            time_label.setStyleSheet("font-size: 12px; color: #999999;")
            header_layout.addWidget(time_label)
        text_layout.addLayout(header_layout)
        
        msg_label = QLabel(last_message[:60] + "..." if len(last_message) > 60 else last_message)
        msg_label.setStyleSheet("font-size: 13px; color: #888888;")
        text_layout.addWidget(msg_label)
        text_layout.addStretch()
        layout.addWidget(text_container, 1)
        
        if unread_count > 0:
            unread_badge = QLabel(str(unread_count))
            unread_badge.setFixedSize(22, 22)
            unread_badge.setAlignment(Qt.AlignCenter)
            unread_badge.setStyleSheet("QLabel { background-color: #3390ec; color: white; border-radius: 11px; font-size: 12px; font-weight: bold; }")
            layout.addWidget(unread_badge)
        
        self.setStyleSheet("ChatListItem { background-color: white; border-bottom: 1px solid #f0f0f0; } ChatListItem:hover { background-color: #f5f5f5; }")


class MessageBubble(QFrame):
    def __init__(self, text, sender_name, is_outgoing, timestamp):
        super().__init__()
        self.is_outgoing = is_outgoing
        self.setup_ui(text, sender_name, timestamp)
        
    def setup_ui(self, text, sender_name, timestamp):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        if not self.is_outgoing and sender_name:
            name_label = QLabel(sender_name)
            name_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #3390ec; padding-left: 8px;")
            layout.addWidget(name_label)
        
        bubble = QFrame()
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)
        
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_label.setStyleSheet("font-size: 14px; color: #000000; line-height: 1.4;")
        bubble_layout.addWidget(text_label)
        
        if timestamp:
            time_str = timestamp.split(" ")[1][:5] if " " in timestamp else timestamp
            time_label = QLabel(time_str)
            time_label.setAlignment(Qt.AlignRight)
            color = "#ffffff" if self.is_outgoing else "#999999"
            time_label.setStyleSheet("font-size: 11px; color: " + color + "; margin-top: 4px;")
            bubble_layout.addWidget(time_label)
        
        if self.is_outgoing:
            bubble.setStyleSheet("QFrame { background-color: #eeffde; border-radius: 16px; border-top-right-radius: 4px; }")
        else:
            bubble.setStyleSheet("QFrame { background-color: #ffffff; border-radius: 16px; border-top-left-radius: 4px; border: 1px solid #e8e8e8; }")
        
        layout.addWidget(bubble)


class MessageScrollArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background-color: #f5f5f5; } QScrollBar:vertical { background-color: transparent; width: 8px; border-radius: 4px; } QScrollBar::handle:vertical { background-color: #d0d0d0; border-radius: 4px; min-height: 20px; } QScrollBar::handle:vertical:hover { background-color: #b0b0b0; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }")
        
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(16, 16, 16, 16)
        self.container_layout.setSpacing(8)
        self.container_layout.addStretch()
        self.setWidget(self.container)
        
    def add_message(self, text, sender_name, is_outgoing, timestamp):
        bubble = MessageBubble(text, sender_name, is_outgoing, timestamp)
        self.container_layout.insertWidget(self.container_layout.count() - 1, bubble)
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def clear_messages(self):
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


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
        self.db = Database()  # Добавляем доступ к БД
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

    async def get_code_async(self):
        self.code_event.clear()
        self.need_code.emit()
        await self.code_event.wait()
        return self.code

    async def get_password_async(self):
        self.password_event.clear()
        self.need_password.emit()
        await self.password_event.wait()
        return self.password

    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        try:
            while True:
                try:
                    await self.client.start(self.phone, self.get_code_async, self.get_password_async)
                    break
                except Exception as e:
                    err = str(e)
                    if err == "CODE_INVALID":
                        self.code_event.clear()
                        self.code = None
                        continue
                    elif err == "PASSWORD_INVALID":
                        self.password_event.clear()
                        self.password = None
                        continue
                    elif err in ("PASSWORD_REQUIRED",):
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
        last_dialogs = None
        consecutive_flood_waits = 0
        while not self._stop_requested:
            try:
                dialogs = await self.client.get_dialogs(limit=50)
                consecutive_flood_waits = 0
                if dialogs != last_dialogs:
                    self.dialogs_ready.emit(dialogs)
                    last_dialogs = dialogs
            except Exception as e:
                err_str = str(e)
                if "flood wait" in err_str.lower():
                    consecutive_flood_waits += 1
                    logger.warning("Flood wait (count: %d): %s", consecutive_flood_waits, e)
                    wait_time = min(5 * consecutive_flood_waits, 60)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("Error fetching dialogs: %s", e)
                    await asyncio.sleep(2)
            await asyncio.sleep(0.5)

    async def on_message(self, message):
        """Обработчик входящих сообщений - сохраняет в БД и отправляет в GUI"""
        try:
            chat_id = str(message.get('chat_id', 0))
            
            # Сохраняем сообщение в базу данных
            self.db.save_message(
                chat_id=chat_id,
                message_id=message.get('id', 0),
                sender_id=message.get('sender_id', 0),
                text=message.get('text', ''),
                media_path=message.get('media_path', ''),
                media_type=message.get('media_type', ''),
                is_outgoing=1 if message.get('is_outgoing', False) else 0
            )
            
            # Обновляем информацию о чате
            timestamp = datetime.now().isoformat()
            self.db.update_chat_last_message(
                chat_id, 
                message.get('text', '')[:100] or '[Медиа]', 
                timestamp
            )
            
            # Увеличиваем счётчик непрочитанных если это не текущий чат
            if not message.get('is_outgoing', False) and self.current_chat_id != chat_id:
                self.db.increment_unread_count(chat_id)
            
            # Отправляем в GUI для отображения
            self.message_received.emit(message)
            
        except Exception as e:
            logger.error(f"Error in on_message handler: {e}")

    def send_message(self, chat_id, text, file_path=None):
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(self.client.send_message(chat_id, text, file_path), self.loop)

    def request_dialogs_now(self):
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(self._refresh_dialogs_once(), self.loop)

    async def _refresh_dialogs_once(self):
        dialogs = await self.client.get_dialogs()
        self.dialogs_ready.emit(dialogs)

    def stop(self):
        self._stop_requested = True
        if self.loop and self.client.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)


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
        QTimer.singleShot(100, self.start_login)

    def init_ui(self):
        self.setWindowTitle("Telegram Messenger")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        self.setStyleSheet("QMainWindow { background-color: #ffffff; }")
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        main_layout.addWidget(splitter)
        
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)
        
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([400, 1000])

    def create_left_panel(self):
        widget = QWidget()
        widget.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QWidget()
        header.setStyleSheet("QWidget { background-color: #ffffff; border-bottom: 1px solid #e8e8e8; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        title_label = QLabel("Chats")
        title_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #222222;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addWidget(header)
        
        search_container = QWidget()
        search_container.setStyleSheet("QWidget { background-color: #f5f5f5; margin: 12px 16px; border-radius: 12px; }")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(16, 10, 16, 10)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search chats...")
        self.search_input.setStyleSheet("QLineEdit { border: none; background-color: transparent; font-size: 14px; color: #333333; } QLineEdit:focus { outline: none; }")
        search_layout.addWidget(self.search_input)
        layout.addWidget(search_container)
        
        self.chat_list = QListWidget()
        self.chat_list.setStyleSheet("QListWidget { border: none; background-color: #ffffff; outline: none; } QListWidget::item { padding: 0px; border-bottom: 1px solid #f0f0f0; } QListWidget::item:selected { background-color: #e3f2fd; } QListWidget::item:hover { background-color: #f5f5f5; }")
        self.chat_list.itemClicked.connect(self.on_chat_selected)
        layout.addWidget(self.chat_list)
        return widget

    def create_right_panel(self):
        widget = QWidget()
        widget.setStyleSheet("background-color: #f0f2f5;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        chat_header = QWidget()
        chat_header.setStyleSheet("QWidget { background-color: #ffffff; border-bottom: 1px solid #e8e8e8; }")
        header_layout = QHBoxLayout(chat_header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        
        self.chat_avatar = QLabel("")
        self.chat_avatar.setFixedSize(42, 42)
        self.chat_avatar.setAlignment(Qt.AlignCenter)
        self.chat_avatar.setStyleSheet("QLabel { background-color: #3390ec; color: white; border-radius: 21px; font-size: 18px; font-weight: bold; }")
        header_layout.addWidget(self.chat_avatar)
        
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        self.chat_title_label = QLabel("Select a chat")
        self.chat_title_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #222222;")
        info_layout.addWidget(self.chat_title_label)
        self.chat_status_label = QLabel("")
        self.chat_status_label.setStyleSheet("font-size: 13px; color: #888888;")
        info_layout.addWidget(self.chat_status_label)
        header_layout.addWidget(info_container)
        header_layout.addStretch()
        layout.addWidget(chat_header)
        
        self.messages_scroll = MessageScrollArea()
        layout.addWidget(self.messages_scroll, 1)
        
        input_container = QWidget()
        input_container.setStyleSheet("QWidget { background-color: #ffffff; border-top: 1px solid #e8e8e8; }")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(12)
        
        attach_btn = QPushButton("Attach")
        attach_btn.setFixedSize(44, 44)
        attach_btn.setCursor(Qt.PointingHandCursor)
        attach_btn.clicked.connect(self.attach_file)
        attach_btn.setStyleSheet("QPushButton { background-color: #f5f5f5; border: none; border-radius: 22px; font-size: 14px; } QPushButton:hover { background-color: #e8e8e8; }")
        input_layout.addWidget(attach_btn)
        
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Write a message...")
        self.message_input.setMinimumHeight(44)
        self.message_input.returnPressed.connect(self.send_message)
        self.message_input.setStyleSheet("QLineEdit { border: none; background-color: #f5f5f5; border-radius: 22px; padding: 0px 20px; font-size: 14px; color: #333333; } QLineEdit:focus { outline: none; background-color: #eeeeee; }")
        input_layout.addWidget(self.message_input, 1)
        
        self.send_button = QPushButton("Send")
        self.send_button.setFixedSize(44, 44)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setStyleSheet("QPushButton { background-color: #3390ec; color: white; border: none; border-radius: 22px; font-size: 14px; font-weight: bold; } QPushButton:hover { background-color: #2885db; } QPushButton:pressed { background-color: #1e73c7; }")
        input_layout.addWidget(self.send_button)
        
        layout.addWidget(input_container)
        return widget

    def start_login(self):
        phone, ok = QInputDialog.getText(self, "Login", "Enter your phone number (e.g., +79991234567):")
        if not ok or not phone:
            sys.exit(0)
        
        self.telegram_thread = TelegramThread(self.api_id, self.api_hash, phone)
        self.telegram_thread.message_received.connect(self.on_message_received)
        self.telegram_thread.login_success.connect(self.on_login_success)
        self.telegram_thread.login_error.connect(self.on_login_error)
        self.telegram_thread.dialogs_ready.connect(self.on_dialogs_received)
        self.telegram_thread.need_code.connect(self.on_need_code)
        self.telegram_thread.need_password.connect(self.on_need_password)
        self.telegram_thread.start()

    def on_message_received(self, msg):
        logger.info("Message received: %s", msg.get("text", "")[:50])
        self.db.save_message(
            str(msg["chat_id"]),
            msg["id"],
            msg.get("sender_id", 0),
            msg.get("text", ""),
            "",
            "",
            0
        )
        if self.current_chat_id != msg["chat_id"]:
            self.db.increment_unread_count(msg["chat_id"])
        self.show_notification(msg)
        if self.current_chat_id == msg["chat_id"]:
            self.display_message(msg)
        self.refresh_chat_list()

    def on_need_code(self):
        code, ok = QInputDialog.getText(self, "Verification Code", "Enter the verification code from Telegram:", QLineEdit.Normal)
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_code(code)

    def on_need_password(self):
        pwd, ok = QInputDialog.getText(self, "Two-Factor Authentication", "Enter your 2FA password:", QLineEdit.Password)
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_password(pwd)

    def on_login_success(self):
        QMessageBox.information(self, "Success", "Logged in successfully!")
        self.telegram_thread.request_dialogs_now()

    def on_login_error(self, error_msg):
        reply = QMessageBox.critical(self, "Error", "Login failed: %s\n\nRetry?" % error_msg, QMessageBox.Yes | QMessageBox.No)
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
            try:
                chat_id = str(dialog["id"])
                self.dialogs_cache[chat_id] = dialog
                unread = self.db.get_unread_count(chat_id)
                last_message = dialog.get("message", "")
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, 80))
                item_widget = ChatListItem(name=dialog["name"], last_message=last_message, unread_count=unread, timestamp="")
                item.setData(Qt.UserRole, chat_id)
                self.chat_list.addItem(item)
                self.chat_list.setItemWidget(item, item_widget)
            except Exception as e:
                logger.error("Error processing dialog: %s", e)

    def on_chat_selected(self, item):
        chat_id = item.data(Qt.UserRole)
        if not chat_id:
            return
        self.current_chat_id = chat_id
        dialog = self.dialogs_cache.get(chat_id, {})
        chat_name = dialog.get("name", "Chat")
        self.chat_title_label.setText(chat_name)
        self.chat_status_label.setText("online")
        self.chat_avatar.setText(chat_name[0].upper() if chat_name else "?")
        self.messages_scroll.clear_messages()
        self.db.reset_unread_count(chat_id)
        db_messages = self.db.get_chat_history(chat_id, limit=100)
        for msg in db_messages:
            self.display_message(msg)
        if self.telegram_thread and self.telegram_thread.loop:
            asyncio.run_coroutine_threadsafe(self._fetch_telegram_history(chat_id), self.telegram_thread.loop)
        self.refresh_chat_list()

    async def _fetch_telegram_history(self, chat_id):
        try:
            # Получаем больше истории для полной синхронизации
            messages = await self.telegram_thread.client.get_chat_history(chat_id, limit=500)
            
            # Проверяем какие сообщения уже есть в БД
            db_existing = self.db.get_chat_history(chat_id, limit=1000)
            existing_ids = {msg.get('id') for msg in db_existing if msg.get('id')}
            
            saved_count = 0
            for msg in reversed(messages):
                sender_name = msg.get("sender_name", "Unknown")
                sender_id = msg.get("sender_id", 0)
                msg_id = msg.get("id", 0)
                msg_text = msg.get("text", "")
                is_outgoing = msg.get("is_outgoing", False)
                msg_date = msg.get("date")
                
                # Пропускаем уже сохранённые
                if msg_id in existing_ids:
                    continue
                
                if isinstance(msg_date, str):
                    try:
                        msg_date = datetime.fromisoformat(msg_date.replace("Z", "+00:00"))
                        timestamp_str = msg_date.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        timestamp_str = msg_date
                elif msg_date:
                    timestamp_str = msg_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(msg_date, 'strftime') else str(msg_date)
                else:
                    timestamp_str = None
                
                self.db.save_message(
                    str(chat_id),
                    msg_id,
                    sender_id,
                    msg_text,
                    "",
                    "",
                    1 if is_outgoing else 0
                )
                saved_count += 1
                
                # Показываем только если это текущий открытый чат
                if chat_id == self.current_chat_id:
                    msg_data = {"text": msg_text, "sender_name": sender_name, "is_outgoing": is_outgoing, "timestamp": timestamp_str, "first_name": sender_name}
                    QTimer.singleShot(0, lambda m=msg_data: self.display_message(m))
                
                await asyncio.sleep(0.005)  # Быстрее, но без перегрузки
            
            logger.info(f"Синхронизировано {saved_count} новых сообщений для чата {chat_id}")
            
        except Exception as e:
            logger.error("Error loading Telegram history: %s", e)

    def display_message(self, msg):
        text = msg.get("text", "")
        if not text:
            return
        sender_name = msg.get("sender_name", msg.get("first_name", "Unknown"))
        is_outgoing = bool(msg.get("is_outgoing", 0))
        timestamp = msg.get("timestamp", "")
        self.messages_scroll.add_message(text, sender_name, is_outgoing, timestamp)

    def send_message(self):
        text = self.message_input.text().strip()
        if not text or not self.current_chat_id:
            return
        self.message_input.clear()
        self.display_message({"text": text, "sender_name": "You", "is_outgoing": True, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        if self.telegram_thread:
            self.telegram_thread.send_message(int(self.current_chat_id), text)
        # Исправлено: параметры строго соответствуют сигнатуре Database.save_message(chat_id, message_id, sender_id, text, media_path, media_type, is_outgoing)
        self.db.save_message(
            str(self.current_chat_id),  # chat_id
            int(time.time() * 1000),    # message_id
            0,                          # sender_id (0 для исходящих от текущего пользователя)
            text,                       # text
            "",                         # media_path (пусто для текста)
            "",                         # media_type (пусто для текста)
            1                           # is_outgoing (1 = True)
        )

    def attach_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)")
        if file_path and self.current_chat_id:
            if self.telegram_thread:
                self.telegram_thread.send_message(int(self.current_chat_id), "", file_path)

    def show_notification(self, msg):
        if self.current_chat_id != msg["chat_id"]:
            try:
                notification.notify(title=msg.get("sender_name", "New Message"), message=msg.get("text", "")[:200], app_name="Telegram Messenger", timeout=5)
            except Exception as e:
                logger.debug("Notification error: %s", e)

    def refresh_chat_list(self):
        dialogs = list(self.dialogs_cache.values())
        self.on_dialogs_received(dialogs)

    def closeEvent(self, event):
        if self.telegram_thread:
            self.telegram_thread.stop()
            self.telegram_thread.wait(3000)
        event.accept()


if __name__ == "__main__":
    API_ID = 123456
    API_HASH = "your_api_hash"
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    window = ChatApp(API_ID, API_HASH)
    window.show()
    sys.exit(app.exec_())
