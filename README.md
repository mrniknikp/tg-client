# Telegram Messenger

Professional cross-platform desktop messenger built with PyQt5 and Telethon, featuring real-time chat updates, beautiful UI, and Windows native notifications.

## 🆕 New: Background Service for 24/7 Message Sync

Now you can run a background service that captures ALL messages even when the GUI is closed!

### Quick Start

**Option 1: Background Service (Recommended)**
```bash
python background_service.py
```
- Runs 24/7 in the background
- Saves ALL incoming/outgoing messages to database
- Works independently of GUI
- Press Ctrl+C to stop

**Option 2: GUI Application**
```bash
python main.py
```
- Beautiful Telegram-like interface
- Loads history from database on startup
- Fetches up to 500 messages per chat from Telegram
- All new messages saved to database

## How It Works

1. **Background service** runs constantly and saves every message to `chat_history.db`
2. **GUI app** loads all messages from database on startup
3. When you open a chat, GUI fetches additional history from Telegram (up to 500 messages)
4. New messages are duplicated to database for persistence

## Benefits

✅ Messages captured 24/7 even when GUI is off
✅ Full history available immediately on app launch
✅ No message loss
✅ Fast GUI performance (reads from local DB)
✅ Multiple clients can share the same database

---

## Features

- 💬 **Real-time messaging** - Send and receive text messages instantly
- 📎 **Media support** - Share photos, documents, and files
- 💾 **Local history** - All chats saved in SQLite database
- 🔔 **Native notifications** - Windows Toast notifications via PowerShell (fallback to plyer)
- 📱 **Beautiful UI** - Modern Telegram-like interface with avatars and message bubbles
- ⚡ **Live updates** - Chat list refreshes every 0.5 seconds with flood wait protection
- 🌐 **MTProto proxy** - Built-in proxy support for unrestricted access
- 🖥️ **Cross-platform** - Works on Windows and Linux
- 🔄 **Smart reconnection** - Automatic handling of AuthRestartError and connection issues

## Screenshots

The application features:
- Left panel with chat list showing last message preview and unread counters
- Right panel with message history in bubble style (like Telegram)
- Avatar circles with first letter of sender name
- Incoming messages (left, white) and outgoing messages (right, blue)
- Message timestamps
- File attachment button
- Beautiful header with "Chats" and current chat title

## Setup

### 1. Get API Credentials

Obtain your API ID and API Hash from [my.telegram.org](https://my.telegram.org):
1. Login with your phone number
2. Go to "API development tools"
3. Create a new application
4. Copy your `API_ID` and `API_HASH`

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**For Windows users:** Make sure `pywin32` is installed for native notifications:
```bash
pip install pywin32
```

### 3. Configure Environment

Create a `.env` file in the project root:

```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
```

Or set environment variables directly.

### 4. Run the Application

```bash
python main.py
```

### 5. Login

1. Enter your phone number in international format (e.g., `+71234567890`)
2. Enter the verification code from Telegram
3. If you have 2FA enabled, enter your password
4. Enjoy chatting!

## Project Structure

```
telegram-messenger/
├── main.py              # Application entry point
├── chat_client.py       # Main UI and business logic (~700 lines)
├── telegram_client.py   # Telethon wrapper for Telegram API
├── database.py          # SQLite database manager
├── requirements.txt     # Python dependencies
├── README.md           # This file
└── media/              # Downloaded media files
```

## Key Features Explained

### Real-time Updates with Flood Protection
- Chat list refreshes every 0.5 seconds
- Limited to 50 dialogs to reduce API load
- Automatic flood wait detection and backoff
- Only updates UI when data changes (optimization)

### Background Message Processing
- Dedicated `MessageWorker` QThread for message handling
- Prevents UI freezing during heavy operations
- Message deduplication using ID tracking
- Queue-based processing for smooth UX

### Native Notifications
- Primary: PowerShell-based Windows Toast API (no COM dependencies)
- Fallback: plyer library for cross-platform support
- Graceful degradation: logs notification if all methods fail
- Shows sender name and message preview

### Beautiful UI Design
- Modern color scheme (#3390ec - official Telegram blue)
- Rounded message bubbles with subtle shadows
- Avatar circles with sender initials
- Smooth scrolling with custom scrollbars
- Responsive splitter layout
- Professional typography (Segoe UI font)

### Robust Error Handling
- AuthRestartError: automatic reconnection and re-authentication
- PhoneCodeInvalidError: graceful retry with code re-entry
- PasswordHashInvalidError: secure password retry loop
- Connection errors: automatic retry with exponential backoff

## Troubleshooting

### AuthRestartError
This is normal during login. The app automatically handles reconnection and will prompt for code again if needed.

### No Notifications on Windows
The app uses PowerShell for notifications (no extra dependencies needed). If it fails, it falls back to plyer or logs the notification.

To ensure best notification experience:
1. Make sure Windows notifications are enabled in Settings
2. Install pywin32 as additional fallback: `pip install pywin32`

### Connection Issues / Flood Wait
The app has built-in flood wait protection:
- Limits dialog fetches to 50 items
- Detects flood wait errors automatically
- Increases retry delay when flood detected
- Caches dialogs to avoid unnecessary API calls

If you see "Sleeping for Xs on GetDialogsRequest flood wait":
- This is Telegram's rate limiting, not an error
- The app automatically waits and retries
- Initial sync may take longer due to rate limits

### First Login Takes Long
- Normal behavior due to Telegram's security measures
- AuthRestartError may occur multiple times
- Be patient and enter codes promptly
- The app will reconnect automatically

## Architecture Highlights

### Thread Safety
- Telegram client runs in dedicated QThread
- UI updates via Qt signals/slots
- Message queue prevents race conditions
- Database operations are synchronous but fast

### Database Schema
- Users table: stores contact information
- Messages table: full chat history with media references
- Unread counters: per-chat tracking
- Automatic cleanup and indexing

### Performance Optimizations
- Dialog caching to reduce API calls
- Message ID deduplication (last 1000 IDs)
- Conditional UI updates (only on changes)
- Async/await for all network operations

## License

MIT License - feel free to use and modify!

## Credits

- [Telethon](https://github.com/LonamiWebs/Telethon) - Telegram client library
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) - GUI framework
- [plyer](https://github.com/kivy/plyer) - Cross-platform notifications
- PowerShell Windows Runtime - Native toast notifications