#!/usr/bin/env python3
import sys
import os
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication
from chat_client import ChatApp

load_dotenv()

# Замените на свои данные от my.telegram.org
API_ID = int(os.getenv('API_ID'))  # Ваш API ID
API_HASH = API_HASH = os.getenv('API_HASH')  # Ваш API Hash

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Messenger")
    window = ChatApp(API_ID, API_HASH)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()