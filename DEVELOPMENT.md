# Development Guide

This guide provides information for developers working on the Discord Selfbot Logger project.

## Table of Contents

- [Project Structure](#project-structure)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing](#testing)
- [Performance Optimization](#performance-optimization)
- [Security Considerations](#security-considerations)
- [Contributing](#contributing)
- [Debugging](#debugging)

## Project Structure

```
Discord selfbot logger/
├── main.py                    # Main application entry point
├── config.py                  # Configuration management
├── rate_limiter.py           # Rate limiting implementation
├── security.py               # Security utilities and validation
├── async_optimizer.py        # Async optimization components
├── async_wrapper.py          # Async wrapper for Discord events
├── performance_monitor.py    # Performance monitoring and metrics
├── requirements.txt          # Python dependencies
├── .env.example             # Environment variables template
├── README.md                # Project documentation
├── API_DOCUMENTATION.md     # API reference
├── DEVELOPMENT.md           # This file
├── backend/                 # Backend components
│   ├── main.py             # Backend entry point
│   ├── requirements.txt    # Backend dependencies
│   └── static/             # Static files
├── attachments/            # Downloaded attachments
└── logs/                   # Application logs
```

## Development Setup

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Git
- Discord account with developer access

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd "Discord selfbot logger"
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Install backend dependencies** (if working on backend):
   ```bash
   cd backend
   pip install -r requirements.txt
   cd ..
   ```

### Development Environment

#### Recommended IDE Settings

**VS Code**:
```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.formatting.provider": "black",
    "python.sortImports.args": ["--profile", "black"],
    "editor.formatOnSave": true
}
```

#### Git Hooks

Set up pre-commit hooks for code quality:

```bash
pip install pre-commit
pre-commit install
```

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 22.3.0
    hooks:
      - id: black
  - repo: https://github.com/pycqa/isort
    rev: 5.10.1
    hooks:
      - id: isort
  - repo: https://github.com/pycqa/flake8
    rev: 4.0.1
    hooks:
      - id: flake8
```

## Architecture Overview

### Core Components

#### 1. Configuration Management (`config.py`)
- Centralized configuration handling
- Environment variable support
- Validation and type checking
- Hot-reload capabilities

#### 2. Rate Limiting (`rate_limiter.py`)
- Token bucket algorithm implementation
- Multiple rate limit types
- Cooldown management
- Thread-safe operations

#### 3. Security (`security.py`)
- Input validation and sanitization
- Token and webhook validation
- Security event logging
- Threat detection

#### 4. Async Optimization (`async_optimizer.py`)
- Async HTTP operations
- Connection pooling
- Batch processing
- Performance optimization

#### 5. Async Wrapper (`async_wrapper.py`)
- Event loop management
- Non-blocking Discord operations
- Backward compatibility
- Error handling

#### 6. Performance Monitoring (`performance_monitor.py`)
- Real-time metrics collection
- Performance analysis
- Bottleneck identification
- Statistics reporting

### Data Flow

```
Discord Event → Security Validation → Rate Limiting → Async Processing → Performance Monitoring
                                                   ↓
                                              Webhook/File Operations
```

### Threading Model

- **Main Thread**: Discord event handling (discum library)
- **Async Thread**: HTTP operations and file I/O
- **Monitor Thread**: Performance metrics collection
- **Rate Limiter**: Thread-safe token bucket operations

## Code Style Guidelines

### Python Style

Follow PEP 8 with these specific guidelines:

#### Imports
```python
# Standard library imports
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Third-party imports
import aiohttp
import discum

# Local imports
from config import Config
from rate_limiter import RateLimiter
```

#### Function Definitions
```python
def function_name(
    param1: str,
    param2: int,
    param3: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str]]:
    """Brief description of function.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        param3: Description of param3
        
    Returns:
        Tuple of (success, error_message)
        
    Raises:
        ValueError: If param1 is invalid
    """
    pass
```

#### Class Definitions
```python
class ClassName:
    """Brief description of class.
    
    Attributes:
        attribute1: Description of attribute1
        attribute2: Description of attribute2
    """
    
    def __init__(self, param1: str, param2: int = 10):
        """Initialize the class.
        
        Args:
            param1: Description of param1
            param2: Description of param2
        """
        self.attribute1 = param1
        self.attribute2 = param2
```

#### Error Handling
```python
try:
    result = risky_operation()
except SpecificException as e:
    logger.error(f"Specific error occurred: {e}")
    return False, str(e)
except Exception as e:
    logger.exception("Unexpected error occurred")
    return False, "Internal error"
else:
    logger.info("Operation completed successfully")
    return True, None
```

#### Async Code
```python
async def async_function(param: str) -> bool:
    """Async function example."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return True
    except asyncio.TimeoutError:
        logger.warning("Request timed out")
        return False
    except Exception as e:
        logger.error(f"Async operation failed: {e}")
        return False
```

### Logging Guidelines

```python
import logging

# Use module-level logger
logger = logging.getLogger(__name__)

# Log levels usage:
logger.debug("Detailed debugging information")
logger.info("General information")
logger.warning("Warning about potential issues")
logger.error("Error that doesn't stop execution")
logger.critical("Critical error that may stop execution")

# Include context in log messages
logger.info(f"Processing message from user {user_id} in channel {channel_id}")

# Use structured logging for important events
logger.info(
    "Message processed",
    extra={
        "user_id": user_id,
        "channel_id": channel_id,
        "message_length": len(content),
        "processing_time": duration
    }
)
```

## Testing

### Unit Testing

Create tests in `tests/` directory:

```python
import unittest
from unittest.mock import Mock, patch

from config import Config

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.config = Config()
    
    def test_get_existing_key(self):
        """Test getting an existing configuration key."""
        with patch.dict('os.environ', {'TEST_KEY': 'test_value'}):
            result = self.config.get('TEST_KEY')
            self.assertEqual(result, 'test_value')
    
    def test_get_nonexistent_key(self):
        """Test getting a non-existent key returns default."""
        result = self.config.get('NONEXISTENT_KEY', 'default')
        self.assertEqual(result, 'default')

if __name__ == '__main__':
    unittest.main()
```

### Integration Testing

```python
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from async_optimizer import AsyncWebhookSender

class TestAsyncWebhookSender(unittest.TestCase):
    def setUp(self):
        self.sender = AsyncWebhookSender()
    
    @patch('aiohttp.ClientSession.post')
    async def test_send_embed_success(self, mock_post):
        """Test successful embed sending."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await self.sender.send_embed(
            'https://discord.com/api/webhooks/test',
            'Test Title',
            'Test Description'
        )
        
        self.assertTrue(result)
        mock_post.assert_called_once()
    
    def test_async_send_embed(self):
        """Test async embed sending."""
        asyncio.run(self.test_send_embed_success())
```

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest --cov=. tests/

# Run specific test file
python -m pytest tests/test_config.py

# Run with verbose output
python -m pytest -v tests/
```

## Performance Optimization

### Profiling

```python
import cProfile
import pstats
from performance_monitor import monitor_performance

# Profile a function
@monitor_performance("critical_function")
def critical_function():
    # Your code here
    pass

# Manual profiling
def profile_function():
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Code to profile
    critical_function()
    
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)  # Top 10 functions
```

### Memory Optimization

```python
import tracemalloc
from memory_profiler import profile

# Track memory usage
tracemalloc.start()

# Your code here

current, peak = tracemalloc.get_traced_memory()
print(f"Current memory usage: {current / 1024 / 1024:.1f} MB")
print(f"Peak memory usage: {peak / 1024 / 1024:.1f} MB")
tracemalloc.stop()

# Profile memory usage of functions
@profile
def memory_intensive_function():
    # Your code here
    pass
```

### Async Optimization Tips

1. **Use connection pooling**:
   ```python
   # Good
   async with aiohttp.ClientSession() as session:
       for url in urls:
           async with session.get(url) as response:
               data = await response.json()
   
   # Bad - creates new connection for each request
   for url in urls:
       async with aiohttp.ClientSession() as session:
           async with session.get(url) as response:
               data = await response.json()
   ```

2. **Batch operations**:
   ```python
   # Process multiple items concurrently
   tasks = [process_item(item) for item in items]
   results = await asyncio.gather(*tasks, return_exceptions=True)
   ```

3. **Use semaphores for concurrency control**:
   ```python
   semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent operations
   
   async def limited_operation(item):
       async with semaphore:
           return await process_item(item)
   ```

## Security Considerations

### Input Validation

```python
from security import InputSanitizer

sanitizer = InputSanitizer()

# Always validate and sanitize inputs
def process_user_input(user_content: str) -> str:
    # Validate input
    if not user_content or len(user_content) > 2000:
        raise ValueError("Invalid content length")
    
    # Sanitize content
    safe_content = sanitizer.sanitize_content(user_content)
    
    return safe_content
```

### Token Security

```python
# Never log tokens
logger.info(f"Using token: {'*' * len(token)}")

# Validate tokens before use
from security import TokenValidator

validator = TokenValidator()
is_valid, error = validator.validate_token(token)
if not is_valid:
    raise ValueError(f"Invalid token: {error}")
```

### Secure File Handling

```python
from pathlib import Path
from security import InputSanitizer

def safe_file_download(url: str, filename: str) -> Path:
    sanitizer = InputSanitizer()
    
    # Sanitize filename
    safe_filename = sanitizer.sanitize_filename(filename)
    
    # Ensure file is within allowed directory
    base_dir = Path("attachments")
    file_path = base_dir / safe_filename
    
    # Prevent directory traversal
    if not str(file_path.resolve()).startswith(str(base_dir.resolve())):
        raise ValueError("Invalid file path")
    
    return file_path
```

## Contributing

### Pull Request Process

1. **Fork the repository**
2. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes**
4. **Add tests** for new functionality
5. **Run tests** and ensure they pass
6. **Update documentation** if needed
7. **Commit your changes**:
   ```bash
   git commit -m "feat: add new feature description"
   ```
8. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```
9. **Create a pull request**

### Commit Message Format

Use conventional commits:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:
```
feat(async): add connection pooling for webhook requests
fix(security): prevent directory traversal in file downloads
docs(api): update API documentation for rate limiter
```

### Code Review Guidelines

**For Authors**:
- Keep PRs focused and small
- Write clear commit messages
- Add tests for new features
- Update documentation
- Respond to feedback promptly

**For Reviewers**:
- Check for security issues
- Verify test coverage
- Review performance implications
- Ensure code follows style guidelines
- Test the changes locally

## Debugging

### Logging Configuration

```python
import logging

# Development logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler()
    ]
)

# Disable noisy third-party loggers
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('discord').setLevel(logging.INFO)
```

### Debug Tools

```python
# Use pdb for interactive debugging
import pdb

def problematic_function():
    # Set breakpoint
    pdb.set_trace()
    # Your code here
    pass

# Use logging for async debugging
async def async_function():
    logger.debug("Starting async operation")
    try:
        result = await some_operation()
        logger.debug(f"Operation result: {result}")
        return result
    except Exception as e:
        logger.exception("Async operation failed")
        raise
```

### Performance Debugging

```python
from performance_monitor import performance_timer

# Time critical sections
with performance_timer("critical_section"):
    # Your code here
    pass

# Monitor function performance
@monitor_performance("function_name", include_args=True)
def monitored_function(arg1, arg2):
    # Your code here
    pass
```

### Common Issues and Solutions

#### Issue: Rate Limiting
```python
# Check rate limiter status
from rate_limiter import get_rate_limiter

rate_limiter = get_rate_limiter()
if not rate_limiter.can_proceed(RateLimitType.WEBHOOK):
    logger.warning("Rate limited, waiting...")
    rate_limiter.wait_for(RateLimitType.WEBHOOK)
```

#### Issue: Async Event Loop
```python
# Check if event loop is running
import asyncio

try:
    loop = asyncio.get_running_loop()
    logger.info(f"Event loop is running: {loop}")
except RuntimeError:
    logger.warning("No event loop running")
```

#### Issue: Memory Leaks
```python
# Monitor object references
import gc
import weakref

# Track object lifecycle
class TrackedObject:
    _instances = weakref.WeakSet()
    
    def __init__(self):
        self._instances.add(self)
    
    @classmethod
    def get_instance_count(cls):
        return len(cls._instances)

# Force garbage collection
gc.collect()
print(f"Active objects: {TrackedObject.get_instance_count()}")
```

---

For more information, see the [API Documentation](API_DOCUMENTATION.md) and [README](README.md).