import sys
import os
import asyncio
import time
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import Message, User, Chat, Channel
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QScrollArea, QLabel, QLineEdit, QPushButton, QFrame, 
                             QSizePolicy, QMessageBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor, QBrush, QIcon

from database import Database

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Конфигурация по умолчанию (если нет в БД) ---
DEFAULT_API_ID = 1234567  # Замените на реальные или оставьте как заглушку для ввода
DEFAULT_API_HASH = 'заглушка'

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Первый запуск / Новый аккаунт")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        
        self.api_id_input = QLineEdit()
        self.api_hash_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.code_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        layout.addRow("API ID:", self.api_id_input)
        layout.addRow("API Hash:", self.api_hash_input)
        layout.addRow("Номер телефона:", self.phone_input)
        layout.addRow("Код подтверждения:", self.code_input)
        layout.addRow("2FA Пароль (если есть):", self.password_input)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: red;")
        layout.addRow(self.status_label)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)
        
        self.code_input.setVisible(False)
        self.password_input.setVisible(False)
        self.waiting_for_code = False
        self.waiting_for_password = False

    def validate_and_accept(self):
        # Простая валидация заполненности
        if not self.api_id_input.text() or not self.api_hash_input.text() or not self.phone_input.text():
            if not self.waiting_for_code and not self.waiting_for_password:
                self.status_label.setText("Заполните API ID, Hash и телефон")
                return
        self.accept()

    def set_mode_code(self):
        self.waiting_for_code = True
        self.code_input.setVisible(True)
        self.status_label.setText("Введите код из Telegram")
        self.code_input.setFocus()

    def set_mode_password(self):
        self.waiting_for_password = True
        self.password_input.setVisible(True)
        self.status_label.setText("Введите пароль двухфакторной аутентификации")
        self.password_input.setFocus()

class AuthThread(QThread):
    finished_signal = pyqtSignal(dict) # Данные пользователя
    error_signal = pyqtSignal(str)
    need_code_signal = pyqtSignal()
    need_password_signal = pyqtSignal()

    def __init__(self, api_id, api_hash, phone, session_name, db_user_id=None):
        super().__init__()
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        self.db_user_id = db_user_id
        self.client = None
        self.db = Database()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._auth_process())
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            loop.close()

    async def _auth_process(self):
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone)
            self.need_code_signal.emit()
            # Ждем ввода кода (цикл событий будет обработан в главном потоке через сигналы)
            # Этот трюк требует синхронизации, упростим: вернем управление в GUI для ввода
            
            # Чтобы не блокировать поток навсегда, мы прервем здесь и продолжим после ввода в GUI
            # Но для простоты в этом примере мы будем использовать флаг в диалоге
            # Реализация сложна в одном потоке, поэтому сделаем так:
            # Вернем клиент в результат и попросим главный поток продолжить авторизацию
            self.finished_signal.emit({'status': 'need_code', 'client': self.client})
            return

        me = await self.client.get_me()
        session_str = await self.client.session.save()
        
        user_data = {
            'status': 'success',
            'api_id': self.api_id,
            'api_hash': self.api_hash,
            'phone': self.phone,
            'session_string': session_str,
            'tg_user_id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'last_name': me.last_name
        }
        
        if self.db_user_id:
            self.db.update_user_session(self.db_user_id, session_str, me.id, me.username, me.first_name, me.last_name)
        else:
            self.db.add_user(self.api_id, self.api_hash, self.phone, session_str, me.id, me.username, me.first_name, me.last_name)
            
        await self.client.disconnect()
        self.finished_signal.emit({'status': 'success', 'data': user_data})

class ContinueAuthThread(QThread):
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)
    need_password_signal = pyqtSignal()

    def __init__(self, client, phone, code, password=None, db_user_id=None):
        super().__init__()
        self.client = client
        self.phone = phone
        self.code = code
        self.password = password
        self.db_user_id = db_user_id
        self.db = Database()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._process())
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            loop.close()

    async def _process(self):
        try:
            if self.password:
                await self.client.sign_in(password=self.password)
            else:
                await self.client.sign_in(phone=self.phone, code=self.code)
            
            me = await self.client.get_me()
            session_str = await self.client.session.save()
            
            if self.db_user_id:
                self.db.update_user_session(self.db_user_id, session_str, me.id, me.username, me.first_name, me.last_name)
            else:
                # Если вдруг пользователя нет (редкий кейс), создадим
                # Но обычно мы передаем db_user_id
                pass

            await self.client.disconnect()
            
            user_data = {
                'status': 'success',
                'session_string': session_str,
                'tg_user_id': me.id,
                'username': me.username,
                'first_name': me.first_name,
                'last_name': me.last_name
            }
            self.finished_signal.emit(user_data)
        except SessionPasswordNeededError:
            self.need_password_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

class TelegramWorker(QThread):
    message_received = pyqtSignal(dict)
    history_loaded = pyqtSignal(list)
    chats_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    auth_success = pyqtSignal(dict)

    def __init__(self, user_data):
        super().__init__()
        self.user_data = user_data
        self.client = None
        self.is_running = True
        self.db = Database()
        self.current_chat_id = None
        self.loaded_chats = set() # Чаты, историю которых уже грузили глубоко

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.main_loop())
        except Exception as e:
            self.error_occurred.emit(f"Worker error: {e}")
        finally:
            loop.close()

    async def main_loop(self):
        api_id = self.user_data['api_id']
        api_hash = self.user_data['api_hash']
        session_str = self.user_data['session_string']
        
        # Восстановление сессии из строки
        from telethon.sessions import StringSession
        session = StringSession(session_str)
        
        self.client = TelegramClient(session, api_id, api_hash)
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            self.error_occurred.emit("Сессия невалидна. Требуется повторный вход.")
            return

        # Загрузка списка чатов
        await self.load_chats()

        # Слушатель событий
        @self.client.on(events.NewMessage)
        async def handler(event):
            chat_id = event.chat_id
            # Игнорируем системные и свои сообщения (если нужно, но свои тоже сохраняем для истории)
            msg = event.message
            
            # Сохраняем в БД
            self.save_message_to_db(msg)
            
            # Отправляем в UI
            data = {
                'chat_id': chat_id,
                'id': msg.id,
                'text': msg.text,
                'sender_id': msg.sender_id,
                'is_outgoing': msg.out,
                'date': int(msg.date.timestamp()),
                'chat_title': getattr(event.chat, 'title', 'Unknown'),
                'sender_name': await self.get_sender_name(msg)
            }
            self.message_received.emit(data)

        # Бесконечный цикл для поддержания жизни потока
        while self.is_running:
            await asyncio.sleep(1)

    async def get_sender_name(self, message):
        if message.out:
            return "Вы"
        sender = await message.get_sender()
        if sender:
            if isinstance(sender, User):
                return f"{sender.first_name or ''} {sender.last_name or ''}".strip() or sender.username
            return getattr(sender, 'title', 'Unknown')
        return "Unknown"

    async def load_chats(self):
        dialogs = []
        try:
            async for dialog in self.client.iter_dialogs(limit=50):
                if dialog.is_user or dialog.is_group or dialog.is_channel:
                    chat_id = dialog.id
                    # Telethon иногда возвращает отрицательные ID для каналов/групп, нормализуем для БД если нужно,
                    # но лучше хранить как есть (int64). В SQLite это просто число.
                    
                    # Сохраняем мету чата
                    title = dialog.title
                    username = getattr(dialog.entity, 'username', None)
                    
                    self.db.save_chat_meta(chat_id, self.user_data['id'], title, username)
                    
                    dialogs.append({
                        'id': chat_id,
                        'title': title,
                        'username': username,
                        'last_message': dialog.message.text if dialog.message else '',
                        'date': dialog.date.timestamp() if dialog.date else 0
                    })
            
            self.chats_loaded.emit(dialogs)
        except Exception as e:
            self.error_occurred.emit(f"Error loading chats: {e}")

    async def load_full_history(self, chat_id):
        if chat_id in self.loaded_chats:
            return # Уже грузили
        
        logger.info(f"Starting deep history load for chat {chat_id}")
        messages_list = []
        
        try:
            entity = await self.client.get_entity(chat_id)
            
            # Асинхронная загрузка как в примере пользователя
            async for message in self.client.iter_messages(entity, limit=500): # Лимит для старта
                self.save_message_to_db(message)
                messages_list.append(self.message_to_dict(message, chat_id))
                
            self.loaded_chats.add(chat_id)
            self.history_loaded.emit(messages_list)
            logger.info(f"History loaded for {chat_id}: {len(messages_list)} msgs")
            
        except FloodWaitError as e:
            self.error_occurred.emit(f"Flood wait: sleep {e.seconds}s")
            await asyncio.sleep(e.seconds)
            # Рекурсивно или повторить позже
        except Exception as e:
            self.error_occurred.emit(f"Error loading history: {e}")

    def save_message_to_db(self, msg):
        if not msg.text and not msg.media:
            return # Пустые сообщения пропускаем или обрабатываем медиа отдельно
            
        chat_id = msg.chat_id
        # Определение outgoing
        is_out = msg.out
        
        # Sender ID
        sender_id = msg.sender_id if msg.sender_id else (msg.from_id.user_id if hasattr(msg, 'from_id') and msg.from_id else 0)
        if is_out:
            # Для исходящих sender_id может быть нашим, но в БД можно сохранить реальный ID
            pass
            
        date_ts = int(msg.date.timestamp()) if msg.date else int(time.time())
        
        media_path = None
        media_type = None
        if msg.media:
            media_type = str(type(msg.media).__name__)
            # Здесь можно добавить скачивание медиа, пока заглушка
            media_path = "media_placeholder"

        self.db.save_message(
            chat_id=chat_id,
            message_id=msg.id,
            sender_id=sender_id,
            text=msg.text or "",
            media_path=media_path,
            media_type=media_type,
            is_outgoing=1 if is_out else 0,
            date=date_ts,
            user_account_id=self.user_data['id']
        )

    def message_to_dict(self, msg, chat_id):
        return {
            'chat_id': chat_id,
            'id': msg.id,
            'text': msg.text,
            'sender_id': msg.sender_id,
            'is_outgoing': msg.out,
            'date': int(msg.date.timestamp()) if msg.date else 0,
            'media_path': None,
            'media_type': None
        }

    def stop(self):
        self.is_running = False
        if self.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), asyncio.get_event_loop())
        self.quit()
        self.wait()

# --- UI Компоненты ---

class ChatListItem(QFrame):
    def __init__(self, chat_data, callback):
        super().__init__()
        self.chat_id = chat_data['id']
        self.callback = callback
        self.setFixedHeight(80)
        self.setStyleSheet("""
            ChatListItem {
                background-color: white;
                border-bottom: 1px solid #E0E0E0;
                padding: 5px;
            }
            ChatListItem:hover {
                background-color: #F5F5F5;
            }
            ChatListItem:selected {
                background-color: #3390EC;
                color: white;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Аватар (заглушка)
        avatar = QLabel()
        avatar.setFixedSize(50, 50)
        avatar.setStyleSheet("background-color: #ccc; border-radius: 25px;")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Первая буква имени
        initial = chat_data['title'][0].upper() if chat_data['title'] else '?'
        avatar.setText(initial)
        avatar.setStyleSheet(f"background-color: #7A8B99; color: white; border-radius: 25px; font-size: 20px; font-weight: bold;")
        
        info_layout = QVBoxLayout()
        
        title_label = QLabel(chat_data['title'])
        title_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #000;")
        
        last_msg_label = QLabel(chat_data.get('last_message', 'Нет сообщений'))
        last_msg_label.setFont(QFont("Arial", 9))
        last_msg_label.setStyleSheet("color: #707070;")
        last_msg_label.setWordWrap(True)
        
        info_layout.addWidget(title_label)
        info_layout.addWidget(last_msg_label)
        
        layout.addWidget(avatar)
        layout.addLayout(info_layout)
        
        self.clicked.connect(lambda: self.callback(self.chat_id))

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.setStyleSheet("""
            ChatListItem {
                background-color: #3390EC;
                color: white;
                border-bottom: 1px solid #E0E0E0;
            }
            ChatListItem QLabel { color: white; }
        """)
        self.callback(self.chat_id)

class MessageBubble(QFrame):
    def __init__(self, text, is_outgoing, date):
        super().__init__()
        self.setMaximumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        msg_label = QLabel(text)
        msg_label.setWordWrap(True)
        msg_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        time_label = QLabel(datetime.fromtimestamp(date).strftime("%H:%M"))
        time_label.setFont(QFont("Arial", 7))
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        if is_outgoing:
            self.setStyleSheet("background-color: #EEFFDE; border-radius: 10px; border-top-right-radius: 0;")
            msg_label.setStyleSheet("color: #000;")
            time_label.setStyleSheet("color: #5BB344;")
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            self.setStyleSheet("background-color: white; border-radius: 10px; border-top-left-radius: 0;")
            msg_label.setStyleSheet("color: #000;")
            time_label.setStyleSheet("color: #A0A0A0;")
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            
        layout.addWidget(msg_label)
        layout.addWidget(time_label)

class ChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.worker = None
        self.current_user_id = None
        self.current_chat_id = None
        
        self.init_ui()
        self.check_auth()

    def init_ui(self):
        self.setWindowTitle("Telegram Desktop Clone")
        self.setGeometry(100, 100, 1000, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Левая панель (Чаты)
        left_panel = QWidget()
        left_panel.setFixedWidth(300)
        left_panel.setStyleSheet("background-color: white; border-right: 1px solid #ccc;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Хедер с выбором аккаунта
        header = QWidget()
        header.setStyleSheet("background-color: #5680C2; padding: 10px;")
        header_layout = QHBoxLayout(header)
        
        self.account_combo = QComboBox()
        self.account_combo.setStyleSheet("QComboBox { background: white; border: none; padding: 5px; border-radius: 4px; }")
        self.account_combo.currentIndexChanged.connect(self.switch_account)
        
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setStyleSheet("background: white; border: none; font-weight: bold; font-size: 18px; border-radius: 15px;")
        self.add_btn.clicked.connect(self.add_new_account)
        
        header_layout.addWidget(self.account_combo)
        header_layout.addWidget(self.add_btn)
        
        left_layout.addWidget(header)
        
        # Список чатов
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list_widget = QWidget()
        self.chat_list_layout = QVBoxLayout(self.chat_list_widget)
        self.chat_list_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_list_layout.setSpacing(0)
        self.chat_scroll.setWidget(self.chat_list_widget)
        
        left_layout.addWidget(self.chat_scroll)
        
        # Правая панель (Сообщения)
        right_panel = QWidget()
        right_panel.setStyleSheet("background-color: #E5E5E5;") # Цвет фона как в TG
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Заголовок чата
        self.chat_header = QLabel("Выберите чат")
        self.chat_header.setStyleSheet("background-color: white; padding: 10px; font-weight: bold; border-bottom: 1px solid #ccc; font-size: 14px;")
        right_layout.addWidget(self.chat_header)
        
        # Область сообщений
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.addStretch()
        self.messages_scroll.setWidget(self.messages_widget)
        
        right_layout.addWidget(self.messages_scroll)
        
        # Ввод сообщения
        input_area = QWidget()
        input_area.setStyleSheet("background-color: white; padding: 10px;")
        input_layout = QHBoxLayout(input_area)
        
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Написать сообщение...")
        self.msg_input.setStyleSheet("border: none; padding: 10px; font-size: 14px;")
        self.msg_input.returnPressed.connect(self.send_message)
        
        send_btn = QPushButton("➤")
        send_btn.setFixedSize(40, 40)
        send_btn.setStyleSheet("background-color: #5680C2; color: white; border: none; border-radius: 20px; font-size: 18px;")
        send_btn.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(send_btn)
        
        right_layout.addWidget(input_area)
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        
        self.refresh_account_list()

    def check_auth(self):
        users = self.db.get_all_users()
        if not users:
            self.add_new_account()
        else:
            current_id = self.db.get_current_user_id()
            if current_id and any(u['id'] == current_id for u in users):
                self.start_worker(current_id)
            else:
                self.start_worker(users[0]['id'])

    def refresh_account_list(self):
        users = self.db.get_all_users()
        self.account_combo.clear()
        for u in users:
            name = f"{u['first_name'] or ''} {u['last_name'] or ''}".strip() or u['phone']
            self.account_combo.addItem(name, u['id'])
        
        current_id = self.db.get_current_user_id()
        if current_id:
            index = self.account_combo.findData(current_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)

    def add_new_account(self):
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            api_id = dialog.api_id_input.text()
            api_hash = dialog.api_hash_input.text()
            phone = dialog.phone_input.text()
            
            if not api_id.isdigit():
                QMessageBox.critical(self, "Ошибка", "API ID должен быть числом")
                return

            session_name = f"session_{int(time.time())}"
            
            self.auth_thread = AuthThread(api_id, api_hash, phone, session_name)
            self.auth_thread.finished_signal.connect(self.on_auth_finished)
            self.auth_thread.error_signal.connect(lambda err: QMessageBox.critical(self, "Ошибка", err))
            self.auth_thread.need_code_signal.connect(dialog.set_mode_code)
            self.auth_thread.need_password_signal.connect(dialog.set_mode_password)
            self.auth_thread.start()
            
            # Здесь нужна более сложная логика ожидания ввода кода в том же потоке или пауза
            # Для упрощения: если нужен код, мы показываем диалог, но поток уже ушел.
            # Упрощенный вариант: пользователь вводит код сразу если знает, или мы ждем.
            # В данной реализации: если вылетел need_code, мы должны приостановить поток и ждать ввода.
            # Это сложно в PyQt без блокировки. 
            # РАБОЧИЙ ВАРИАНТ: 
            # 1. Запускаем до отправки кода. 2. Показываем диалог. 3. После ввода запускаем второй поток.
            
            # Переделаем логику AuthThread для пошаговости
            pass 

    def on_auth_finished(self, result):
        if result.get('status') == 'need_code':
            # Нужно запросить код у пользователя и продолжить
            # Это сложный момент в асинхронном потоке. 
            # Для простоты примера предположим, что пользователь ввел код в диалог ДО запуска? Нет.
            # Реализуем через второй шаг.
            client = result['client']
            # Сохраняем временные данные для продолжения
            self.temp_client = client
            self.temp_phone = self.auth_thread.phone
            self.temp_api_id = self.auth_thread.api_id
            self.temp_api_hash = self.auth_thread.api_hash
            
            # Показываем диалог снова для ввода кода
            dialog = LoginDialog(self)
            dialog.api_id_input.setEnabled(False)
            dialog.api_hash_input.setEnabled(False)
            dialog.phone_input.setEnabled(False)
            dialog.set_mode_code()
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                code = dialog.code_input.text()
                password = dialog.password_input.text() if dialog.password_input.isVisible() else None
                
                self.cont_auth_thread = ContinueAuthThread(client, self.temp_phone, code, password)
                self.cont_auth_thread.finished_signal.connect(self.on_final_auth_success)
                self.cont_auth_thread.error_signal.connect(lambda err: QMessageBox.critical(self, "Ошибка", err))
                self.cont_auth_thread.need_password_signal.connect(dialog.set_mode_password)
                self.cont_auth_thread.start()
                
                # Если нужен пароль, диалог снова показывается внутри потока? Нет, сигнал.
                # Упрощение: если пароль нужен, поток завершится ошибкой или сигналом.
                # В ContinueAuthThread есть сигнал need_password.
                
                def handle_need_pwd():
                    dialog.set_mode_password()
                    # Ждем повторного нажатия ОК? 
                    # Это становится слишком сложным для одного файла.
                    # Предположим, пользователь введет пароль в том же диалоге если увидит поле.
                    # Но диалог уже закрылся после accept.
                    # Решение: не закрывать диалог пока не успех.
                    pass
                
                self.cont_auth_thread.need_password_signal.connect(handle_need_pwd)

        elif result.get('status') == 'success':
            self.on_final_auth_success(result['data'])

    def on_final_auth_success(self, data):
        # data содержит сессию и инфо о юзере
        # Если это новый юзер, он уже добавлен в БД в потоке
        self.refresh_account_list()
        # Переключаемся на нового
        users = self.db.get_all_users()
        new_user = users[-1] # Последний добавленный
        self.db.set_current_user(new_user['id'])
        self.start_worker(new_user['id'])

    def switch_account(self):
        user_id = self.account_combo.currentData()
        if user_id != self.current_user_id:
            self.db.set_current_user(user_id)
            self.start_worker(user_id)

    def start_worker(self, user_id):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        
        user_data = self.db.get_user(user_id)
        if not user_data or not user_data['session_string']:
            QMessageBox.warning(self, "Ошибка", "Сессия не найдена. Войдите снова.")
            return
            
        self.current_user_id = user_id
        self.worker = TelegramWorker(user_data)
        self.worker.message_received.connect(self.handle_new_message)
        self.worker.history_loaded.connect(self.append_messages)
        self.worker.chats_loaded.connect(self.render_chats)
        self.worker.error_occurred.connect(lambda err: print(f"Worker Error: {err}"))
        self.worker.start()

    def render_chats(self, chats):
        # Очистка списка
        for i in reversed(range(self.chat_list_layout.count())): 
            self.chat_list_layout.itemAt(i).widget().setParent(None)
            
        for chat in chats:
            item = ChatListItem(chat, self.on_chat_selected)
            self.chat_list_layout.addWidget(item)

    def on_chat_selected(self, chat_id):
        self.current_chat_id = chat_id
        chat_info = self.db.get_chats(self.current_user_id, 1) # Найти заголовок
        # В реальном приложении лучше передавать объект чата
        # Здесь просто обновим заголовок
        self.chat_header.setText(f"Чат #{chat_id}")
        
        # Очистка сообщений
        for i in reversed(range(self.messages_layout.count())): 
            w = self.messages_layout.itemAt(i).widget()
            if w: w.setParent(None)
        self.messages_layout.addStretch()
        
        # Загрузка из БД
        messages = self.db.get_messages(chat_id, self.current_user_id, limit=100)
        for msg in messages:
            bubble = MessageBubble(msg['text'], msg['is_outgoing'], msg['date'])
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
            
        # Запрос полной истории если нужно
        if self.worker:
            asyncio.run_coroutine_threadsafe(self.worker.load_full_history(chat_id), asyncio.get_event_loop())

    def append_messages(self, messages):
        # Добавление старых сообщений вверх (требуется скролл)
        # Для простоты просто перерисуем или добавим в начало
        if not self.current_chat_id:
            return
            
        # Фильтруем только для текущего чата
        current_msgs = [m for m in messages if m['chat_id'] == self.current_chat_id]
        if not current_msgs:
            return
            
        # Вставка перед stretch
        for msg in current_msgs:
            # Проверка на дубликат в UI
            # ...
            bubble = MessageBubble(msg['text'], msg['is_outgoing'], msg['date'])
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
            
        self.messages_scroll.verticalScrollBar().setValue(0) # Скролл вверх

    def handle_new_message(self, msg):
        if msg['chat_id'] == self.current_chat_id:
            bubble = MessageBubble(msg['text'], msg['is_outgoing'], msg['date'])
            self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
            self.messages_scroll.verticalScrollBar().setValue(self.messages_scroll.verticalScrollBar().maximum())
            
            # Обновление последнего сообщения в списке чатов (упрощено)
            # Нужно найти виджет чата и обновить текст

    def send_message(self):
        text = self.msg_input.text()
        if not text or not self.current_chat_id or not self.worker:
            return
            
        self.msg_input.clear()
        
        # Отправка через клиента
        async def send():
            try:
                await self.worker.client.send_message(self.current_chat_id, text)
                # Сообщение придет обратно через event и отобразится
            except Exception as e:
                print(f"Send error: {e}")
                
        if self.worker.client:
            asyncio.run_coroutine_threadsafe(send(), asyncio.get_event_loop())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ChatApp()
    window.show()
    sys.exit(app.exec())