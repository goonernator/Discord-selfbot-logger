"""Tests for security.py module."""

import unittest
from security import (
    TokenValidator, WebhookValidator, InputSanitizer,
    validate_token, validate_webhook, sanitize_filename, sanitize_text
)


class TestTokenValidator(unittest.TestCase):
    """Test cases for TokenValidator."""
    
    def test_validate_token_format_invalid(self):
        """Test invalid token format."""
        is_valid, token_type = TokenValidator.validate_token_format("invalid")
        self.assertFalse(is_valid)
    
    def test_extract_user_id_invalid(self):
        """Test extracting user ID from invalid token."""
        result = TokenValidator.extract_user_id("invalid")
        self.assertIsNone(result)


class TestWebhookValidator(unittest.TestCase):
    """Test cases for WebhookValidator."""
    
    def test_validate_webhook_url_invalid(self):
        """Test invalid webhook URL."""
        is_valid, reason = WebhookValidator.validate_webhook_url("invalid")
        self.assertFalse(is_valid)


class TestInputSanitizer(unittest.TestCase):
    """Test cases for InputSanitizer."""
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        result = InputSanitizer.sanitize_filename("test<>file.txt")
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
    
    def test_sanitize_text(self):
        """Test text sanitization."""
        result = InputSanitizer.sanitize_text("test\x00text")
        self.assertNotIn('\x00', result)


if __name__ == '__main__':
    unittest.main()

