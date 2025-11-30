"""Configuration management for Discord Selfbot Logger.

This module handles loading, validating, and managing configuration settings
for the Discord selfbot logger application.
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
import json
from datetime import datetime
from security import TokenValidator, WebhookValidator, log_security_event, get_secure_storage, log_audit_event

logger = logging.getLogger(__name__)

class ConfigurationError(Exception):
    """Raised when there's an error with configuration."""
    pass

class Config:
    """Configuration manager for the Discord logger."""
    
    def __init__(self, config_dir: Optional[Path] = None, encrypt_tokens: bool = True, strict_token_validation: bool = False):
        """Initialize configuration manager.
        
        Args:
            config_dir: Directory containing configuration files. Defaults to script directory.
            encrypt_tokens: Whether to encrypt tokens at rest (default True)
            strict_token_validation: If False, use lenient token validation (default False)
        """
        self.config_dir = config_dir or Path(__file__).parent
        self.env_file = self.config_dir / '.env'
        self.settings_file = self.config_dir / 'settings.json'
        self.accounts_file = self.config_dir / 'accounts.json'
        self.encrypt_tokens = encrypt_tokens
        self.strict_token_validation = strict_token_validation
        
        # Initialize secure storage for token encryption
        if self.encrypt_tokens:
            try:
                self.secure_storage = get_secure_storage()
            except Exception as e:
                logger.warning(f"Failed to initialize secure storage: {e}. Tokens will not be encrypted.")
                self.encrypt_tokens = False
                self.secure_storage = None
        else:
            self.secure_storage = None
        
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
        self._decrypt_account_tokens()  # Decrypt tokens before loading configuration
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
            # Basic checks first
            if not token or not isinstance(token, str) or len(token.strip()) < 50:
                logger.warning("Token too short or invalid type")
                return False
            
            token = token.strip()
            
            # Check for bot token prefixes (these shouldn't be used for selfbots)
            if token.startswith(('Bot ', 'Bearer ')):
                logger.warning("Bot token detected - selfbots should use user tokens")
                return False
            
            # If strict validation is disabled, do basic checks only
            if not self.strict_token_validation:
                # Lenient validation - just check basic structure
                if '.' not in token:
                    logger.warning("Token doesn't contain dots - invalid format")
                    return False
                # Accept token if it passes basic checks
                logger.info("Token passed lenient validation")
                return True
            
            # Strict validation
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
            
            # Check if token appears expired (but be lenient - this check isn't reliable)
            # Skip this check as it can give false positives
            # if TokenValidator.is_token_expired(token):
            #     log_security_event('token_appears_expired', {
            #         'token_preview': token[:10] + '...'
            #     })
            #     logger.warning("Token appears to be expired")
            #     return False
            
            # Extract and validate user ID (optional - don't fail if extraction fails)
            user_id = TokenValidator.extract_user_id(token)
            if user_id:
                log_security_event('token_validated', {
                    'user_id': user_id
                })
            else:
                # Still accept token if format validation passed
                logger.debug("Could not extract user ID from token, but format is valid")
            
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
                token = account.get('discord_token')
                
                # Check if token is still encrypted (shouldn't happen if decryption worked)
                if isinstance(token, str) and token.startswith('<encrypted:'):
                    logger.error(f'Token for account {self._active_account_id} is still encrypted! Decryption may have failed.')
                    # Try to decrypt it now as a fallback
                    self._decrypt_account_tokens()
                    token = account.get('discord_token')
                
                if not token or (isinstance(token, str) and token.startswith('<encrypted:')):
                    raise ConfigurationError(f'Token for account {self._active_account_id} could not be decrypted')
                
                self._config['DISCORD_TOKEN'] = token
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
            
            # Log audit event
            log_audit_event('account_switch', {
                'from_account': old_account,
                'to_account': account_id
            })
            
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
        
        # Log audit event
        log_audit_event('account_added', {
            'account_id': account_id,
            'account_name': name
        })
        
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
        
        # Log audit event
        log_audit_event('account_removed', {
            'account_id': account_id,
            'account_name': account_name
        })
        
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
        
        # Log audit event
        updated_fields = list(kwargs.keys())
        log_audit_event('account_updated', {
            'account_id': account_id,
            'updated_fields': updated_fields
        })
        
        logger.info(f'Updated account: {account_id}')
        return True
    
    def _encrypt_account_tokens(self):
        """Encrypt tokens in account configurations."""
        if not self.encrypt_tokens or not self.secure_storage:
            return
        
        try:
            for account_id, account_data in self._accounts.items():
                if 'discord_token' in account_data:
                    token = account_data['discord_token']
                    # Store encrypted token in secure storage
                    encrypted_data = self.secure_storage.load_data() or {}
                    encrypted_data[f'token_{account_id}'] = token
                    self.secure_storage.store_data(encrypted_data)
                    # Replace token with encrypted marker
                    account_data['discord_token'] = f'<encrypted:{account_id}>'
                    logger.debug(f'Encrypted token for account {account_id}')
        except Exception as e:
            logger.error(f'Failed to encrypt tokens: {e}')
    
    def _decrypt_account_tokens(self):
        """Decrypt tokens in account configurations."""
        if not self.encrypt_tokens or not self.secure_storage:
            return
        
        try:
            encrypted_data = self.secure_storage.load_data() or {}
            for account_id, account_data in self._accounts.items():
                if 'discord_token' in account_data:
                    token = account_data['discord_token']
                    # Check if token is encrypted
                    if token.startswith('<encrypted:'):
                        # Retrieve from secure storage
                        key = f'token_{account_id}'
                        if key in encrypted_data:
                            account_data['discord_token'] = encrypted_data[key]
                            logger.debug(f'Decrypted token for account {account_id}')
                        else:
                            logger.warning(f'Encrypted token not found in secure storage for account {account_id}')
        except Exception as e:
            logger.error(f'Failed to decrypt tokens: {e}')
    
    def _save_accounts(self):
        """Save account configurations to accounts.json."""
        try:
            # Encrypt tokens before saving
            if self.encrypt_tokens:
                self._encrypt_account_tokens()
            
            accounts_data = {
                'active_account': self._active_account_id,
                'accounts': self._accounts
            }
            
            # Create backup before saving
            self._backup_accounts()
            
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_data, f, indent=2)
                
            logger.debug('Accounts saved successfully')
            
        except Exception as e:
            logger.error(f'Failed to save accounts: {e}')
            raise ConfigurationError(f'Failed to save accounts: {e}')
    
    def _backup_accounts(self):
        """Create a backup of accounts.json."""
        try:
            if not self.accounts_file.exists():
                return
            
            backup_dir = self.config_dir / 'backups'
            backup_dir.mkdir(exist_ok=True)
            
            # Create backup filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = backup_dir / f'accounts_{timestamp}.json'
            
            # Copy current file to backup
            import shutil
            shutil.copy2(self.accounts_file, backup_file)
            
            # Keep only last 10 backups
            backups = sorted(backup_dir.glob('accounts_*.json'), key=lambda p: p.stat().st_mtime)
            if len(backups) > 10:
                for old_backup in backups[:-10]:
                    old_backup.unlink()
                    logger.debug(f'Removed old backup: {old_backup.name}')
            
            logger.debug(f'Created backup: {backup_file.name}')
            
        except Exception as e:
            logger.warning(f'Failed to create backup: {e}')
    
    def create_backup(self, backup_path: Optional[Path] = None, encrypt: bool = False) -> Path:
        """Create a manual backup of accounts.json.
        
        Args:
            backup_path: Optional custom backup path
            encrypt: Whether to encrypt the backup
            
        Returns:
            Path to backup file
        """
        try:
            if not self.accounts_file.exists():
                raise ConfigurationError('No accounts file to backup')
            
            if backup_path is None:
                backup_dir = self.config_dir / 'backups'
                backup_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = backup_dir / f'accounts_manual_{timestamp}.json'
            
            # Read accounts data
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                accounts_data = json.load(f)
            
            # Encrypt if requested
            if encrypt:
                from security import get_secure_storage
                secure_storage = get_secure_storage()
                secure_storage.store_data(accounts_data)
                backup_path = backup_path.with_suffix('.enc')
                logger.info(f'Created encrypted backup: {backup_path}')
            else:
                # Write plain backup
                with open(backup_path, 'w', encoding='utf-8') as f:
                    json.dump(accounts_data, f, indent=2)
                logger.info(f'Created backup: {backup_path}')
            
            return backup_path
            
        except Exception as e:
            logger.error(f'Failed to create backup: {e}')
            raise ConfigurationError(f'Failed to create backup: {e}')
    
    def restore_backup(self, backup_path: Path, encrypted: bool = False) -> bool:
        """Restore accounts from a backup file.
        
        Args:
            backup_path: Path to backup file
            encrypted: Whether backup is encrypted
            
        Returns:
            True if successful
        """
        try:
            if not backup_path.exists():
                raise ConfigurationError(f'Backup file not found: {backup_path}')
            
            # Load backup data
            if encrypted:
                from security import get_secure_storage
                secure_storage = get_secure_storage()
                accounts_data = secure_storage.load_data()
                if not accounts_data:
                    raise ConfigurationError('Failed to decrypt backup')
            else:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    accounts_data = json.load(f)
            
            # Validate backup data
            if 'accounts' not in accounts_data:
                raise ConfigurationError('Invalid backup format: missing accounts')
            
            # Create backup of current file before restore
            self._backup_accounts()
            
            # Restore accounts
            self._accounts = accounts_data.get('accounts', {})
            self._active_account_id = accounts_data.get('active_account')
            
            # Save restored accounts
            self._save_accounts()
            
            # Reload configuration
            self._load_configuration()
            
            logger.info(f'Successfully restored accounts from backup: {backup_path.name}')
            return True
            
        except Exception as e:
            logger.error(f'Failed to restore backup: {e}')
            raise ConfigurationError(f'Failed to restore backup: {e}')
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List available backup files.
        
        Returns:
            List of backup file information dictionaries
        """
        try:
            backup_dir = self.config_dir / 'backups'
            if not backup_dir.exists():
                return []
            
            backups = []
            for backup_file in backup_dir.glob('accounts_*.json'):
                stat = backup_file.stat()
                backups.append({
                    'filename': backup_file.name,
                    'path': str(backup_file),
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'encrypted': False
                })
            
            # Also check for encrypted backups
            for backup_file in backup_dir.glob('accounts_*.enc'):
                stat = backup_file.stat()
                backups.append({
                    'filename': backup_file.name,
                    'path': str(backup_file),
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'encrypted': True
                })
            
            # Sort by creation time (newest first)
            backups.sort(key=lambda x: x['created'], reverse=True)
            return backups
            
        except Exception as e:
            logger.error(f'Failed to list backups: {e}')
            return []

# Global configuration instance
config = None

def get_config(strict_token_validation: bool = False) -> Config:
    """Get global configuration instance.
    
    Args:
        strict_token_validation: If True, use strict token validation (default False)
    
    Returns:
        Config: Global configuration instance
    """
    global config
    if config is None:
        config = Config(strict_token_validation=strict_token_validation)
    return config

def reload_config():
    """Reload global configuration."""
    global config
    if config is not None:
        config.reload()
    else:
        config = Config()