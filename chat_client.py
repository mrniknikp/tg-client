import sys
import asyncio
import os
import time
import ctypes
from ctypes import wintypes
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QTextEdit, QLineEdit,
                             QPushButton, QSplitter, QMessageBox, QInputDialog,
                             QFileDialog, QLabel, QListWidgetItem, QFrame, 
                             QGraphicsDropShadowEffect, QScrollArea)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, QObject
from PyQt5.QtGui import QFont, QTextCursor, QIcon, QPalette, QColor, QPixmap, QPainter
from plyer import notification
from database import Database
from telegram_client import TelegramClientWrapper
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# WinAPI для системных уведомлений
class WindowsNotifier:
    """Класс для отправки уведомлений через WinAPI"""
    
    @staticmethod
    def send_notification(title, message, icon_path=None):
        try:
            # Пробуем использовать ctypes для вызова Windows Toast через Shell
            # Это более надежный способ чем COM
            import subprocess
            # Создаем PowerShell скрипт для уведомления
            ps_script = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            
            $template = @"
<toast>
    <visual>
        <binding template="ToastText02">
            <text id="1">{title}</text>
            <text id="2">{message[:200]}</text>
        </binding>
    </visual>
</toast>
"@
            
            $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
            $xml.LoadXml($template)
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Telegram Messenger").Show($toast)
            '''
            subprocess.run(['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script], 
                          capture_output=True, timeout=5)
            return True
        except Exception as e:
            logger.debug(f"PowerShell notification error: {e}")
            # Fallback на plyer
            try:
                notification.notify(
                    title=title,
                    message=message[:200],
                    app_name="Telegram Messenger",
                    timeout=5
                )
                return True
            except Exception as e2:
                logger.debug(f"Plyer notification error: {e2}")
                # Если все методы не работают, просто логируем
                logger.info(f"Notification: {title} - {message[:100]}")
                return False


class MessageWorker(QThread):
    """Фоновый воркер для обработки входящих сообщений"""
    message_processed = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.message_queue = []
        self.running = True
    
    def add_message(self, message):
        self.message_queue.append(message)
    
    def run(self):
        while self.running:
            if self.message_queue:
                msg = self.message_queue.pop(0)
                self.message_processed.emit(msg)
            else:
                self.msleep(50)
    
    def stop(self):
        self.running = False

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
        self._code_requested = False
        self._password_requested = False

    def set_code(self, code):
        self.code = code
        if self._code_requested:
            self.code_event.set()

    def set_password(self, password):
        self.password = password
        if self._password_requested:
            self.password_event.set()

    def reset_code_event(self):
        self.code_event.clear()
        self.code = None
        self._code_requested = False

    def reset_password_event(self):
        self.password_event.clear()
        self.password = None
        self._password_requested = False

    async def get_code_async(self):
        # Сначала сигнализируем UI, что нужен код
        self._code_requested = True
        self.code_event.clear()
        self.need_code.emit()
        # Ждем пока пользователь введет код
        await self.code_event.wait()
        return self.code

    async def get_password_async(self):
        # Сначала сигнализируем UI, что нужен пароль
        self._password_requested = True
        self.password_event.clear()
        self.need_password.emit()
        # Ждем пока пользователь введет пароль
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
                        self.reset_code_event()
                        # need_code уже был вызван в get_code_async, просто ждем новый код
                        continue
                    elif err == "PASSWORD_INVALID":
                        self.reset_password_event()
                        # need_password уже был вызван в get_password_async
                        continue
                    elif err == "PASSWORD_REQUIRED":
                        # need_password будет вызван в get_password_async
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
        """Периодическое обновление списка чатов каждые 0.5 секунды"""
        last_dialogs = None
        consecutive_flood_waits = 0
        while not self._stop_requested:
            try:
                # Получаем диалоги с ограничением по времени для предотвращения flood wait
                dialogs = await self.client.get_dialogs(limit=50)
                
                # Сбрасываем счетчик flood wait при успехе
                consecutive_flood_waits = 0
                
                # Отправляем только если есть изменения (оптимизация трафика)
                if dialogs != last_dialogs:
                    self.dialogs_ready.emit(dialogs)
                    last_dialogs = dialogs
            except Exception as e:
                err_str = str(e)
                if "flood wait" in err_str.lower():
                    # При flood wait увеличиваем интервал
                    consecutive_flood_waits += 1
                    logger.warning(f"Flood wait detected (count: {consecutive_flood_waits}): {e}")
                    # Ждем дольше при каждом последующем flood wait, но не более 60 секунд
                    wait_time = min(5 * consecutive_flood_waits, 60)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Error fetching dialogs: {e}")
                    # При других ошибках тоже делаем паузу
                    await asyncio.sleep(2)
            await asyncio.sleep(0.5)  # Обновление каждые 0.5 секунды

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
        self.message_worker = None  # Фоновый воркер для обработки сообщений
        self.current_chat_id = None
        self.dialogs_cache = {}
        self.last_message_ids = set()  # Для предотвращения дублирования сообщений
        self.init_ui()
        # Не запускаем логин сразу - дадим приложению инициализироваться
        # start_login будет вызван после показа окна через QTimer.singleShot
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self.start_login)

    def init_ui(self):
        self.setWindowTitle("Telegram Messenger (via Proxy)")
        self.setGeometry(100, 100, 1200, 800)
        
        # Применяем современный стиль
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QListWidget {
                border: none;
                background-color: #ffffff;
                font-size: 14px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #e0e0e0;
            }
            QListWidget::item:selected {
                background-color: #3390ec;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #e3f2fd;
            }
            QTextEdit {
                border: none;
                background-color: #ffffff;
                font-size: 14px;
                padding: 10px;
            }
            QLineEdit {
                border: 2px solid #e0e0e0;
                border-radius: 20px;
                padding: 10px 15px;
                font-size: 14px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border: 2px solid #3390ec;
            }
            QPushButton {
                background-color: #3390ec;
                color: white;
                border: none;
                border-radius: 20px;
                padding: 10px 25px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2885db;
            }
            QPushButton:pressed {
                background-color: #1e73c7;
            }
            QSplitter::handle {
                background-color: #e0e0e0;
                width: 1px;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #c0c0c0;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #a0a0a0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        main_layout.addWidget(splitter)
        
        # Левая панель - список чатов
        left_widget = QWidget()
        left_widget.setStyleSheet("background-color: #ffffff;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        
        # Заголовок
        header_label = QLabel("Chats")
        header_label.setStyleSheet("""
            QLabel {
                background-color: #3390ec;
                color: white;
                font-size: 18px;
                font-weight: bold;
                padding: 15px;
            }
        """)
        left_layout.addWidget(header_label)
        
        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self.on_chat_selected)
        left_layout.addWidget(self.chat_list)
        
        splitter.addWidget(left_widget)
        
        # Правая панель - чат
        right = QWidget()
        right.setStyleSheet("background-color: #f5f5f5;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(10)
        splitter.addWidget(right)
        
        # Область сообщений с заголовком
        chat_header = QLabel("")
        chat_header.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                color: #333333;
                font-size: 16px;
                font-weight: bold;
                padding: 12px;
                border-radius: 10px;
            }
        """)
        right_layout.addWidget(chat_header)
        
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        self.messages_area.setFont(QFont("Segoe UI", 11))
        self.messages_area.setStyleSheet("""
            QTextEdit {
                border: 1px solid #e0e0e0;
                border-radius: 10px;
                background-color: #ffffff;
                padding: 10px;
            }
        """)
        right_layout.addWidget(self.messages_area)
        
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        self.attach_button = QPushButton("📎")
        self.attach_button.setFixedSize(50, 50)
        self.attach_button.clicked.connect(self.attach_file)
        input_layout.addWidget(self.attach_button)
        
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message...")
        self.message_input.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.message_input)
        
        self.send_button = QPushButton("Send")
        self.send_button.setFixedSize(80, 50)
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_button)
        
        right_layout.addLayout(input_layout)
        
        splitter.setSizes([350, 850])
        
        self.chat_header_label = chat_header
        
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_chat_list)
        self.refresh_timer.start(5000)

    def start_login(self):
        phone, ok = QInputDialog.getText(self, "Login", "Enter phone number (e.g., +71234567890):")
        if not ok or not phone:
            sys.exit(0)
        
        # Запускаем фоновый воркер для обработки сообщений
        self.message_worker = MessageWorker()
        self.message_worker.message_processed.connect(self.process_message_from_worker)
        self.message_worker.start()
        
        self.telegram_thread = TelegramThread(self.api_id, self.api_hash, phone)
        self.telegram_thread.login_success.connect(self.on_login_success)
        self.telegram_thread.login_error.connect(self.on_login_error)
        self.telegram_thread.message_received.connect(self.on_message_received)
        self.telegram_thread.dialogs_ready.connect(self.on_dialogs_received)
        self.telegram_thread.need_code.connect(self.on_need_code)
        self.telegram_thread.need_password.connect(self.on_need_password)
        self.telegram_thread.start()
        # Не запрашиваем код здесь - дождемся сигнала need_code

    def on_message_received(self, msg):
        """Получение сообщения от Telegram и отправка в воркер"""
        if self.message_worker:
            self.message_worker.add_message(msg)
    
    def process_message_from_worker(self, msg):
        """Обработка сообщения из фонового воркера"""
        # Проверка на дублирование по ID
        msg_key = f"{msg['chat_id']}_{msg['id']}"
        if msg_key in self.last_message_ids:
            return  # Пропускаем дубликат
        self.last_message_ids.add(msg_key)
        
        # Ограничиваем размер множества ID
        if len(self.last_message_ids) > 1000:
            self.last_message_ids = set(list(self.last_message_ids)[-500:])
        
        # Сохраняем в БД
        self.db.save_message(
            chat_id=msg['chat_id'],
            message_id=msg['id'],
            sender_id=msg['sender_id'],
            text=msg['text'],
            media_path=msg.get('media_path', ''),
            media_type=msg.get('media_type', ''),
            is_outgoing=1 if msg.get('is_outgoing', False) else 0
        )
        self.db.save_user(
            user_id=msg['sender_id'],
            username=msg.get('sender_username', ''),
            first_name=msg.get('sender_name', '')
        )
        
        # Обновляем счетчик непрочитанных
        if self.current_chat_id != msg['chat_id']:
            self.db.increment_unread_count(msg['chat_id'])
        
        # Показываем уведомление через WinAPI
        self.show_notification(msg)
        
        # Если чат открыт - отображаем сообщение
        if self.current_chat_id == msg['chat_id']:
            self.display_message(msg)
        
        # Обновляем список чатов
        self.refresh_chat_list()

    def on_need_code(self):
        # Показываем диалог ввода кода
        code, ok = QInputDialog.getText(self, "Verification Code", 
            "Enter the verification code you received from Telegram:",
            QLineEdit.Normal)
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_code(code)

    def on_need_password(self):
        # Показываем диалог ввода пароля
        pwd, ok = QInputDialog.getText(self, "Two-Factor Authentication", 
            "Enter your two-factor authentication password:",
            QLineEdit.Password)
        if not ok:
            sys.exit(0)
        self.telegram_thread.set_password(pwd)

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
        """Обновление списка чатов с красивым отображением"""
        self.chat_list.clear()
        self.dialogs_cache.clear()
        for dialog in dialogs:
            try:
                chat_id = str(dialog['id'])
                self.dialogs_cache[chat_id] = dialog
                unread = self.db.get_unread_count(chat_id)
                
                # Форматируем текст чата с последним сообщением
                last_message = dialog.get('message', '')
                if last_message and len(last_message) > 40:
                    last_message = last_message[:37] + "..."
                
                # Создаем виджет для элемента списка
                item_widget = QWidget()
                item_widget.setStyleSheet("""
                    QWidget {
                        background-color: white;
                        border-bottom: 1px solid #e0e0e0;
                    }
                    QWidget:hover {
                        background-color: #e3f2fd;
                    }
                """)
                item_layout = QVBoxLayout(item_widget)
                item_layout.setContentsMargins(12, 8, 12, 8)
                item_layout.setSpacing(4)
                
                # Название чата
                name_label = QLabel(dialog['name'])
                name_label.setStyleSheet("""
                    QLabel {
                        font-size: 14px;
                        font-weight: bold;
                        color: #333333;
                    }
                """)
                item_layout.addWidget(name_label)
                
                # Последнее сообщение
                if last_message:
                    msg_label = QLabel(last_message)
                    msg_label.setStyleSheet("""
                        QLabel {
                            font-size: 12px;
                            color: #888888;
                        }
                    """)
                    item_layout.addWidget(msg_label)
                
                # Счетчик непрочитанных
                if unread > 0:
                    unread_label = QLabel(f"✉️ {unread}")
                    unread_label.setStyleSheet("""
                        QLabel {
                            font-size: 12px;
                            color: #3390ec;
                            font-weight: bold;
                        }
                    """)
                    unread_label.setAlignment(Qt.AlignRight)
                    item_layout.addWidget(unread_label)
                
                # Создаем элемент списка
                item = QListWidgetItem()
                item.setData(Qt.UserRole, chat_id)
                item.setSizeHint(item_widget.sizeHint())
                self.chat_list.addItem(item)
                self.chat_list.setItemWidget(item, item_widget)
            except Exception as e:
                logger.error(f"Error processing dialog: {e}")

    def show_notification(self, msg):
        """Показ уведомления через WinAPI или plyer"""
        try:
            title = f"New message from {msg.get('sender_name', 'Unknown')}"
            message_text = msg.get('text', '')[:200] if msg.get('text') else "📎 Media file"
            
            # Используем WinAPI для уведомлений
            WindowsNotifier.send_notification(title, message_text)
        except Exception as e:
            logger.error(f"Notification error: {e}")

    def refresh_chat_list(self):
        """Обновление списка чатов"""
        if self.telegram_thread and self.telegram_thread.isRunning():
            self.telegram_thread.request_dialogs_now()

    def on_chat_selected(self, item):
        chat_id = item.data(Qt.UserRole)
        if chat_id:
            self.current_chat_id = chat_id
            # Обновляем заголовок чата
            if chat_id in self.dialogs_cache:
                dialog = self.dialogs_cache[chat_id]
                self.chat_header_label.setText(f"💬 {dialog['name']}")
            else:
                self.chat_header_label.setText("Chat")
            self.load_chat_history(chat_id)
            self.db.reset_unread_count(chat_id)
            self.refresh_chat_list()

    def load_chat_history(self, chat_id):
        self.messages_area.clear()
        for msg in self.db.get_chat_history(chat_id):
            self.display_message(msg)

    def display_message(self, msg):
        """Красивое отображение сообщений в стиле Telegram"""
        cursor = self.messages_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # Корректная обработка is_outgoing из БД (может быть int, bool, None)
        is_outgoing_val = msg.get('is_outgoing', 0)
        if is_outgoing_val is None:
            is_outgoing_val = 0
        is_out = bool(is_outgoing_val)
        
        # Стиль для входящих и исходящих сообщений
        if is_out:
            # Исходящее сообщение - справа, синее
            bg_color = "#e3f2fd"
            align = "right"
            sender_name = "You"
            avatar_color = "#3390ec"
        else:
            # Входящее сообщение - слева, белое
            bg_color = "#ffffff"
            align = "left"
            sender_name = msg.get('first_name', msg.get('sender_name', 'Unknown'))
            avatar_color = "#4caf50"
        
        text = msg.get('text', '') or ''
        # Экранируем HTML спецсимволы
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        timestamp = ""
        if 'timestamp' in msg and msg['timestamp']:
            try:
                ts = msg['timestamp']
                if isinstance(ts, str):
                    # Пробуем разные форматы
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                        try:
                            dt = datetime.strptime(ts[:19], fmt)
                            timestamp = dt.strftime("%H:%M")
                            break
                        except:
                            continue
                    else:
                        timestamp = datetime.now().strftime("%H:%M")
                else:
                    timestamp = datetime.now().strftime("%H:%M")
            except:
                timestamp = datetime.now().strftime("%H:%M")
        elif 'date' in msg and msg['date']:
            try:
                if isinstance(msg['date'], str):
                    dt = datetime.fromisoformat(msg['date'].replace('Z', '+00:00'))
                else:
                    dt = msg['date']
                timestamp = dt.strftime("%H:%M")
            except:
                timestamp = datetime.now().strftime("%H:%M")
        else:
            timestamp = datetime.now().strftime("%H:%M")
        
        # Первая буква имени для аватара
        avatar_letter = sender_name[0].upper() if sender_name else "?"
        
        html = f"""
        <div style="margin:8px 0; display:flex; {'justify-content:flex-end;' if align == 'right' else 'justify-content:flex-start;'}">
            {'<div style="width:36px;"></div>' if align == 'right' else f'<div style="width:40px; height:40px; border-radius:50%; background:{avatar_color}; color:white; display:flex; align-items:center; justify-content:center; font-weight:bold; margin-right:8px;">{avatar_letter}</div>'}
            <div style="max-width:70%;">
                {'<div style="font-size:11px; color:#888; text-align:right; margin-bottom:3px;">' + sender_name + '</div>' if align == 'right' else ''}
                <div style="padding:10px 14px; border-radius:18px; background:{bg_color}; box-shadow:0 1px 3px rgba(0,0,0,0.12);">
                    <div style="font-size:14px; color:#333; line-height:1.4;">{text}</div>
                    <div style="font-size:11px; color:#999; text-align:right; margin-top:4px;">{timestamp}</div>
                </div>
            </div>
            {'<div style="width:40px;"></div>' if align == 'left' else ''}
        </div>
        """
        
        media_path = msg.get('media_path')
        if media_path and os.path.exists(str(media_path)):
            html += f'<div style="margin:5px 0;"><a href="file://{media_path}" style="color:#3390ec;">📎 Open file</a></div>'
        
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
        """Корректное завершение работы приложения"""
        if self.message_worker:
            self.message_worker.stop()
            self.message_worker.quit()
            self.message_worker.wait(1000)
        
        if self.telegram_thread:
            self.telegram_thread.stop()
            self.telegram_thread.quit()
            self.telegram_thread.wait(2000)
        
        self.db.close()
        event.accept()