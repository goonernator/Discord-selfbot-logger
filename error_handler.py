"""Error handling utilities for Discord Selfbot Logger.

This module provides consistent error handling patterns including retry logic,
circuit breakers, and better error messages.
"""

import logging
import time
import functools
from typing import Callable, Any, Optional, TypeVar, Tuple, Dict
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')

class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass

class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Time in seconds before attempting to close circuit
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half_open
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit is open
        """
        if self.state == "open":
            if time.time() - (self.last_failure_time or 0) > self.timeout:
                self.state = "half_open"
                logger.info("Circuit breaker transitioning to half-open state")
            else:
                raise CircuitBreakerError("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
                logger.info("Circuit breaker closed after successful call")
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise

def retry_with_backoff(
    func: Callable[..., T],
    config: Optional[RetryConfig] = None,
    exceptions: Tuple[Exception, ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None
) -> Callable[..., T]:
    """Decorator for retrying functions with exponential backoff.
    
    Args:
        func: Function to retry
        config: Retry configuration
        exceptions: Tuple of exceptions to catch and retry
        on_retry: Optional callback called on each retry
        
    Returns:
        Wrapped function with retry logic
    """
    if config is None:
        config = RetryConfig()
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> T:
        last_exception = None
        
        for attempt in range(config.max_attempts):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                
                if attempt == config.max_attempts - 1:
                    logger.error(f"Function {func.__name__} failed after {config.max_attempts} attempts: {e}")
                    raise
                
                # Calculate delay with exponential backoff
                delay = min(
                    config.initial_delay * (config.exponential_base ** attempt),
                    config.max_delay
                )
                
                # Add jitter if enabled
                if config.jitter:
                    import random
                    delay = delay * (0.5 + random.random() * 0.5)
                
                if on_retry:
                    on_retry(attempt + 1, e)
                
                logger.warning(
                    f"Function {func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)
        
        raise last_exception
    
    return wrapper

def handle_error(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    log_full_context: bool = True
) -> str:
    """Handle an error with consistent logging and context.
    
    Args:
        error: Exception that occurred
        context: Additional context dictionary
        severity: Error severity level
        log_full_context: Whether to log full context
        
    Returns:
        User-friendly error message
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    # Build context string
    context_str = ""
    if context:
        context_items = [f"{k}={v}" for k, v in context.items() if not isinstance(v, (dict, list))]
        context_str = f" | Context: {', '.join(context_items)}"
    
    # Log based on severity
    if severity == ErrorSeverity.CRITICAL:
        logger.critical(f"CRITICAL ERROR [{error_type}]: {error_message}{context_str}", exc_info=log_full_context)
    elif severity == ErrorSeverity.HIGH:
        logger.error(f"HIGH SEVERITY ERROR [{error_type}]: {error_message}{context_str}", exc_info=log_full_context)
    elif severity == ErrorSeverity.MEDIUM:
        logger.warning(f"MEDIUM SEVERITY ERROR [{error_type}]: {error_message}{context_str}")
    else:
        logger.info(f"LOW SEVERITY ERROR [{error_type}]: {error_message}{context_str}")
    
    # Return user-friendly message
    user_message = f"An error occurred: {error_type}"
    if error_message and len(error_message) < 100:
        user_message += f" - {error_message}"
    
    return user_message

def safe_execute(
    func: Callable[..., T],
    *args,
    default: Optional[T] = None,
    context: Optional[Dict[str, Any]] = None,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    **kwargs
) -> Optional[T]:
    """Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        *args: Function arguments
        default: Default value to return on error
        context: Additional context for error logging
        severity: Error severity level
        **kwargs: Function keyword arguments
        
    Returns:
        Function result or default value
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        func_name = getattr(func, '__name__', 'unknown')
        handle_error(e, context={**(context or {}), 'function': func_name}, severity=severity)
        return default

class ErrorHandler:
    """Centralized error handler with context management."""
    
    def __init__(self):
        """Initialize error handler."""
        self.error_history: list = []
        self.max_history = 1000
    
    def handle(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        user_message: Optional[str] = None
    ) -> str:
        """Handle an error with full context.
        
        Args:
            error: Exception that occurred
            context: Additional context
            severity: Error severity
            user_message: Optional user-friendly message
            
        Returns:
            User-friendly error message
        """
        error_record = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'severity': severity.value,
            'context': context or {}
        }
        
        self.error_history.append(error_record)
        if len(self.error_history) > self.max_history:
            self.error_history.pop(0)
        
        msg = handle_error(error, context, severity)
        return user_message or msg
    
    def get_recent_errors(self, limit: int = 100, severity: Optional[ErrorSeverity] = None) -> list:
        """Get recent errors.
        
        Args:
            limit: Maximum number of errors to return
            severity: Optional severity filter
            
        Returns:
            List of error records
        """
        errors = self.error_history[-limit:]
        if severity:
            errors = [e for e in errors if e['severity'] == severity.value]
        return errors
    
    def clear_history(self):
        """Clear error history."""
        self.error_history.clear()

# Global error handler instance
_error_handler: Optional[ErrorHandler] = None

def get_error_handler() -> ErrorHandler:
    """Get global error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler

