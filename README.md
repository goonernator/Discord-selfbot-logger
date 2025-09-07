
# Discord Selfbot Logger

> **⚠️ Educational purposes only. Using selfbots violates Discord's ToS and may result in account termination.**

A comprehensive Discord message logger with web dashboard, multi-account support, and advanced features.

## ✨ Key Features

- 📜 **Message & Attachment Logging** - Automatic logging to webhooks with file downloads
- 🌐 **Web Dashboard** - Real-time monitoring and account management interface
- 👥 **Multi-Account Support** - Switch between multiple Discord accounts seamlessly
- ⚡ **Performance Optimized** - Async processing with intelligent rate limiting
- 🛡️ **Security Features** - Input sanitization and secure token handling
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

**Required Environment Variables:**
- `DISCORD_TOKEN` - Your Discord user token
- `WEBHOOK_URL` - Discord webhook for message logging

**Optional Settings:**
- `ATTACH_DIR` - Attachment storage directory (default: `attachments`)
- `LOG_LEVEL` - Logging verbosity (default: `INFO`)
- `MAX_CONCURRENT_REQUESTS` - Async request limit (default: `10`)
- `ATTACHMENT_SIZE_LIMIT` - Max file size in bytes (default: `52428800`)

## 🎯 Usage

1. **Start Services**: Use `start_all.bat` (Windows) or `start_all.py`
2. **Access Dashboard**: Navigate to http://127.0.0.1:5002
3. **Manage Accounts**: Add/switch accounts via the web interface
4. **Monitor Activity**: View real-time logs and statistics
5. **Restart Services**: Use the restart button in the dashboard

## 🔧 Development

**Core Components:**
- `main.py` - Discord event handler and message processing
- `web_server.py` - Flask-based dashboard with SocketIO
- `config.py` - Multi-account configuration management
- `rate_limiter.py` - Token bucket rate limiting system
- `security.py` - Input sanitization and security monitoring

**Contributing:**
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

---

**Disclaimer**: This project is for educational purposes only. Use responsibly and at your own risk.
