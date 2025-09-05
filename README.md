# Discord Selfbot Logger

A comprehensive Discord selfbot logger with advanced features including async optimization, rate limiting, security monitoring, and performance tracking.

## Features

- **Message Logging**: Automatically logs all Discord messages to webhooks
- **Attachment Handling**: Downloads and saves message attachments
- **Async Optimization**: High-performance async processing for better throughput
- **Rate Limiting**: Intelligent rate limiting to prevent API abuse and bans
- **Security Monitoring**: Advanced security features with input sanitization
- **Performance Tracking**: Built-in performance monitoring and metrics
- **Configuration Management**: Flexible configuration with validation
- **Error Handling**: Comprehensive error handling and logging
- **Multi-Account Support**: GUI for managing multiple Discord accounts

## Installation

### Prerequisites

- Python 3.8 or higher
- Discord account with developer access
- Discord webhook URL for logging

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd "Discord selfbot logger"
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   Create a `.env` file in the root directory:
   ```env
   DISCORD_TOKEN=your_discord_token_here
   WEBHOOK_URL=your_webhook_url_here
   ATTACH_DIR=attachments
   LOG_LEVEL=INFO
   ```

4. **Run the application**:
   ```bash
   python main.py
   ```

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DISCORD_TOKEN` | Your Discord user token | - | Yes |
| `WEBHOOK_URL` | Discord webhook URL for logging | - | Yes |
| `ATTACH_DIR` | Directory for saving attachments | `attachments` | No |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` | No |
| `LOG_FILE` | Log file path | `discord_logger.log` | No |
| `MAX_CONCURRENT_REQUESTS` | Max concurrent async requests | `10` | No |
| `REQUEST_TIMEOUT` | Request timeout in seconds | `30` | No |
| `ATTACHMENT_SIZE_LIMIT` | Max attachment size in bytes | `52428800` (50MB) | No |
| `ENABLE_BATCH_PROCESSING` | Enable batch processing | `true` | No |

### Advanced Configuration

The application uses a sophisticated configuration system with validation:

- **Token Validation**: Automatically validates Discord tokens
- **Webhook Validation**: Ensures webhook URLs are valid and accessible
- **Security Settings**: Configurable security monitoring and input sanitization
- **Rate Limiting**: Customizable rate limits for different operation types

## Usage

### Basic Usage

1. **Start the logger**:
   ```bash
   python main.py
   ```

2. **Monitor logs**: Check the console output and log files for activity

3. **View performance stats**: Performance statistics are displayed on exit

### Multi-Account GUI

For managing multiple Discord accounts:

```bash
python backend/multi_account_gui.py
```

The GUI provides:
- Account management interface
- Real-time logging status
- Configuration management
- Performance monitoring

### Delete Commands

The logger supports delete commands for message management:

- `$delete <count>`: Delete the last N messages
- `$delete all`: Delete all cached messages

## Architecture

### Core Components

1. **Main Logger** (`main.py`): Primary Discord event handler
2. **Configuration** (`config.py`): Configuration management with validation
3. **Rate Limiter** (`rate_limiter.py`): Token bucket rate limiting system
4. **Security** (`security.py`): Security monitoring and input sanitization
5. **Async Optimizer** (`async_optimizer.py`): Async processing optimization
6. **Performance Monitor** (`performance_monitor.py`): Performance tracking and metrics

### Async Architecture

The application uses a hybrid async/sync architecture:

- **Async Processing**: Non-blocking operations for webhooks and downloads
- **Sync Fallback**: Automatic fallback to synchronous processing if async fails
- **Performance Monitoring**: Tracks async vs sync performance benefits

### Security Features

- **Token Validation**: Validates Discord tokens before use
- **Input Sanitization**: Sanitizes all user inputs and file names
- **URL Validation**: Validates attachment URLs for security
- **Security Monitoring**: Logs security events and suspicious activity
- **Secure Storage**: Encrypted storage for sensitive configuration data

## Performance

### Optimization Features

- **Async Processing**: Up to 10x performance improvement for I/O operations
- **Rate Limiting**: Prevents API abuse while maximizing throughput
- **Batch Processing**: Efficient handling of multiple operations
- **Connection Pooling**: Reuses HTTP connections for better performance
- **Memory Management**: Efficient memory usage with configurable limits

### Monitoring

Built-in performance monitoring provides:

- **Operation Metrics**: Success rates, duration, throughput
- **Real-time Stats**: Live performance statistics
- **Historical Data**: Performance trends over time
- **Error Tracking**: Detailed error analysis and reporting

## Troubleshooting

### Common Issues

1. **Token Invalid**:
   - Ensure your Discord token is correct
   - Check that the token hasn't expired
   - Verify the token has necessary permissions

2. **Webhook Errors**:
   - Verify the webhook URL is correct
   - Check webhook permissions
   - Ensure the webhook channel exists

3. **Rate Limiting**:
   - The application automatically handles rate limits
   - Check logs for rate limit warnings
   - Adjust rate limit settings if needed

4. **Performance Issues**:
   - Enable async processing for better performance
   - Check performance statistics for bottlenecks
   - Adjust concurrent request limits

### Debug Mode

Enable debug logging for detailed troubleshooting:

```env
LOG_LEVEL=DEBUG
```

### Log Analysis

Check the following log files:

- `discord_logger.log`: Main application logs
- `security.log`: Security events and monitoring
- `performance.log`: Performance metrics and statistics

## Development

### Project Structure

```
Discord selfbot logger/
├── main.py                 # Main application entry point
├── config.py              # Configuration management
├── rate_limiter.py        # Rate limiting system
├── security.py            # Security features
├── async_optimizer.py     # Async optimization
├── async_wrapper.py       # Async wrapper for compatibility
├── performance_monitor.py # Performance monitoring
├── requirements.txt       # Python dependencies
├── .env                   # Environment configuration
├── backend/              # Backend components
│   ├── main.py           # Backend main module
│   ├── multi_account_gui.py # Multi-account GUI
│   └── requirements.txt  # Backend dependencies
└── attachments/          # Downloaded attachments
```

### Adding Features

1. **New Modules**: Follow the existing module structure
2. **Configuration**: Add new config options to `config.py`
3. **Security**: Implement security checks for new features
4. **Performance**: Add performance monitoring for new operations
5. **Documentation**: Update this README and add inline comments

### Testing

The application includes comprehensive error handling and logging for testing:

- **Unit Tests**: Test individual components
- **Integration Tests**: Test component interactions
- **Performance Tests**: Benchmark async vs sync performance
- **Security Tests**: Validate security features

## Security Considerations

### Token Security

- **Never commit tokens**: Use environment variables only
- **Token rotation**: Regularly rotate Discord tokens
- **Access control**: Limit token permissions to minimum required

### Data Protection

- **Encryption**: Sensitive data is encrypted at rest
- **Input validation**: All inputs are validated and sanitized
- **Secure transmission**: HTTPS used for all external requests

### Monitoring

- **Security events**: All security events are logged
- **Anomaly detection**: Unusual activity is flagged
- **Audit trail**: Complete audit trail of all operations

## License

This project is for educational purposes only. Please ensure compliance with Discord's Terms of Service and applicable laws.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests and documentation
5. Submit a pull request

## Support

For issues and questions:

1. Check the troubleshooting section
2. Review the logs for error details
3. Enable debug mode for more information
4. Create an issue with detailed information

---

**Note**: This is a selfbot application. Please ensure you comply with Discord's Terms of Service and use responsibly.