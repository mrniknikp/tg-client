import asyncio
import os
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError, RPCError, PhoneCodeInvalidError,
    PasswordHashInvalidError, AuthRestartError
)
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate
import logging
from typing import Optional, Callable, Any, Awaitable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramClientWrapper:
    def __init__(self, api_id: int, api_hash: str, session_name: str = "user_session",
                 connection_retries: int = 5, retry_delay: int = 3):
        # Жёстко заданный MTProto прокси
        self.proxy = ('84.252.74.108', 443, 'd544dfc97e2434c0e410dda5d9cd41a3')
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self.message_callback: Optional[Callable] = None
        self.media_dir = "media"
        self.connection_retries = connection_retries
        self.retry_delay = retry_delay
        if not os.path.exists(self.media_dir):
            os.makedirs(self.media_dir)

    async def start(self, phone: str,
                    code_callback: Callable[[], Awaitable[str]],
                    password_callback: Optional[Callable[[], Awaitable[str]]] = None):
        for attempt in range(1, self.connection_retries + 1):
            try:
                connection = ConnectionTcpMTProxyRandomizedIntermediate
                logger.info(f"Connecting via MTProto proxy {self.proxy[0]}:{self.proxy[1]}")
                self.client = TelegramClient(
                    self.session_name,
                    self.api_id,
                    self.api_hash,
                    connection=connection,
                    connection_retries=None,
                    retry_delay=None,
                    timeout=30,
                    request_retries=5,
                    flood_sleep_threshold=60,
                    proxy=self.proxy
                )
                await self.client.connect()

                if not await self.client.is_user_authorized():
                    await self.client.send_code_request(phone)
                    # Цикл ввода кода
                    while True:
                        try:
                            code = await code_callback()
                            await self.client.sign_in(phone, code)
                            break  # Код верен, выходим из цикла
                        except PhoneCodeInvalidError:
                            # Освобождаем событие для повторного запроса кода
                            raise Exception("CODE_INVALID")
                        except AuthRestartError:
                            # Требуется перезапуск процесса авторизации
                            logger.warning("AuthRestartError received, restarting authorization...")
                            await self.client.disconnect()
                            await asyncio.sleep(1)
                            await self.client.connect()
                            await self.client.send_code_request(phone)
                            continue  # Пробуем снова
                        except SessionPasswordNeededError:
                            # Требуется двухфакторный пароль
                            if not password_callback:
                                raise Exception("PASSWORD_REQUIRED")
                            # Цикл ввода пароля
                            while True:
                                try:
                                    password = await password_callback()
                                    await self.client.sign_in(password=password)
                                    break  # Пароль верен, выходим
                                except PasswordHashInvalidError:
                                    raise Exception("PASSWORD_INVALID")
                                except AuthRestartError:
                                    logger.warning("AuthRestartError during password auth, restarting...")
                                    await self.client.disconnect()
                                    await asyncio.sleep(1)
                                    await self.client.connect()
                                    await self.client.send_code_request(phone)
                                    # Возвращаемся к запросу кода
                                    break
                            else:
                                continue  # После AuthRestartError продолжаем внешний цикл
                            break  # После успешного ввода пароля выходим из внешнего цикла

                @self.client.on(events.NewMessage)
                async def handler(event):
                    if self.message_callback:
                        await self.handle_new_message(event)

                logger.info("Telegram client started successfully")
                return self.client

            except (ConnectionError, OSError, RPCError) as e:
                logger.warning(f"Attempt {attempt}/{self.connection_retries} failed: {e}")
                if attempt == self.connection_retries:
                    raise Exception(f"Connection failed: {e}")
                await asyncio.sleep(self.retry_delay)
            except AuthRestartError as e:
                logger.warning(f"AuthRestartError: {e}, restarting authorization...")
                if self.client and self.client.is_connected():
                    await self.client.disconnect()
                await asyncio.sleep(2)
                if attempt == self.connection_retries:
                    raise Exception(f"Auth restart failed after {attempt} attempts")
                continue  # Пробуем снова
            except Exception as e:
                if str(e) in ("CODE_INVALID", "PASSWORD_INVALID", "PASSWORD_REQUIRED"):
                    raise  # Пробрасываем дальше для обработки в GUI
                logger.error(f"Unexpected error: {e}")
                raise

    async def handle_new_message(self, event):
        try:
            message = event.message
            sender = await event.get_sender()
            chat = await event.get_chat()
            sender_name = getattr(sender, 'first_name', 'Unknown')
            sender_username = getattr(sender, 'username', '')
            media_path = None
            media_type = None
            if message.media:
                media_path, media_type = await self.download_media(message)
            if self.message_callback:
                await self.message_callback({
                    'id': message.id,
                    'chat_id': str(chat.id),
                    'chat_title': getattr(chat, 'title', sender_name),
                    'sender_id': sender.id,
                    'sender_name': sender_name,
                    'sender_username': sender_username,
                    'text': message.text or '',
                    'media_path': media_path,
                    'media_type': media_type,
                    'is_outgoing': message.out
                })
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def download_media(self, message):
        try:
            path = await message.download_media(file=self.media_dir)
            from telethon.tl.types import MessageMediaPhoto
            media_type = "photo" if isinstance(message.media, MessageMediaPhoto) else "document"
            return path, media_type
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None, None

    async def send_message(self, chat_id: int, text: str, file_path: str = None):
        if not self.client:
            raise Exception("Client not started")
        entity = await self.client.get_entity(chat_id)
        if file_path and os.path.exists(file_path):
            await self.client.send_file(entity, file_path, caption=text)
        else:
            await self.client.send_message(entity, text)

    async def get_dialogs(self, limit: int = 50):
        """Получение списка диалогов с ограничением для предотвращения flood wait"""
        if not self.client:
            logger.warning("Telegram client not initialized")
            return []
        try:
            # Ограничиваем количество диалогов для уменьшения нагрузки
            dialogs = await self.client.get_dialogs(limit=limit)
            result = []
            for dialog in dialogs:
                try:
                    result.append({
                        'id': dialog.id,
                        'name': dialog.name,
                        'unread_count': dialog.unread_count,
                        'message': getattr(dialog.message, 'text', '') if dialog.message else ''
                    })
                except Exception as e:
                    logger.error(f"Error processing dialog {dialog}: {e}")
                    continue
            logger.info(f"Fetched {len(result)} dialogs")
            return result
        except Exception as e:
            logger.error(f"Error getting dialogs: {e}")
            return []

    async def get_chat_history(self, chat_id: int, limit: int = 100):
        if not self.client:
            return []
        entity = await self.client.get_entity(chat_id)
        messages = []
        async for message in self.client.iter_messages(entity, limit=limit):
            messages.append({
                'id': message.id,
                'text': message.text or '',
                'sender_id': message.sender_id,
                'date': message.date.isoformat(),
                'media': bool(message.media),
                'is_outgoing': message.out
            })
        return messages

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            logger.info("Disconnected from Telegram")