import asyncio
import os
import sys
import signal
from telethon import TelegramClient, events
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate
from database import Database
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
API_ID = int(os.getenv("TG_API_ID", "YOUR_API_ID"))
API_HASH = os.getenv("TG_API_HASH", "YOUR_API_HASH")
PHONE = os.getenv("TG_PHONE", "+YOUR_PHONE")
SESSION_NAME = "background_session"
PROXY = ('84.252.74.108', 443, 'd544dfc97e2434c0e410dda5d9cd41a3')

db = Database()
client = None
running = True

def signal_handler(sig, frame):
    global running
    logger.info("Получен сигнал завершения, останавливаемся...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def save_message_to_db(event):
    """Сохраняет сообщение в базу данных"""
    try:
        message = event.message
        chat = await event.get_chat()
        sender = await event.get_sender()
        
        chat_id = str(getattr(chat, 'id', 0))
        message_id = getattr(message, 'id', 0)
        sender_id = getattr(sender, 'id', 0) if sender else 0
        text = getattr(message, 'text', '') or ''
        is_outgoing = getattr(message, 'out', False)
        
        # Скачиваем медиа если есть
        media_path = None
        media_type = None
        if message.media:
            try:
                media_path = await message.download_media(file="media")
                from telethon.tl.types import MessageMediaPhoto
                media_type = "photo" if isinstance(message.media, MessageMediaPhoto) else "document"
            except Exception as e:
                logger.error(f"Ошибка скачивания медиа: {e}")
        
        # Сохраняем в БД
        db.save_message(
            chat_id=chat_id,
            message_id=message_id,
            sender_id=sender_id,
            text=text,
            media_path=media_path or "",
            media_type=media_type or "",
            is_outgoing=1 if is_outgoing else 0
        )
        
        # Обновляем информацию о чате
        chat_title = getattr(chat, 'title', '') or (getattr(sender, 'first_name', 'Unknown') if sender else 'Unknown')
        timestamp = datetime.now().isoformat()
        db.update_chat_last_message(chat_id, text[:100] if text else "[Медиа]", timestamp)
        
        if not is_outgoing:
            db.increment_unread_count(chat_id)
        
        logger.info(f"Сообщение сохранено: {chat_title} - {text[:50]}...")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения сообщения: {e}")

async def main():
    global client, running
    
    # Создаем директорию для медиа
    os.makedirs("media", exist_ok=True)
    
    connection = ConnectionTcpMTProxyRandomizedIntermediate
    
    logger.info(f"Подключение через MTProto прокси {PROXY[0]}:{PROXY[1]}...")
    
    client = TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
        connection=connection,
        connection_retries=None,
        retry_delay=None,
        timeout=30,
        request_retries=5,
        flood_sleep_threshold=60,
        proxy=PROXY
    )
    
    await client.connect()
    
    if not await client.is_user_authorized():
        logger.warning("Требуется авторизация! Запустите main.py для входа.")
        # Простой ввод кода прямо в консоли
        await client.send_code_request(PHONE)
        code = input("Введите код из Telegram: ")
        try:
            await client.sign_in(PHONE, code)
        except Exception as e:
            if "SESSION_PASSWORD_NEEDED" in str(e):
                password = input("Введите двухфакторный пароль: ")
                await client.sign_in(password=password)
            else:
                raise
    
    # Регистрируем обработчик всех новых сообщений
    @client.on(events.NewMessage(incoming=True))
    async def incoming_handler(event):
        await save_message_to_db(event)
    
    @client.on(events.NewMessage(outgoing=True))
    async def outgoing_handler(event):
        await save_message_to_db(event)
    
    logger.info("Фоновый сервис запущен. Ожидание сообщений...")
    logger.info("Нажмите Ctrl+C для остановки.")
    
    # Основной цикл
    while running:
        await asyncio.sleep(1)
    
    # Остановка
    logger.info("Отключение...")
    await client.disconnect()
    db.close()
    logger.info("Сервис остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Принудительная остановка.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
