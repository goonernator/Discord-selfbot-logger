
# Discord Selfbot Logger

**A comprehensive Discord selfbot logger with advanced features including async optimization, rate limiting, security monitoring, and performance tracking.**

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Architecture](#architecture)
- [Security](#security)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- 📜 **Message Logging**: Automatically logs all Discord messages to webhooks.
- 📎 **Attachment Handling**: Downloads and saves message attachments.
- ⚡ **Async Optimization**: High-performance async processing for better throughput.
- 🚦 **Rate Limiting**: Intelligent rate limiting to prevent API abuse and bans.
- 🛡️ **Security Monitoring**: Advanced security features with input sanitization.
- 📊 **Performance Tracking**: Built-in performance monitoring and metrics.
- ⚙️ **Configuration Management**: Flexible configuration with validation.
- 🚨 **Error Handling**: Comprehensive error handling and logging.
- 👥 **Multi-Account Support**: GUI for managing multiple Discord accounts.

- 🖱️ **Right-Click Context Menu** **NEW**: Interactive context menu for tagging channels, favoriting users, and managing auto-download settings.
- ⭐ **Favourites Tab** **NEW**: Filter and view events from your favorite users in the dashboard.

---

## Installation

### Prerequisites

- Python 3.8 or higher
- A Discord account
- A Discord webhook URL for logging

### Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/Discord-selfbot-logger.git
    cd "Discord selfbot logger"
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment variables:**

    Create a `.env` file in the root directory and add the following:

    ```env
    DISCORD_TOKEN=your_discord_token_here
    WEBHOOK_URL=your_webhook_url_here
    ```

4.  **Run the application:**
    ```bash
    python main.py
    ```

---

## Configuration

### Environment Variables

| Variable                  | Description                               | Default              | Required |
| ------------------------- | ----------------------------------------- | -------------------- | :------: |
| `DISCORD_TOKEN`           | Your Discord user token.                  | -                    |   Yes    |
| `WEBHOOK_URL`             | Discord webhook URL for logging.          | -                    |   Yes    |
| `ATTACH_DIR`              | Directory for saving attachments.         | `attachments`        |    No    |
| `LOG_LEVEL`               | Logging level (DEBUG, INFO, etc.).        | `INFO`               |    No    |
| `MAX_CONCURRENT_REQUESTS` | Max concurrent async requests.            | `10`                 |    No    |
| `ATTACHMENT_SIZE_LIMIT`   | Max attachment size in bytes (50MB).      | `52428800`           |    No    |

---

## Usage

### Basic Usage

1.  **Start the logger:**
    ```bash
    python main.py
    ```

2.  **Monitor logs:** Check the console output and `discord_logger.log` for activity.

### Multi-Account GUI

For managing multiple Discord accounts, run the GUI:

```bash
python backend/web_server.py
```

The GUI provides:
- An account management interface
- Real-time logging status
- Configuration management

---

## Architecture

### Core Components

- `main.py`: The primary Discord event handler.
- `config.py`: Manages configuration with validation.
- `rate_limiter.py`: A token bucket rate limiting system.
- `security.py`: Handles security monitoring and input sanitization.
- `async_optimizer.py`: Optimizes asynchronous processing.
- `performance_monitor.py`: Tracks performance and metrics.

<details>
  <summary>Project Structure</summary>

  ```
  Discord selfbot logger/
  ├── main.py                 # Main application entry point
  ├── config.py              # Configuration management
  ├── rate_limiter.py        # Rate limiting system
  ├── security.py            # Security features
  ├── async_optimizer.py     # Async optimization
  ├── requirements.txt       # Python dependencies
  ├── .env.example           # Environment configuration example
  ├── backend/
  │   ├── web_server.py      # Backend web server
  │   └── ...
  └── attachments/           # Downloaded attachments
  ```
</details>

---

## Security

- **Token Security**: Tokens are loaded from environment variables and are not hard-coded.
- **Input Sanitization**: All user inputs and file names are sanitized.
- **URL Validation**: Attachment URLs are validated for security.

---

## Contributing

Contributions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create a new feature branch.
3.  Make your changes.
4.  Submit a pull request.

---

## License

This project is for educational purposes only. Using a selfbot is against Discord's ToS and can result in account termination. Use at your own risk.
