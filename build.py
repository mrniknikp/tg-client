#!/usr/bin/env python3
import os
import sys
import shutil
import platform

def clean_build_dirs():
    for d in ['build', 'dist', '__pycache__']:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Removed: {d}")
    if os.path.exists('telegram_messenger.spec'):
        os.remove('telegram_messenger.spec')
        print("Removed spec file")

def build_windows():
    os.system('pyinstaller --onefile --windowed --name "TelegramMessenger" '
              '--icon=resources/icon.ico '
              '--add-data "resources;resources" '
              '--hidden-import=telethon '
              '--hidden-import=cryptg '
              'main.py')

def build_linux():
    os.system('pyinstaller --onefile --windowed --name "telegram-messenger" '
              '--add-data "resources:resources" '
              '--hidden-import=telethon '
              '--hidden-import=cryptg '
              'main.py')

def main():
    print("=== Building Telegram Messenger ===\n")
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found, installing...")
        os.system('pip install pyinstaller')
    clean_build_dirs()
    system = platform.system().lower()
    if system == 'windows':
        build_windows()
        print("\nBuild complete: dist/TelegramMessenger.exe")
    elif system == 'linux':
        build_linux()
        print("\nBuild complete: dist/telegram-messenger")
    else:
        print(f"Unsupported OS: {system}")
        sys.exit(1)

if __name__ == "__main__":
    main()