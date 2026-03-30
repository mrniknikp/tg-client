import asyncio
import json
import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Message

# --- Конфигурация ---
# ЗДЕСЬ НУЖНО УКАЗАТЬ ВАШИ ДАННЫЕ ИЗ my.telegram.org
API_ID = 1234567  # Замените на ваш api_id (число)
API_HASH = 'ваш_api_hash_здесь'  # Замените на ваш api_hash (строка)
SESSION_NAME = 'my_session'  # Имя файла для сохранения сессии (можно любое)

async def main():
    # Создаем клиентское приложение
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    try:
        # Начинаем сессию
        await client.start()
        print("✅ Авторизация прошла успешно!")
        
        # Запрашиваем у пользователя имя чата
        chat_input = input("\nВведите username (например, @durov), ссылку или ID чата: ")
        
        # Пытаемся получить объект чата по введенным данным
        try:
            entity = await client.get_entity(chat_input)
            print(f"✅ Чат найден: {entity.title if hasattr(entity, 'title') else 'Личный чат'}")
        except Exception as e:
            print(f"❌ Чат '{chat_input}' не найден. Ошибка: {e}")
            return

        print(f"\nНачинаю выгрузку сообщений из чата... Это может занять некоторое время.")
        
        all_messages = []
        # Асинхронно перебираем все сообщения в чате
        # message_date.order('asc') для сортировки от старых к новым
        async for message in client.iter_messages(entity):
            # Преобразуем объект сообщения в удобный для JSON словарь
            message_data = {
                'id': message.id,
                'date': message.date.isoformat() if message.date else None,
                'sender_id': message.sender_id,
                'text': message.text,
                # При необходимости можно добавить другие поля, например:
                # 'media': str(message.media) if message.media else None,
            }
            all_messages.append(message_data)
            
            # Простая индикация прогресса в консоли
            if len(all_messages) % 500 == 0:
                print(f"  ... загружено {len(all_messages)} сообщений")
        
        print(f"✅ Выгрузка завершена. Всего получено сообщений: {len(all_messages)}")
        
        # Сохраняем результат в файл JSON
        output_file = 'chat_export.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_messages, f, ensure_ascii=False, indent=4)
            
        print(f"💾 Данные успешно сохранены в файл: {output_file}")

    except SessionPasswordNeededError:
        print("❌ Для входа требуется двухфакторный пароль. Эта версия скрипта его не поддерживает.")
    except Exception as e:
        print(f"❌ Произошла непредвиденная ошибка: {e}")
    finally:
        # Всегда закрываем соединение
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())