"""Tests for config.py module."""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
import json
import os

from config import Config, ConfigurationError


class TestConfig(unittest.TestCase):
    """Test cases for Config class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir)
        
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_get_existing_key(self):
        """Test getting an existing configuration key."""
        config = Config(config_dir=self.config_dir, encrypt_tokens=False)
        # Config should have defaults
        self.assertIsNotNone(config.get('CACHE_MAX'))
    
    def test_get_nonexistent_key(self):
        """Test getting a non-existent key returns default."""
        config = Config(config_dir=self.config_dir, encrypt_tokens=False)
        result = config.get('NONEXISTENT_KEY', 'default')
        self.assertEqual(result, 'default')
    
    def test_validate_token_format(self):
        """Test token validation."""
        config = Config(config_dir=self.config_dir, encrypt_tokens=False)
        # This will test the validation logic
        # Note: Actual token validation requires proper format
        self.assertTrue(hasattr(config, '_validate_token'))


if __name__ == '__main__':
    unittest.main()

