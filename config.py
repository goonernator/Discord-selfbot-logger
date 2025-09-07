"""Configuration management for Discord Selfbot Logger.

This module handles loading, validating, and managing configuration settings
for the Discord selfbot logger application.
"""

import os
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
import json
from datetime import datetime
from security import TokenValidator, WebhookValidator, log_security_event

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when there's an error with configuration."""
    pass

class Config:
    """Configuration manager for the Discord logger."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize configuration manager.
        
        Args:
            config_dir: Directory containing configuration files. Defaults to script directory.
        """
        self.config_dir = config_dir or Path(__file__).parent
        self.env_file = self.config_dir / '.env'
        self.settings_file = self.config_dir / 'settings.json'
        self.accounts_file = self.config_dir / 'accounts.json'
        
        # Account management
        self._accounts = {}
        self._active_account_id = None
        
        # Default settings
        self.defaults = {
            'CACHE_MAX': 10000,
            'ATTACHMENT_SIZE_LIMIT': 100 * 1024 * 1024,  # 100MB
            'REQUEST_TIMEOUT': 30,
            'WEBHOOK_TIMEOUT': 10,
            'RATE_LIMIT_DELAY': 1.5,
            'MAX_DELETE_ITERATIONS': 100,
            'LOG_LEVEL': 'INFO',
            'ENABLE_ATTACHMENT_DOWNLOAD': True,
            'ENABLE_MENTION_LOGGING': True,
            'ENABLE_DELETE_LOGGING': True,
            'ENABLE_RELATIONSHIP_LOGGING': True,
            
            # Web Dashboard settings
            'WEB_HOST': '127.0.0.1',
            'WEB_PORT': 5002,
            'WEB_DEBUG': False,
            'WEB_SECRET_KEY': None,  # Will be auto-generated if not provided
            'WEB_CORS_ORIGINS': '*',
            'WEB_MAX_EVENTS': 1000,
            'WEB_EVENT_RETENTION_HOURS': 24
        }
        
        self._config = {}
        self._load_accounts()
        self._load_configuration()
    
    def _validate_webhook_url(self, url: str) -> bool:
        """Validate Discord webhook URL format using security module.
        
        Args:
            url: URL to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            is_valid, reason = WebhookValidator.validate_webhook_url(url)
            if not is_valid:
                log_security_event('webhook_validation_failed', {
                    'url': url[:50] + '...' if len(url) > 50 else url,
                    'reason': reason
                })
            return is_valid
        except Exception as e:
            logger.error(f"Error validating webhook URL: {e}")
            return False
    
    def _validate_token(self, token: str) -> bool:
        """Enhanced Discord token validation using security module.
        
        Args:
            token: Discord token to validate
            
        Returns:
            bool: True if format looks valid, False otherwise
        """
        try:
            is_valid, token_type = TokenValidator.validate_token_format(token)
            
            if not is_valid:
                log_security_event('token_validation_failed', {
                    'token_type': token_type,
                    'token_preview': token[:10] + '...' if token and len(token) > 10 else 'invalid'
                })
                return False
            
            if token_type != 'user_token':
                log_security_event('invalid_token_type', {
                    'token_type': token_type,
                    'expected': 'user_token'
                })
                return False
            
            # Check if token appears expired
            if TokenValidator.is_token_expired(token):
                log_security_event('token_appears_expired', {
                    'token_preview': token[:10] + '...'
                })
                logger.warning("Token appears to be expired")
                return False
            
            # Extract and validate user ID
            user_id = TokenValidator.extract_user_id(token)
            if user_id:
                log_security_event('token_validated', {
                    'user_id': user_id
                })
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating token: {e}")
            log_security_event('token_validation_error', {
                'error': str(e)
            })
            return False
    
    def _validate_discord_token(self, token: str) -> bool:
        """Validate Discord token format (alias for _validate_token).
        
        Args:
            token: Discord token to validate
            
        Returns:
            bool: True if token is valid
        """
        return self._validate_token(token)
    
    def _load_env_file(self) -> Dict[str, Any]:
        """Load environment variables from .env file.
        
        Returns:
            Dict containing environment variables
            
        Raises:
            ConfigurationError: If .env file cannot be loaded
        """
        try:
            if not self.env_file.exists():
                raise ConfigurationError(f'.env file not found at {self.env_file}')
                
            load_dotenv(self.env_file)
            
            env_config = {
                'DISCORD_TOKEN': os.getenv('DISCORD_TOKEN'),
                'WEBHOOK_URL_FRIEND': os.getenv('WEBHOOK_URL_FRIEND'),
                'WEBHOOK_URL_MESSAGE': os.getenv('WEBHOOK_URL_MESSAGE'),
                'WEBHOOK_URL_COMMAND': os.getenv('WEBHOOK_URL_COMMAND')
            }
            
            # Validate required fields
            missing_fields = [key for key, value in env_config.items() if not value]
            if missing_fields:
                raise ConfigurationError(
                    f'Missing required environment variables: {", ".join(missing_fields)}'
                )
            
            # Validate token
            if not self._validate_token(env_config['DISCORD_TOKEN']):
                raise ConfigurationError('Invalid Discord token format')
            
            # Validate webhook URLs
            webhook_fields = ['WEBHOOK_URL_FRIEND', 'WEBHOOK_URL_MESSAGE', 'WEBHOOK_URL_COMMAND']
            for field in webhook_fields:
                if not self._validate_webhook_url(env_config[field]):
                    raise ConfigurationError(f'Invalid webhook URL format for {field}')
            
            logger.info('Environment configuration loaded and validated')
            return env_config
            
        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(f'Failed to load .env file: {e}')
    
    def _load_settings_file(self) -> Dict[str, Any]:
        """Load additional settings from JSON file.
        
        Returns:
            Dict containing settings, or empty dict if file doesn't exist
        """
        try:
            if not self.settings_file.exists():
                logger.info(f'Settings file not found at {self.settings_file}, using defaults')
                return {}
                
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                
            logger.info('Settings file loaded successfully')
            return settings
            
        except json.JSONDecodeError as e:
            logger.warning(f'Invalid JSON in settings file: {e}')
            return {}
        except Exception as e:
            logger.warning(f'Failed to load settings file: {e}')
            return {}
    
    def _load_accounts(self):
        """Load account configurations from accounts.json."""
        try:
            if not self.accounts_file.exists():
                logger.info('No accounts file found, using legacy .env configuration')
                return
                
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                accounts_data = json.load(f)
                
            self._accounts = accounts_data.get('accounts', {})
            self._active_account_id = accounts_data.get('active_account')
            
            if not self._accounts:
                logger.warning('No accounts found in accounts.json')
                return
                
            if self._active_account_id not in self._accounts:
                # Set first account as active if current active doesn't exist
                self._active_account_id = list(self._accounts.keys())[0]
                logger.warning(f'Active account not found, switching to {self._active_account_id}')
                
            logger.info(f'Loaded {len(self._accounts)} accounts, active: {self._active_account_id}')
            
        except json.JSONDecodeError as e:
            logger.error(f'Invalid JSON in accounts file: {e}')
        except Exception as e:
            logger.error(f'Failed to load accounts: {e}')
    
    def _load_configuration(self):
        """Load complete configuration from all sources."""
        try:
            # Start with defaults
            self._config = self.defaults.copy()
            
            # Load from active account if available
            if self._active_account_id and self._active_account_id in self._accounts:
                account = self._accounts[self._active_account_id]
                self._config['DISCORD_TOKEN'] = account['discord_token']
                self._config['WEBHOOK_URL_FRIEND'] = account['webhook_urls']['friend']
                self._config['WEBHOOK_URL_MESSAGE'] = account['webhook_urls']['message']
                self._config['WEBHOOK_URL_COMMAND'] = account['webhook_urls']['command']
                
                # Load account-specific settings
                account_settings = account.get('settings', {})
                for key, value in account_settings.items():
                    config_key = key.upper()
                    if config_key in self.defaults:
                        self._config[config_key] = value
            else:
                # Fallback to environment variables
                env_config = self._load_env_file()
                self._config.update(env_config)
            
            # Load additional settings from settings.json
            settings = self._load_settings_file()
            self._config.update(settings)
            
            # Override with environment variables if they exist
            for key in self.defaults:
                env_value = os.getenv(key)
                if env_value is not None:
                    # Try to convert to appropriate type
                    try:
                        if isinstance(self.defaults[key], bool):
                            self._config[key] = env_value.lower() in ('true', '1', 'yes', 'on')
                        elif isinstance(self.defaults[key], int):
                            self._config[key] = int(env_value)
                        else:
                            self._config[key] = env_value
                    except ValueError:
                        logger.warning(f'Invalid value for {key}: {env_value}, using default')
            
            logger.info('Configuration loaded successfully')
            
        except Exception as e:
            logger.error(f'Failed to load configuration: {e}')
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value
        """
        self._config[key] = value
    
    def get_required(self, key: str) -> Any:
        """Get required configuration value.
        
        Args:
            key: Configuration key
            
        Returns:
            Configuration value
            
        Raises:
            ConfigurationError: If key is not found
        """
        if key not in self._config:
            raise ConfigurationError(f'Required configuration key not found: {key}')
        return self._config[key]
    
    def save_settings(self, settings: Dict[str, Any] = None):
        """Save settings to JSON file.
        
        Args:
            settings: Settings to save. If None, saves current configuration.
        """
        try:
            # Use current config if no settings provided
            if settings is None:
                settings = self._config
            
            # Only save non-sensitive settings (not tokens/webhooks)
            safe_settings = {
                k: v for k, v in settings.items() 
                if not any(sensitive in k.upper() for sensitive in ['TOKEN', 'WEBHOOK', 'PASSWORD', 'SECRET'])
            }
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(safe_settings, f, indent=2)
                
            logger.info(f'Settings saved to {self.settings_file}')
            
        except Exception as e:
            logger.error(f'Failed to save settings: {e}')
            raise ConfigurationError(f'Failed to save settings: {e}')
    
    def reload(self):
        """Reload configuration from all sources."""
        logger.info('Reloading configuration...')
        self._load_configuration()
    
    def validate(self) -> bool:
        """Validate current configuration.
        
        Returns:
            bool: True if configuration is valid
            
        Raises:
            ConfigurationError: If configuration is invalid
        """
        required_keys = ['DISCORD_TOKEN', 'WEBHOOK_URL_FRIEND', 'WEBHOOK_URL_MESSAGE', 'WEBHOOK_URL_COMMAND']
        
        for key in required_keys:
            if key not in self._config or not self._config[key]:
                raise ConfigurationError(f'Missing required configuration: {key}')
        
        # Validate token
        if not self._validate_token(self._config['DISCORD_TOKEN']):
            raise ConfigurationError('Invalid Discord token')
        
        # Validate webhooks
        webhook_keys = ['WEBHOOK_URL_FRIEND', 'WEBHOOK_URL_MESSAGE', 'WEBHOOK_URL_COMMAND']
        for key in webhook_keys:
            if not self._validate_webhook_url(self._config[key]):
                raise ConfigurationError(f'Invalid webhook URL: {key}')
        
        return True
    
    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to configuration."""
        return self.get_required(key)
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists in configuration."""
        return key in self._config
    
    def keys(self):
        """Get all configuration keys."""
        return self._config.keys()
    
    def items(self):
        """Get all configuration items."""
        return self._config.items()
    
    # Account management methods
    def get_accounts(self) -> Dict[str, Dict[str, Any]]:
        """Get all available accounts.
        
        Returns:
            Dict containing all account configurations
        """
        return self._accounts.copy()
    
    def get_active_account_id(self) -> Optional[str]:
        """Get the currently active account ID.
        
        Returns:
            Active account ID or None if no accounts
        """
        return self._active_account_id
    
    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Get the currently active account configuration.
        
        Returns:
            Active account configuration or None
        """
        if self._active_account_id and self._active_account_id in self._accounts:
            return self._accounts[self._active_account_id].copy()
        return None
    
    def switch_account(self, account_id: str) -> bool:
        """Switch to a different account.
        
        Args:
            account_id: ID of the account to switch to
            
        Returns:
            bool: True if switch was successful
            
        Raises:
            ConfigurationError: If account doesn't exist
        """
        if account_id not in self._accounts:
            raise ConfigurationError(f'Account {account_id} not found')
        
        old_account = self._active_account_id
        self._active_account_id = account_id
        
        # Update last_used timestamp
        self._accounts[account_id]['last_used'] = datetime.now().isoformat()
        
        try:
            # Reload configuration with new account
            self._load_configuration()
            
            # Save the account switch
            self._save_accounts()
            
            logger.info(f'Switched from account {old_account} to {account_id}')
            return True
            
        except Exception as e:
            # Revert on error
            self._active_account_id = old_account
            logger.error(f'Failed to switch account: {e}')
            raise ConfigurationError(f'Failed to switch account: {e}')
    
    def add_account(self, account_id: str, name: str, discord_token: str, 
                   webhook_urls: Dict[str, str], settings: Optional[Dict[str, Any]] = None) -> bool:
        """Add a new account configuration.
        
        Args:
            account_id: Unique identifier for the account
            name: Display name for the account
            discord_token: Discord user token
            webhook_urls: Dictionary with friend, message, command webhook URLs
            settings: Optional account-specific settings
            
        Returns:
            bool: True if account was added successfully
            
        Raises:
            ConfigurationError: If account already exists or validation fails
        """
        if account_id in self._accounts:
            raise ConfigurationError(f'Account {account_id} already exists')
        
        # Validate token
        if not self._validate_token(discord_token):
            raise ConfigurationError('Invalid Discord token format')
        
        # Validate webhook URLs
        required_webhooks = ['friend', 'message', 'command']
        for webhook_type in required_webhooks:
            if webhook_type not in webhook_urls:
                raise ConfigurationError(f'Missing webhook URL for {webhook_type}')
            if not self._validate_webhook_url(webhook_urls[webhook_type]):
                raise ConfigurationError(f'Invalid webhook URL for {webhook_type}')
        
        # Create account configuration
        account_config = {
            'name': name,
            'discord_token': discord_token,
            'webhook_urls': webhook_urls,
            'settings': settings or {
                'enable_attachment_download': True,
                'enable_mention_logging': True,
                'enable_delete_logging': True,
                'enable_relationship_logging': True
            },
            'created_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat()
        }
        
        self._accounts[account_id] = account_config
        
        # If this is the first account, make it active
        if not self._active_account_id:
            self._active_account_id = account_id
            self._load_configuration()
        
        # Save accounts
        self._save_accounts()
        
        logger.info(f'Added new account: {account_id} ({name})')
        return True
    
    def remove_account(self, account_id: str) -> bool:
        """Remove an account configuration.
        
        Args:
            account_id: ID of the account to remove
            
        Returns:
            bool: True if account was removed successfully
            
        Raises:
            ConfigurationError: If account doesn't exist or is the only account
        """
        if account_id not in self._accounts:
            raise ConfigurationError(f'Account {account_id} not found')
        
        if len(self._accounts) == 1:
            raise ConfigurationError('Cannot remove the only account')
        
        # If removing active account, switch to another one
        if account_id == self._active_account_id:
            remaining_accounts = [aid for aid in self._accounts.keys() if aid != account_id]
            self._active_account_id = remaining_accounts[0]
            logger.info(f'Switched to account {self._active_account_id} after removing active account')
        
        del self._accounts[account_id]
        
        # Reload configuration if we switched accounts
        if account_id == self._active_account_id:
            self._load_configuration()
        
        # Save accounts
        self._save_accounts()
        
        logger.info(f'Removed account: {account_id}')
        return True
    
    def update_account(self, account_id: str, **kwargs) -> bool:
        """Update an account configuration.
        
        Args:
            account_id: ID of the account to update
            **kwargs: Fields to update (name, discord_token, webhook_urls, settings)
            
        Returns:
            bool: True if account was updated successfully
            
        Raises:
            ConfigurationError: If account doesn't exist or validation fails
        """
        if account_id not in self._accounts:
            raise ConfigurationError(f'Account {account_id} not found')
        
        account = self._accounts[account_id]
        
        # Validate updates
        if 'discord_token' in kwargs:
            if not self._validate_token(kwargs['discord_token']):
                raise ConfigurationError('Invalid Discord token format')
        
        if 'webhook_urls' in kwargs:
            webhook_urls = kwargs['webhook_urls']
            required_webhooks = ['friend', 'message', 'command']
            for webhook_type in required_webhooks:
                if webhook_type in webhook_urls:
                    if not self._validate_webhook_url(webhook_urls[webhook_type]):
                        raise ConfigurationError(f'Invalid webhook URL for {webhook_type}')
        
        # Apply updates
        for key, value in kwargs.items():
            if key in ['name', 'discord_token', 'webhook_urls', 'settings']:
                if key == 'webhook_urls':
                    # Merge webhook URLs
                    account['webhook_urls'].update(value)
                elif key == 'settings':
                    # Merge settings
                    account['settings'].update(value)
                else:
                    account[key] = value
        
        # If updating active account, reload configuration
        if account_id == self._active_account_id:
            self._load_configuration()
        
        # Save accounts
        self._save_accounts()
        
        logger.info(f'Updated account: {account_id}')
        return True
    
    def _save_accounts(self):
        """Save account configurations to accounts.json."""
        try:
            accounts_data = {
                'active_account': self._active_account_id,
                'accounts': self._accounts
            }
            
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_data, f, indent=2)
                
            logger.debug('Accounts saved successfully')
            
        except Exception as e:
            logger.error(f'Failed to save accounts: {e}')
            raise ConfigurationError(f'Failed to save accounts: {e}')

# Global configuration instance
config = None

def get_config() -> Config:
    """Get global configuration instance.
    
    Returns:
        Config: Global configuration instance
    """
    global config
    if config is None:
        config = Config()
    return config

def reload_config():
    """Reload global configuration."""
    global config
    if config is not None:
        config.reload()
    else:
        config = Config()