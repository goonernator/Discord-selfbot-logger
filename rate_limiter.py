"""Rate limiting module for Discord Selfbot Logger.

This module provides rate limiting functionality to prevent API abuse
and potential Discord account bans by managing request frequencies.
"""

import time
import asyncio
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict, deque
from threading import Lock
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class RateLimitType(Enum):
    """Types of rate limits."""
    WEBHOOK = "webhook"
    API_REQUEST = "api_request"
    MESSAGE_SEND = "message_send"
    FILE_DOWNLOAD = "file_download"
    GATEWAY = "gateway"

@dataclass
class RateLimitConfig:
    """Configuration for a specific rate limit."""
    requests_per_second: float
    burst_limit: int
    cooldown_period: float = 0.0
    
    @property
    def interval(self) -> float:
        """Time interval between requests in seconds."""
        return 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0

class TokenBucket:
    """Token bucket algorithm implementation for rate limiting."""
    
    def __init__(self, config: RateLimitConfig):
        """Initialize token bucket.
        
        Args:
            config: Rate limit configuration
        """
        self.config = config
        self.tokens = float(config.burst_limit)
        self.last_update = time.time()
        self.lock = Lock()
        
    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """Try to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            Tuple of (success, wait_time)
            success: True if tokens were consumed, False if rate limited
            wait_time: Time to wait before next attempt (0 if successful)
        """
        with self.lock:
            now = time.time()
            
            # Add tokens based on time elapsed
            if self.config.requests_per_second > 0:
                elapsed = now - self.last_update
                tokens_to_add = elapsed * self.config.requests_per_second
                self.tokens = min(self.config.burst_limit, self.tokens + tokens_to_add)
            
            self.last_update = now
            
            # Check if we have enough tokens
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0
            else:
                # Calculate wait time
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.config.requests_per_second if self.config.requests_per_second > 0 else 0.0
                return False, wait_time
    
    def reset(self):
        """Reset the token bucket."""
        with self.lock:
            self.tokens = float(self.config.burst_limit)
            self.last_update = time.time()

class RateLimiter:
    """Main rate limiter class managing multiple rate limits."""
    
    # Default rate limit configurations
    DEFAULT_CONFIGS = {
        RateLimitType.WEBHOOK: RateLimitConfig(
            requests_per_second=5.0,  # Discord webhook limit is ~5/sec
            burst_limit=10,
            cooldown_period=1.0
        ),
        RateLimitType.API_REQUEST: RateLimitConfig(
            requests_per_second=50.0,  # Conservative API limit
            burst_limit=100,
            cooldown_period=0.5
        ),
        RateLimitType.MESSAGE_SEND: RateLimitConfig(
            requests_per_second=1.0,   # Very conservative for selfbot
            burst_limit=3,
            cooldown_period=2.0
        ),
        RateLimitType.FILE_DOWNLOAD: RateLimitConfig(
            requests_per_second=2.0,   # File downloads
            burst_limit=5,
            cooldown_period=1.0
        ),
        RateLimitType.GATEWAY: RateLimitConfig(
            requests_per_second=120.0, # Gateway commands
            burst_limit=120,
            cooldown_period=0.1
        )
    }
    
    def __init__(self, custom_configs: Optional[Dict[RateLimitType, RateLimitConfig]] = None):
        """Initialize rate limiter.
        
        Args:
            custom_configs: Custom rate limit configurations
        """
        self.configs = self.DEFAULT_CONFIGS.copy()
        if custom_configs:
            self.configs.update(custom_configs)
            
        self.buckets: Dict[RateLimitType, TokenBucket] = {}
        self.request_history: Dict[RateLimitType, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.cooldown_until: Dict[RateLimitType, float] = defaultdict(float)
        self.lock = Lock()
        
        # Initialize token buckets
        for limit_type, config in self.configs.items():
            self.buckets[limit_type] = TokenBucket(config)
            
        logger.info(f"Rate limiter initialized with {len(self.configs)} limit types")
    
    def can_proceed(self, limit_type: RateLimitType, tokens: int = 1) -> Tuple[bool, float]:
        """Check if a request can proceed without being rate limited.
        
        Args:
            limit_type: Type of rate limit to check
            tokens: Number of tokens required
            
        Returns:
            Tuple of (can_proceed, wait_time)
        """
        if limit_type not in self.buckets:
            logger.warning(f"Unknown rate limit type: {limit_type}")
            return True, 0.0
            
        now = time.time()
        
        # Check cooldown period
        if now < self.cooldown_until[limit_type]:
            wait_time = self.cooldown_until[limit_type] - now
            return False, wait_time
            
        # Check token bucket
        can_proceed, wait_time = self.buckets[limit_type].consume(tokens)
        
        if can_proceed:
            # Record successful request
            self.request_history[limit_type].append(now)
            logger.debug(f"Rate limit check passed for {limit_type.value}")
        else:
            logger.debug(f"Rate limited for {limit_type.value}, wait {wait_time:.2f}s")
            
        return can_proceed, wait_time
    
    def wait_if_needed(self, limit_type: RateLimitType, tokens: int = 1) -> float:
        """Wait if rate limited, then proceed.
        
        Args:
            limit_type: Type of rate limit to check
            tokens: Number of tokens required
            
        Returns:
            Time waited in seconds
        """
        can_proceed, wait_time = self.can_proceed(limit_type, tokens)
        
        if not can_proceed and wait_time > 0:
            logger.info(f"Rate limited, waiting {wait_time:.2f}s for {limit_type.value}")
            time.sleep(wait_time)
            return wait_time
            
        return 0.0
    
    async def async_wait_if_needed(self, limit_type: RateLimitType, tokens: int = 1) -> float:
        """Async version of wait_if_needed.
        
        Args:
            limit_type: Type of rate limit to check
            tokens: Number of tokens required
            
        Returns:
            Time waited in seconds
        """
        can_proceed, wait_time = self.can_proceed(limit_type, tokens)
        
        if not can_proceed and wait_time > 0:
            logger.info(f"Rate limited, waiting {wait_time:.2f}s for {limit_type.value}")
            await asyncio.sleep(wait_time)
            return wait_time
            
        return 0.0
    
    def trigger_cooldown(self, limit_type: RateLimitType, duration: Optional[float] = None):
        """Trigger a cooldown period for a specific rate limit type.
        
        Args:
            limit_type: Type of rate limit
            duration: Cooldown duration in seconds (uses config default if None)
        """
        if limit_type not in self.configs:
            return
            
        cooldown_duration = duration or self.configs[limit_type].cooldown_period
        self.cooldown_until[limit_type] = time.time() + cooldown_duration
        
        logger.warning(f"Cooldown triggered for {limit_type.value}: {cooldown_duration}s")
    
    def reset_limits(self, limit_type: Optional[RateLimitType] = None):
        """Reset rate limits.
        
        Args:
            limit_type: Specific limit type to reset (resets all if None)
        """
        if limit_type:
            if limit_type in self.buckets:
                self.buckets[limit_type].reset()
                self.cooldown_until[limit_type] = 0.0
                self.request_history[limit_type].clear()
                logger.info(f"Reset rate limits for {limit_type.value}")
        else:
            for bucket in self.buckets.values():
                bucket.reset()
            self.cooldown_until.clear()
            for history in self.request_history.values():
                history.clear()
            logger.info("Reset all rate limits")
    
    def get_stats(self, limit_type: RateLimitType) -> Dict[str, any]:
        """Get statistics for a rate limit type.
        
        Args:
            limit_type: Type of rate limit
            
        Returns:
            Dictionary with statistics
        """
        if limit_type not in self.buckets:
            return {}
            
        bucket = self.buckets[limit_type]
        history = self.request_history[limit_type]
        now = time.time()
        
        # Count requests in last minute
        recent_requests = sum(1 for req_time in history if now - req_time <= 60)
        
        return {
            'limit_type': limit_type.value,
            'available_tokens': bucket.tokens,
            'max_tokens': bucket.config.burst_limit,
            'requests_per_second': bucket.config.requests_per_second,
            'recent_requests_1min': recent_requests,
            'total_requests': len(history),
            'cooldown_remaining': max(0, self.cooldown_until[limit_type] - now),
            'last_request': history[-1] if history else None
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, any]]:
        """Get statistics for all rate limit types.
        
        Returns:
            Dictionary mapping limit types to their statistics
        """
        return {limit_type.value: self.get_stats(limit_type) for limit_type in self.buckets.keys()}

# Global rate limiter instance
_global_rate_limiter: Optional[RateLimiter] = None

def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance.
    
    Returns:
        Global rate limiter instance
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    return _global_rate_limiter

def reset_rate_limiter():
    """Reset global rate limiter."""
    global _global_rate_limiter
    _global_rate_limiter = None

# Convenience functions
def wait_for_webhook() -> float:
    """Wait if webhook rate limited."""
    return get_rate_limiter().wait_if_needed(RateLimitType.WEBHOOK)

def wait_for_api() -> float:
    """Wait if API rate limited."""
    return get_rate_limiter().wait_if_needed(RateLimitType.API_REQUEST)

def wait_for_message() -> float:
    """Wait if message sending rate limited."""
    return get_rate_limiter().wait_if_needed(RateLimitType.MESSAGE_SEND)

def wait_for_download() -> float:
    """Wait if file download rate limited."""
    return get_rate_limiter().wait_if_needed(RateLimitType.FILE_DOWNLOAD)

def wait_for_gateway() -> float:
    """Wait if gateway rate limited."""
    return get_rate_limiter().wait_if_needed(RateLimitType.GATEWAY)

# Async convenience functions
async def async_wait_for_webhook() -> float:
    """Async wait if webhook rate limited."""
    return await get_rate_limiter().async_wait_if_needed(RateLimitType.WEBHOOK)

async def async_wait_for_api() -> float:
    """Async wait if API rate limited."""
    return await get_rate_limiter().async_wait_if_needed(RateLimitType.API_REQUEST)

async def async_wait_for_message() -> float:
    """Async wait if message sending rate limited."""
    return await get_rate_limiter().async_wait_if_needed(RateLimitType.MESSAGE_SEND)

async def async_wait_for_download() -> float:
    """Async wait if file download rate limited."""
    return await get_rate_limiter().async_wait_if_needed(RateLimitType.FILE_DOWNLOAD)

async def async_wait_for_gateway() -> float:
    """Async wait if gateway rate limited."""
    return await get_rate_limiter().async_wait_if_needed(RateLimitType.GATEWAY)