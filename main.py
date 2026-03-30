#!/usr/bin/env python3
import sys
import os
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication, QMessageBox
from chat_client import ChatApp
from database import Database

load_dotenv()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Messenger")
    
    db = Database()
    
    # Проверяем, есть ли уже аккаунты
    if not db.has_accounts():
        # Первый запуск - создаем диалог для ввода данных аккаунта
        from PyQt5.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout
        
        dialog = QDialog()
        dialog.setWindowTitle("Первая настройка - Добавление аккаунта Telegram")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        intro_label = QLabel("Добро пожаловать! Для начала работы добавьте ваш аккаунт Telegram.\n\n"
                           "Получите API_ID и API_HASH на сайте my.telegram.org:\n"
                           "1. Войдите на my.telegram.org\n"
                           "2. Перейдите в 'API development tools'\n"
                           "3. Создайте новое приложение\n"
                           "4. Скопируйте API_ID и API_HASH")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)
        
        form_layout = QFormLayout()
        
        account_name_input = QLineEdit()
        account_name_input.setPlaceholderText("Например: Личный, Рабочий")
        form_layout.addRow("Название аккаунта:", account_name_input)
        
        api_id_input = QLineEdit()
        api_id_input.setPlaceholderText("Число, например: 1234567")
        form_layout.addRow("API_ID:", api_id_input)
        
        api_hash_input = QLineEdit()
        api_hash_input.setPlaceholderText("Строка, например: abc123def456")
        form_layout.addRow("API_HASH:", api_hash_input)
        
        phone_input = QLineEdit()
        phone_input.setPlaceholderText("+79991234567")
        form_layout.addRow("Номер телефона:", phone_input)
        
        layout.addLayout(form_layout)
        
        btn_layout = QVBoxLayout()
        save_btn = QPushButton("Сохранить и продолжить")
        save_btn.setStyleSheet("QPushButton { background-color: #3390ec; color: white; padding: 10px; border-radius: 5px; font-weight: bold; }")
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
        result = {'success': False}
        
        def on_save():
            account_name = account_name_input.text().strip()
            api_id_str = api_id_input.text().strip()
            api_hash = api_hash_input.text().strip()
            phone = phone_input.text().strip()
            
            if not account_name or not api_id_str or not api_hash or not phone:
                QMessageBox.warning(dialog, "Ошибка", "Заполните все поля!")
                return
            
            try:
                api_id = int(api_id_str)
            except ValueError:
                QMessageBox.warning(dialog, "Ошибка", "API_ID должен быть числом!")
                return
            
            if len(phone) < 10 or not phone.startswith('+'):
                QMessageBox.warning(dialog, "Ошибка", "Введите корректный номер телефона (начинается с +)!")
                return
            
            try:
                session_name = f"session_{account_name.replace(' ', '_').lower()}"
                db.create_account(account_name, api_id, api_hash, phone, session_name)
                db.set_active_account(1)  # Устанавливаем как активный
                result['success'] = True
                dialog.accept()
            except Exception as e:
                QMessageBox.critical(dialog, "Ошибка", f"Не удалось сохранить аккаунт: {e}")
        
        save_btn.clicked.connect(on_save)
        
        if dialog.exec_() != QDialog.Accepted or not result['success']:
            sys.exit(1)
    
    # Получаем активный аккаунт
    active_account = db.get_active_account()
    if not active_account:
        # Если нет активного, берем первый
        accounts = db.get_all_accounts()
        if accounts:
            db.set_active_account(accounts[0]['id'])
            active_account = accounts[0]
        else:
            QMessageBox.critical(None, "Ошибка", "Нет настроенных аккаунтов!")
            sys.exit(1)
    
    try:
        api_id = int(active_account['api_id'])
        api_hash = active_account['api_hash']
    except (ValueError, KeyError) as e:
        QMessageBox.critical(None, "Configuration Error", f"Invalid API credentials in database: {e}")
        sys.exit(1)
    
    window = ChatApp(api_id, api_hash, db)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()