#!/usr/bin/env python3
import sys
import os
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication, QMessageBox
from chat_client import ChatApp

load_dotenv()

# Замените на свои данные от my.telegram.org
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

def main():
    # Проверка наличия обязательных переменных окружения
    if not API_ID or not API_HASH:
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Configuration Error", 
            "API_ID and API_HASH must be set in .env file or environment variables.\n"
            "Please create a .env file with:\n"
            "API_ID=your_api_id\n"
            "API_HASH=your_api_hash")
        sys.exit(1)
    
    try:
        api_id = int(API_ID)
    except ValueError:
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Configuration Error", 
            "API_ID must be a valid integer.")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Messenger")
    window = ChatApp(api_id, API_HASH)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()