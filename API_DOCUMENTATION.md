# API Documentation

This document provides comprehensive API documentation for all modules in the Discord Selfbot Logger.

## Table of Contents

- [Configuration Module](#configuration-module)
- [Rate Limiter Module](#rate-limiter-module)
- [Security Module](#security-module)
- [Async Optimizer Module](#async-optimizer-module)
- [Async Wrapper Module](#async-wrapper-module)
- [Performance Monitor Module](#performance-monitor-module)
- [Main Application](#main-application)

## Configuration Module

**File**: `config.py`

### Class: Config

Manages application configuration with validation and environment variable support.

#### Methods

##### `__init__(self, config_file: str = '.env')`
Initializes the configuration manager.

**Parameters**:
- `config_file` (str): Path to the configuration file

##### `get(self, key: str, default: Any = None) -> Any`
Retrieves a configuration value.

**Parameters**:
- `key` (str): Configuration key
- `default` (Any): Default value if key not found

**Returns**: Configuration value or default

##### `get_all_config(self) -> Dict[str, Any]`
Retrieves all configuration values.

**Returns**: Dictionary of all configuration values

##### `validate_config(self) -> bool`
Validates the current configuration.

**Returns**: True if configuration is valid

#### Configuration Keys

| Key | Type | Description | Default |
|-----|------|-------------|----------|
| `DISCORD_TOKEN` | str | Discord user token | Required |
| `WEBHOOK_URL` | str | Discord webhook URL | Required |
| `ATTACH_DIR` | str | Attachments directory | `attachments` |
| `LOG_LEVEL` | str | Logging level | `INFO` |
| `LOG_FILE` | str | Log file path | `discord_logger.log` |
| `MAX_CONCURRENT_REQUESTS` | int | Max concurrent requests | `10` |
| `REQUEST_TIMEOUT` | int | Request timeout (seconds) | `30` |
| `ATTACHMENT_SIZE_LIMIT` | int | Max attachment size (bytes) | `52428800` |

## Rate Limiter Module

**File**: `rate_limiter.py`

### Class: RateLimiter

Implements token bucket rate limiting for different operation types.

#### Methods

##### `__init__(self, rate_configs: Dict[RateLimitType, RateConfig] = None)`
Initializes the rate limiter.

**Parameters**:
- `rate_configs` (Dict): Rate configuration for different operation types

##### `can_proceed(self, limit_type: RateLimitType) -> bool`
Checks if an operation can proceed.

**Parameters**:
- `limit_type` (RateLimitType): Type of operation

**Returns**: True if operation can proceed

##### `wait_for(self, limit_type: RateLimitType, timeout: float = 60.0) -> bool`
Waits for rate limit to allow operation.

**Parameters**:
- `limit_type` (RateLimitType): Type of operation
- `timeout` (float): Maximum wait time in seconds

**Returns**: True if operation can proceed within timeout

##### `trigger_cooldown(self, limit_type: RateLimitType, duration: int)`
Triggers a cooldown period for an operation type.

**Parameters**:
- `limit_type` (RateLimitType): Type of operation
- `duration` (int): Cooldown duration in seconds

### Enum: RateLimitType

Defines different types of rate-limited operations:

- `WEBHOOK`: Webhook requests
- `API_REQUEST`: General API requests
- `MESSAGE_SEND`: Message sending
- `FILE_DOWNLOAD`: File downloads
- `USER_ACTION`: User actions

### Convenience Functions

##### `wait_for_webhook(timeout: float = 60.0) -> bool`
Waits for webhook rate limit.

##### `wait_for_api(timeout: float = 60.0) -> bool`
Waits for API rate limit.

##### `wait_for_download(timeout: float = 60.0) -> bool`
Waits for download rate limit.

## Security Module

**File**: `security.py`

### Class: TokenValidator

Validates Discord tokens for security and authenticity.

#### Methods

##### `validate_token(self, token: str) -> Tuple[bool, Optional[str]]`
Validates a Discord token.

**Parameters**:
- `token` (str): Discord token to validate

**Returns**: Tuple of (is_valid, error_message)

##### `extract_user_id(self, token: str) -> Optional[str]`
Extracts user ID from token.

**Parameters**:
- `token` (str): Discord token

**Returns**: User ID or None if invalid

### Class: WebhookValidator

Validates Discord webhook URLs.

#### Methods

##### `validate_webhook(self, webhook_url: str) -> Tuple[bool, Optional[str]]`
Validates a webhook URL.

**Parameters**:
- `webhook_url` (str): Webhook URL to validate

**Returns**: Tuple of (is_valid, error_message)

### Class: InputSanitizer

Sanitizes user inputs for security.

#### Methods

##### `sanitize_content(self, content: str) -> str`
Sanitizes message content.

**Parameters**:
- `content` (str): Content to sanitize

**Returns**: Sanitized content

##### `sanitize_filename(self, filename: str) -> str`
Sanitizes file names.

**Parameters**:
- `filename` (str): Filename to sanitize

**Returns**: Safe filename

##### `validate_url(self, url: str) -> bool`
Validates URLs for security.

**Parameters**:
- `url` (str): URL to validate

**Returns**: True if URL is safe

### Class: SecurityMonitor

Monitors security events and suspicious activity.

#### Methods

##### `log_message_event(self, event_data: Dict[str, Any])`
Logs message-related security events.

**Parameters**:
- `event_data` (Dict): Event data to log

##### `log_authentication_event(self, event_data: Dict[str, Any])`
Logs authentication-related events.

**Parameters**:
- `event_data` (Dict): Event data to log

### Functions

##### `log_security_event(event_type: str, event_data: Dict[str, Any])`
Logs a security event.

**Parameters**:
- `event_type` (str): Type of security event
- `event_data` (Dict): Event data

## Async Optimizer Module

**File**: `async_optimizer.py`

### Class: AsyncConfig

Configuration for async operations.

#### Attributes

- `max_concurrent_requests` (int): Maximum concurrent requests
- `request_timeout` (float): Request timeout in seconds
- `max_file_size` (int): Maximum file size for downloads
- `enable_batch_processing` (bool): Enable batch processing
- `connection_pool_size` (int): HTTP connection pool size

### Class: AsyncWebhookSender

Async webhook sender with connection pooling.

#### Methods

##### `async send_embed(self, webhook_url: str, title: str, description: str, ...) -> bool`
Sends an embed asynchronously.

**Parameters**:
- `webhook_url` (str): Webhook URL
- `title` (str): Embed title
- `description` (str): Embed description
- Additional optional parameters for author, image, color

**Returns**: True if sent successfully

### Class: AsyncFileDownloader

Async file downloader with progress tracking.

#### Methods

##### `async download_file(self, url: str, filepath: Path, max_size: int = None) -> Tuple[bool, Optional[str]]`
Downloads a file asynchronously.

**Parameters**:
- `url` (str): File URL
- `filepath` (Path): Local file path
- `max_size` (int): Maximum file size

**Returns**: Tuple of (success, error_message)

### Class: AsyncMessageProcessor

Async message processor for batch operations.

#### Methods

##### `async process_message(self, message_data: Dict[str, Any], config: Dict[str, Any]) -> bool`
Processes a message asynchronously.

**Parameters**:
- `message_data` (Dict): Message data
- `config` (Dict): Configuration

**Returns**: True if processed successfully

### Convenience Functions

##### `async async_send_embed(...) -> bool`
Sends an embed using the global async sender.

##### `async async_download_attachment(...) -> Tuple[bool, Optional[str]]`
Downloads an attachment using the global async downloader.

##### `async async_process_message(...) -> bool`
Processes a message using the global async processor.

## Async Wrapper Module

**File**: `async_wrapper.py`

### Class: AsyncEventLoop

Manages the async event loop for Discord events.

#### Methods

##### `start(self)`
Starts the async event loop in a separate thread.

##### `stop(self)`
Stops the async event loop.

##### `run_async(self, coro)`
Schedules a coroutine to run in the async loop.

**Parameters**:
- `coro`: Coroutine to run

**Returns**: Future object

##### `run_async_nowait(self, coro)`
Schedules a coroutine without waiting for result.

**Parameters**:
- `coro`: Coroutine to run

### Class: AsyncDiscordWrapper

Wrapper for Discord event handlers with async optimization.

#### Methods

##### `send_embed_async(...) -> bool`
Sends embed asynchronously (non-blocking).

##### `download_attachment_async(...) -> bool`
Downloads attachment asynchronously (non-blocking).

##### `process_message_async(...) -> bool`
Processes message asynchronously (non-blocking).

##### `get_stats(self) -> Dict[str, int]`
Gets processing statistics.

**Returns**: Dictionary of statistics

### Functions

##### `get_async_wrapper(config: Dict[str, Any] = None) -> AsyncDiscordWrapper`
Gets or creates the global async wrapper instance.

##### `cleanup_async_wrapper()`
Cleans up the global async wrapper.

## Performance Monitor Module

**File**: `performance_monitor.py`

### Class: PerformanceMetric

Represents an individual performance metric.

#### Attributes

- `name` (str): Operation name
- `start_time` (float): Start timestamp
- `end_time` (float): End timestamp
- `duration` (float): Operation duration
- `success` (bool): Whether operation succeeded
- `error` (str): Error message if failed
- `metadata` (Dict): Additional metadata

### Class: PerformanceStats

Aggregated performance statistics.

#### Attributes

- `total_operations` (int): Total number of operations
- `successful_operations` (int): Number of successful operations
- `failed_operations` (int): Number of failed operations
- `avg_duration` (float): Average operation duration
- `operations_per_second` (float): Operations per second

### Class: PerformanceMonitor

Performance monitoring and metrics collection.

#### Methods

##### `start_operation(self, operation_name: str, metadata: Dict = None) -> str`
Starts tracking a performance operation.

**Parameters**:
- `operation_name` (str): Name of the operation
- `metadata` (Dict): Additional metadata

**Returns**: Unique operation ID

##### `finish_operation(self, operation_id: str, success: bool = True, error: str = None)`
Finishes tracking a performance operation.

**Parameters**:
- `operation_id` (str): Operation ID from start_operation
- `success` (bool): Whether operation succeeded
- `error` (str): Error message if failed

##### `get_performance_summary(self) -> Dict[str, Any]`
Gets comprehensive performance summary.

**Returns**: Dictionary containing performance summary

##### `save_metrics(self, filepath: Path)`
Saves metrics to a JSON file.

**Parameters**:
- `filepath` (Path): Path to save metrics

### Decorators

##### `@monitor_performance(operation_name: str = None, include_args: bool = False)`
Decorator to monitor function performance.

**Parameters**:
- `operation_name` (str): Custom operation name
- `include_args` (bool): Include function arguments in metadata

### Context Manager

##### `performance_timer(operation_name: str, metadata: Dict = None)`
Context manager for timing operations.

**Usage**:
```python
with performance_timer("my_operation"):
    # Your code here
    pass
```

## Main Application

**File**: `main.py`

### Functions

##### `send_embed(webhook_url: str, title: str, description: str, image_url: str = None) -> bool`
Sends an embed to Discord webhook with async optimization.

**Parameters**:
- `webhook_url` (str): Discord webhook URL
- `title` (str): Embed title
- `description` (str): Embed description
- `image_url` (str): Optional image URL

**Returns**: True if sent successfully

##### `download_attachment(url: str, filename: str) -> bool`
Downloads an attachment with async optimization.

**Parameters**:
- `url` (str): File URL
- `filename` (str): Local filename

**Returns**: True if downloaded successfully

##### `on_message(resp)`
Handles incoming Discord messages with async optimization.

**Parameters**:
- `resp`: Discord message response object

##### `print_performance_stats()`
Prints current performance statistics.

### Event Handlers

The application registers several Discord event handlers:

- `on_message`: Processes incoming messages
- `on_message_delete`: Handles message deletions
- `on_ready`: Handles connection ready events

## Error Handling

All modules implement comprehensive error handling:

- **Graceful Degradation**: Async operations fall back to sync if needed
- **Retry Logic**: Automatic retries for transient failures
- **Rate Limit Handling**: Automatic handling of Discord rate limits
- **Logging**: Detailed error logging for debugging

## Performance Considerations

- **Async Operations**: Non-blocking I/O for better performance
- **Connection Pooling**: Reuses HTTP connections
- **Rate Limiting**: Prevents API abuse while maximizing throughput
- **Memory Management**: Efficient memory usage with configurable limits
- **Monitoring**: Real-time performance tracking

## Security Features

- **Input Validation**: All inputs are validated and sanitized
- **Token Security**: Secure token handling and validation
- **URL Validation**: Prevents malicious URL access
- **Audit Logging**: Complete audit trail of security events
- **Encryption**: Sensitive data encrypted at rest

---

For more detailed examples and usage patterns, see the main README.md file.