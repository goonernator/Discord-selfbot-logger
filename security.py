"""Security module for Discord Selfbot Logger.

This module provides security utilities including token validation,
secure storage, input sanitization, and security monitoring.
"""

import os
import re
import hashlib
import secrets
import base64
import logging
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from urllib.parse import urlparse
import json
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class SecurityError(Exception):
    """Raised when there's a security-related error."""
    pass

class TokenValidator:
    """Validates Discord tokens and provides security checks."""
    
    # Discord token patterns
    USER_TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9+/]{24}\.[A-Za-z0-9+/]{6}\.[A-Za-z0-9+/\-_]{27}$')
    BOT_TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9+/]{24}\.[A-Za-z0-9+/]{6}\.[A-Za-z0-9+/\-_]{27}$')
    
    @staticmethod
    def validate_token_format(token: str) -> Tuple[bool, str]:
        """Validate Discord token format.
        
        Args:
            token: Discord token to validate
            
        Returns:
            Tuple of (is_valid, token_type)
        """
        if not token or not isinstance(token, str):
            return False, "invalid"
            
        token = token.strip()
        
        # Check for bot token prefixes (these shouldn't be used for selfbots)
        if token.startswith(('Bot ', 'Bearer ')):
            return False, "bot_token"
            
        # Basic length check - Discord tokens are typically 59+ characters
        if len(token) < 50:
            return False, "too_short"
            
        # Check if it looks like a Discord token (should have dots separating parts)
        parts = token.split('.')
        if len(parts) < 2:  # More lenient - at least 2 parts
            return False, "invalid_format"
            
        try:
            # Try to decode the first part (user ID)
            user_id_encoded = parts[0]
            
            # Skip validation if first part is too short (might be a different format)
            if len(user_id_encoded) < 20:
                # Still try to validate, but be more lenient
                pass
            
            # Add padding if needed
            padding = 4 - (len(user_id_encoded) % 4)
            if padding != 4:
                user_id_encoded += '=' * padding
                
            user_id_bytes = base64.b64decode(user_id_encoded)
            user_id = user_id_bytes.decode('utf-8')
            
            # Check if it's a valid snowflake ID (more lenient - allow 15-21 digits)
            if not user_id.isdigit() or len(user_id) < 15 or len(user_id) > 21:
                # If we can't decode properly, but token has right structure, accept it
                # The actual validation will happen when trying to use it
                if len(parts) >= 2 and len(token) >= 50:
                    return True, "user_token"  # Accept based on structure
                return False, "invalid_user_id"
                
            return True, "user_token"
            
        except Exception as e:
            # If decode fails but token has right structure, be lenient
            # Some valid tokens might not decode properly but still work
            if len(parts) >= 2 and len(token) >= 50:
                logger.debug(f"Token decode failed but structure looks valid: {e}")
                return True, "user_token"  # Accept based on structure
            return False, f"decode_error: {str(e)[:50]}"
    
    @staticmethod
    def extract_user_id(token: str) -> Optional[str]:
        """Extract user ID from Discord token.
        
        Args:
            token: Discord token
            
        Returns:
            User ID if valid, None otherwise
        """
        try:
            is_valid, token_type = TokenValidator.validate_token_format(token)
            if not is_valid or token_type != "user_token":
                return None
                
            parts = token.split('.')
            user_id_encoded = parts[0]
            
            # Add padding if needed
            padding = 4 - (len(user_id_encoded) % 4)
            if padding != 4:
                user_id_encoded += '=' * padding
                
            user_id_bytes = base64.b64decode(user_id_encoded)
            return user_id_bytes.decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to extract user ID from token: {e}")
            return None
    
    @staticmethod
    def is_token_expired(token: str) -> bool:
        """Check if token appears to be expired based on format validation.
        
        Note: User tokens don't contain timestamps like bot tokens do,
        so we can't actually check expiration. This method only validates
        the token format and assumes it's valid if properly formatted.
        
        Args:
            token: Discord token
            
        Returns:
            False for properly formatted user tokens (we can't check expiration)
        """
        try:
            # For user tokens, we can't determine expiration from the token itself
            # The only way to know if a user token is expired is to try using it
            is_valid, token_type = TokenValidator.validate_token_format(token)
            
            # If the token format is valid, assume it's not expired
            # The actual expiration check happens when the token is used
            return not is_valid
            
        except Exception:
            return True

class WebhookValidator:
    """Validates Discord webhook URLs."""
    
    DISCORD_DOMAINS = [
        'discord.com',
        'discordapp.com',
        'ptb.discord.com',
        'canary.discord.com'
    ]
    
    @staticmethod
    def validate_webhook_url(url: str) -> Tuple[bool, str]:
        """Validate Discord webhook URL.
        
        Args:
            url: Webhook URL to validate
            
        Returns:
            Tuple of (is_valid, reason)
        """
        if not url or not isinstance(url, str):
            return False, "empty_url"
            
        try:
            parsed = urlparse(url.strip())
            
            # Check scheme
            if parsed.scheme not in ('http', 'https'):
                return False, "invalid_scheme"
                
            # Prefer HTTPS
            if parsed.scheme != 'https':
                logger.warning("Webhook URL uses HTTP instead of HTTPS")
                
            # Check domain
            if not any(domain in parsed.netloc.lower() for domain in WebhookValidator.DISCORD_DOMAINS):
                return False, "invalid_domain"
                
            # Check path
            if '/webhooks/' not in parsed.path:
                return False, "invalid_path"
                
            # Check for webhook ID and token in path
            path_parts = parsed.path.split('/webhooks/')
            if len(path_parts) != 2:
                return False, "malformed_path"
                
            webhook_parts = path_parts[1].split('/')
            if len(webhook_parts) < 2:
                return False, "missing_webhook_parts"
                
            webhook_id = webhook_parts[0]
            webhook_token = webhook_parts[1]
            
            # Validate webhook ID (should be a snowflake)
            if not webhook_id.isdigit() or len(webhook_id) < 17 or len(webhook_id) > 20:
                return False, "invalid_webhook_id"
                
            # Validate webhook token (should be base64-like)
            if len(webhook_token) < 60 or not re.match(r'^[A-Za-z0-9+/\-_]+$', webhook_token):
                return False, "invalid_webhook_token"
                
            return True, "valid"
            
        except Exception as e:
            logger.error(f"Error validating webhook URL: {e}")
            return False, "validation_error"

class SecureStorage:
    """Provides secure storage for sensitive data."""
    
    def __init__(self, storage_dir: Optional[Path] = None):
        """Initialize secure storage.
        
        Args:
            storage_dir: Directory for secure storage files
        """
        self.storage_dir = storage_dir or Path.home() / '.discord_logger'
        self.storage_dir.mkdir(mode=0o700, exist_ok=True)
        
        self.key_file = self.storage_dir / '.key'
        self.data_file = self.storage_dir / 'secure_data.enc'
        
        self._ensure_key()
    
    def _ensure_key(self):
        """Ensure encryption key exists."""
        if not self.key_file.exists():
            # Generate new key
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)
            logger.info("Generated new encryption key")
    
    def _get_cipher(self) -> Fernet:
        """Get Fernet cipher instance."""
        with open(self.key_file, 'rb') as f:
            key = f.read()
        return Fernet(key)
    
    def store_data(self, data: Dict[str, Any]) -> bool:
        """Store data securely.
        
        Args:
            data: Data to store
            
        Returns:
            True if successful
        """
        try:
            cipher = self._get_cipher()
            json_data = json.dumps(data).encode('utf-8')
            encrypted_data = cipher.encrypt(json_data)
            
            with open(self.data_file, 'wb') as f:
                f.write(encrypted_data)
            
            # Set restrictive permissions
            os.chmod(self.data_file, 0o600)
            logger.debug("Data stored securely")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store secure data: {e}")
            return False
    
    def load_data(self) -> Optional[Dict[str, Any]]:
        """Load data securely.
        
        Returns:
            Loaded data or None if failed
        """
        try:
            if not self.data_file.exists():
                return {}
                
            cipher = self._get_cipher()
            
            with open(self.data_file, 'rb') as f:
                encrypted_data = f.read()
                
            decrypted_data = cipher.decrypt(encrypted_data)
            data = json.loads(decrypted_data.decode('utf-8'))
            
            logger.debug("Data loaded securely")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load secure data: {e}")
            return None
    
    def delete_data(self) -> bool:
        """Delete stored data.
        
        Returns:
            True if successful
        """
        try:
            if self.data_file.exists():
                self.data_file.unlink()
            if self.key_file.exists():
                self.key_file.unlink()
            logger.info("Secure data deleted")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete secure data: {e}")
            return False

class InputSanitizer:
    """Sanitizes user inputs to prevent security issues."""
    
    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 255) -> str:
        """Sanitize filename for safe storage.
        
        Args:
            filename: Original filename
            max_length: Maximum allowed length
            
        Returns:
            Sanitized filename
        """
        if not filename:
            return "unknown_file"
            
        # Remove or replace dangerous characters
        safe_chars = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
        
        # Remove leading/trailing dots and spaces
        safe_chars = safe_chars.strip('. ')
        
        # Ensure it's not empty
        if not safe_chars:
            safe_chars = "sanitized_file"
            
        # Truncate if too long
        if len(safe_chars) > max_length:
            name, ext = os.path.splitext(safe_chars)
            max_name_length = max_length - len(ext)
            safe_chars = name[:max_name_length] + ext
            
        return safe_chars
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 4096) -> str:
        """Sanitize text content.
        
        Args:
            text: Original text
            max_length: Maximum allowed length
            
        Returns:
            Sanitized text
        """
        if not text:
            return ""
            
        # Remove null bytes and other control characters
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # Truncate if too long
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length-3] + "..."
            
        return sanitized
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format and security.
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid and safe
        """
        if not url or not isinstance(url, str):
            return False
            
        # Basic URL format validation
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+'  # domain...
            r'(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # host...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            
        if not url_pattern.match(url):
            return False
            
        # Check for Discord CDN URLs (most common for attachments)
        discord_domains = ['cdn.discordapp.com', 'media.discordapp.net']
        for domain in discord_domains:
            if domain in url:
                return True
                
        # Allow other HTTPS URLs but be more restrictive
        return url.startswith('https://')
    
    @staticmethod
    def validate_user_id(user_id: str) -> bool:
        """Validate Discord user ID format.
        
        Args:
            user_id: User ID to validate
            
        Returns:
            True if valid
        """
        if not user_id or not isinstance(user_id, str):
            return False
            
        # Discord snowflake IDs are 17-20 digit numbers
        return user_id.isdigit() and 17 <= len(user_id) <= 20

class AuditLogger:
    """Logs configuration changes and security events for audit trail."""
    
    def __init__(self, log_file: Optional[Path] = None):
        """Initialize audit logger.
        
        Args:
            log_file: Path to audit log file
        """
        self.log_file = log_file or Path(__file__).parent / 'audit.log'
        self.events = deque(maxlen=10000)  # Keep last 10k events in memory
    
    def log_event(self, event_type: str, details: Dict[str, Any], user: Optional[str] = None):
        """Log an audit event.
        
        Args:
            event_type: Type of event (config_change, account_switch, security_event, etc.)
            details: Event details dictionary
            user: Optional user identifier
        """
        event = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'user': user or 'system',
            'details': details
        }
        
        self.events.append(event)
        
        # Write to file
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def get_recent_events(self, event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit events.
        
        Args:
            event_type: Optional filter by event type
            limit: Maximum events to return
            
        Returns:
            List of audit events
        """
        events = list(self.events)
        
        if event_type:
            events = [e for e in events if e['event_type'] == event_type]
        
        # Sort by timestamp (newest first)
        events.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return events[:limit]

class SecurityMonitor:
    """Monitors for security events and suspicious activity."""
    
    def __init__(self, max_events: int = 1000):
        """Initialize security monitor.
        
        Args:
            max_events: Maximum events to keep in memory
        """
        self.events = deque(maxlen=max_events)
        self.failed_attempts = defaultdict(int)
        self.last_attempt = defaultdict(float)
        self.blocked_ips = set()
        
    def log_event(self, event_type: str, details: Dict[str, Any]):
        """Log a security event.
        
        Args:
            event_type: Type of security event
            details: Event details
        """
        event = {
            'timestamp': time.time(),
            'type': event_type,
            'details': details
        }
        
        self.events.append(event)
        logger.info(f"Security event: {event_type} - {details}")
    
    def check_rate_limit_violation(self, identifier: str, max_attempts: int = 5, window: int = 300) -> bool:
        """Check for rate limit violations.
        
        Args:
            identifier: Unique identifier (IP, user ID, etc.)
            max_attempts: Maximum attempts allowed
            window: Time window in seconds
            
        Returns:
            True if rate limit violated
        """
        now = time.time()
        
        # Reset counter if window expired
        if now - self.last_attempt[identifier] > window:
            self.failed_attempts[identifier] = 0
            
        self.failed_attempts[identifier] += 1
        self.last_attempt[identifier] = now
        
        if self.failed_attempts[identifier] > max_attempts:
            self.log_event('rate_limit_violation', {
                'identifier': identifier,
                'attempts': self.failed_attempts[identifier],
                'window': window
            })
            return True
            
        return False
    
    def get_recent_events(self, event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent security events.
        
        Args:
            event_type: Filter by event type
            limit: Maximum events to return
            
        Returns:
            List of recent events
        """
        events = list(self.events)
        
        if event_type:
            events = [e for e in events if e['type'] == event_type]
            
        # Sort by timestamp (newest first)
        events.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return events[:limit]

# Global instances
_security_monitor: Optional[SecurityMonitor] = None
_secure_storage: Optional[SecureStorage] = None
_audit_logger: Optional[AuditLogger] = None

def get_security_monitor() -> SecurityMonitor:
    """Get global security monitor instance."""
    global _security_monitor
    if _security_monitor is None:
        _security_monitor = SecurityMonitor()
    return _security_monitor

def get_secure_storage() -> SecureStorage:
    """Get global secure storage instance."""
    global _secure_storage
    if _secure_storage is None:
        _secure_storage = SecureStorage()
    return _secure_storage

# Convenience functions
def validate_token(token: str) -> bool:
    """Validate Discord token."""
    is_valid, token_type = TokenValidator.validate_token_format(token)
    return is_valid and token_type == "user_token"

def validate_webhook(url: str) -> bool:
    """Validate Discord webhook URL."""
    is_valid, reason = WebhookValidator.validate_webhook_url(url)
    return is_valid

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    return InputSanitizer.sanitize_filename(filename)

def sanitize_text(text: str) -> str:
    """Sanitize text content."""
    return InputSanitizer.sanitize_text(text)

def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger

def log_security_event(event_type: str, details: Dict[str, Any]):
    """Log a security event."""
    get_security_monitor().log_event(event_type, details)
    # Also log to audit trail
    get_audit_logger().log_event('security_event', details)

def log_audit_event(event_type: str, details: Dict[str, Any], user: Optional[str] = None):
    """Log an audit event (configuration changes, account switches, etc.)."""
    get_audit_logger().log_event(event_type, details, user)