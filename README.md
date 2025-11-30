
# Discord Selfbot Logger

> **⚠️ Educational purposes only. Using selfbots violates Discord's ToS and may result in account termination.**

A comprehensive Discord message logger with web dashboard, multi-account support, and advanced features.

## ✨ Key Features

- 📜 **Message & Attachment Logging** - Automatic logging to webhooks with file downloads
- 🌐 **Web Dashboard** - Real-time monitoring and account management interface
- 👥 **Multi-Account Support** - Switch between multiple Discord accounts seamlessly
- 💾 **Database Persistence** - SQLite database for storing messages, edits, deletions, and attachments
- ⚡ **Performance Optimized** - Async processing with intelligent rate limiting
- 🛡️ **Security Features** - Token encryption, input sanitization, and security monitoring
- 🔔 **Notification System** - Configurable rules for webhooks, email, and desktop notifications
- 📊 **Monitoring & Metrics** - Prometheus-style metrics and alerting system
- 🛠️ **Error Handling** - Retry logic with exponential backoff and circuit breaker pattern
- 🖱️ **Interactive UI** - Right-click menus, favorites, and channel tagging

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Discord account & webhook URL

### Installation

```bash
# Clone and setup
git clone <repository-url>
cd "Discord selfbot logger"
pip install -r requirements.txt

# Configure (copy .env.example to .env and fill in your details)
cp .env.example .env

# Start both services
double-click start_all.bat
# OR
python start_all.py
```

### Dashboard Access
Open http://127.0.0.1:5002 in your browser after starting.

## ⚙️ Configuration

### Option 1: Environment Variables (.env file)

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your Discord token and webhook URLs
```

**Required:**
- `DISCORD_TOKEN` - Your Discord user token
- `WEBHOOK_URL_FRIEND` - Discord webhook for friend events
- `WEBHOOK_URL_MESSAGE` - Discord webhook for message logging
- `WEBHOOK_URL_COMMAND` - Discord webhook for command logging

### Option 2: Multi-Account Configuration (Recommended)

Use the web dashboard to manage multiple accounts. Accounts are stored in `accounts.json` (auto-created) with encrypted token storage.

**Optional Settings:**
- `LOG_LEVEL` - Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `NONE` (default: `INFO`)
- `WEB_HOST` - Dashboard host (default: `127.0.0.1`)
- `WEB_PORT` - Dashboard port (default: `5002`)
- `ATTACHMENT_SIZE_LIMIT` - Max file size in bytes (default: `104857600` = 100MB)
- `MAX_CONCURRENT_DOWNLOADS` - Max parallel downloads (default: `5`)
- `ENABLE_ATTACHMENT_DOWNLOAD` - Enable/disable attachment downloads (default: `true`)

## 🎯 Usage

1. **Start Services**: Use `start_all.bat` (Windows) or `start_all.py`
2. **Access Dashboard**: Navigate to http://127.0.0.1:5002
3. **Manage Accounts**: Add/switch accounts via the web interface
4. **Monitor Activity**: View real-time logs and statistics
5. **Restart Services**: Use the restart button in the dashboard

## 📁 Project Structure

```
Discord-selfbot-logger/
├── main.py                 # Discord client and event handlers
├── config.py               # Configuration and multi-account management
├── security.py             # Token encryption, validation, and security
├── database.py             # SQLite database persistence
├── error_handler.py        # Error handling and retry logic
├── monitoring.py           # Metrics collection and alerting
├── notifications.py        # Notification rules and management
├── rate_limiter.py         # Token bucket rate limiting
├── async_wrapper.py        # Async HTTP operations
├── backend/
│   ├── web_server.py       # Flask dashboard with SocketIO
│   └── templates/          # HTML templates
├── tests/                  # Unit tests
├── requirements.txt        # Python dependencies
└── accounts.json.example   # Account configuration template
```

## 🔧 Development

**Core Components:**
- `main.py` - Discord event handler and message processing
- `backend/web_server.py` - Flask-based dashboard with SocketIO
- `config.py` - Multi-account configuration management with token encryption
- `database.py` - SQLite database with FTS5 full-text search
- `rate_limiter.py` - Token bucket rate limiting system
- `security.py` - Token encryption, validation, and security monitoring
- `error_handler.py` - Retry logic with exponential backoff and circuit breaker
- `monitoring.py` - Prometheus-style metrics and alerting
- `notifications.py` - Configurable notification rules

**Testing:**
```bash
# Run unit tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_config.py
```

**Contributing:**
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

**Disclaimer**: This project is for educational purposes only. Use responsibly and at your own risk.
