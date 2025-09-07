import os
import sys
import logging
import requests
import discum
import datetime
import random
import time
import atexit
import json
import threading
from typing import Optional, Dict, Any
from pathlib import Path
from config import get_config, ConfigurationError
from rate_limiter import get_rate_limiter, RateLimitType, wait_for_webhook, wait_for_api, wait_for_download
from security import InputSanitizer, SecurityMonitor, log_security_event
from async_wrapper import get_async_wrapper, cleanup_async_wrapper, AsyncConfig
from performance_monitor import get_performance_monitor, performance_timer, monitor_performance
from web_integration import log_message, log_mention, log_deletion, log_friend_update, log_attachment_download, log_performance, start_web_integration, stop_web_integration

# Initialize configuration
try:
    config = get_config()
    config.validate()
except ConfigurationError as e:
    print(f"Configuration error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Failed to initialize configuration: {e}")
    sys.exit(1)

# Configure logging based on config
log_level = getattr(logging, config.get('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_logger.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Initialize async wrapper
async_config = AsyncConfig(
    max_concurrent_downloads=config.get('MAX_CONCURRENT_DOWNLOADS', 5),
    max_concurrent_webhooks=config.get('MAX_CONCURRENT_WEBHOOKS', 3),
    connection_timeout=config.get('CONNECTION_TIMEOUT', 10.0),
    read_timeout=config.get('REQUEST_TIMEOUT', 30.0),
    max_retries=config.get('MAX_RETRIES', 3),
    retry_delay=config.get('RETRY_DELAY', 1.0)
)
async_wrapper = get_async_wrapper(config, async_config)

# Register cleanup function
atexit.register(cleanup_async_wrapper)

# Web integration cleanup function
def cleanup_web_integration():
    """Cleanup web integration on exit."""
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(stop_web_integration())
        loop.close()
        logger.info("Web integration cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up web integration: {e}")

atexit.register(cleanup_web_integration)

# Initialize performance monitoring
perf_monitor = get_performance_monitor()
logger.info("Performance monitoring initialized")

def print_performance_stats():
    """Print current performance statistics."""
    try:
        summary = perf_monitor.get_performance_summary()
        print("\n=== Performance Statistics ===")
        print(f"Uptime: {summary['uptime_formatted']}")
        print(f"Total Operations: {summary['total_operations']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        print(f"Operations/min: {summary['operations_per_minute']:.1f}")
        print(f"Active Operations: {summary['active_operations']}")
        
        if summary['operation_stats']:
            print("\nOperation Details:")
            for op_name, stats in summary['operation_stats'].items():
                print(f"  {op_name}:")
                print(f"    Total: {stats['total']} operations")
                print(f"    Success Rate: {stats['success_rate']:.1f}%")
                print(f"    Avg Duration: {stats['avg_duration_ms']:.1f}ms")
                print(f"    Ops/sec: {stats['ops_per_second']:.2f}")
        print("="*40)
    except Exception as e:
        logger.error(f"Error printing performance stats: {e}")

# Register performance stats cleanup
atexit.register(print_performance_stats)

def fetch_user_id(token: str) -> Optional[tuple]:
    """Fetch the bot's user ID and data from Discord API."""
    try:
        headers = {'authorization': token, 'User-Agent': 'DiscordBot (https://github.com/user/repo, 1.0)'}
        response = requests.get('https://discord.com/api/v9/users/@me', headers=headers, timeout=10)
        response.raise_for_status()
        
        user_data = response.json()
        user_id = user_data.get('id')
        username = user_data.get('username', 'Unknown')
        
        if not user_id:
            raise ValueError('No user ID in API response')
            
        logger.info(f'Successfully fetched user ID: {user_id} (Username: {username})')
        return user_id, user_data
        
    except requests.exceptions.Timeout:
        logger.error('Timeout while fetching user ID from Discord API')
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            logger.error('Invalid Discord token - authentication failed')
        else:
            logger.error(f'HTTP error while fetching user ID: {e.response.status_code}')
    except requests.exceptions.RequestException as e:
        logger.error(f'Network error while fetching user ID: {e}')
    except ValueError as e:
        logger.error(f'Invalid response from Discord API: {e}')
    except Exception as e:
        logger.error(f'Unexpected error while fetching user ID: {e}')
    
    return None

def initialize_bot(token: str) -> Optional[discum.Client]:
    """Initialize the Discum client with error handling."""
    try:
        bot = discum.Client(token=token, log=False)
        logger.info('Discord client initialized successfully')
        return bot
    except Exception as e:
        logger.error(f'Failed to initialize Discord client: {e}')
        return None

# Discord Client Manager for account switching
class DiscordClientManager:
    """Manages Discord client instances and account switching."""
    
    def __init__(self, config_instance):
        self.config = config_instance
        self.current_client = None
        self.current_user_id = None
        self.current_user_data = None
        self.current_account_id = None
        self._initialize_current_account()
    
    def _initialize_current_account(self):
        """Initialize with the current active account."""
        try:
            active_account = self.config.get_active_account()
            if active_account:
                self.current_account_id = self.config.get_active_account_id()
                self._setup_client(active_account)
            else:
                logger.error("No active account found")
        except Exception as e:
            logger.error(f"Error initializing current account: {e}")
    
    def _setup_client(self, account_data):
        """Setup Discord client for the given account."""
        try:
            token = account_data['discord_token']
            
            # Fetch user ID and data
            result = fetch_user_id(token)
            if not result:
                logger.error(f"Failed to fetch user ID for account {account_data.get('name', 'Unknown')}")
                return False
            
            user_id, user_data = result
            
            # Initialize Discord client
            client = initialize_bot(token)
            if not client:
                logger.error(f"Failed to initialize Discord client for account {account_data.get('name', 'Unknown')}")
                return False
            
            # Store current client info
            self.current_client = client
            self.current_user_id = user_id
            self.current_user_data = user_data
            
            logger.info(f"Successfully setup client for account: {account_data.get('name', 'Unknown')} ({user_id})")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up client: {e}")
            return False
    
    def switch_account(self, account_id):
        """Switch to a different account."""
        try:
            # Stop current client if running
            if self.current_client:
                try:
                    self.current_client.gateway.close()
                    logger.info("Closed previous Discord connection")
                except:
                    pass  # Ignore errors when closing
            
            # Get new account data
            accounts = self.config.get_accounts()
            if account_id not in accounts:
                logger.error(f"Account {account_id} not found")
                return False
            
            account_data = accounts[account_id]
            
            # Setup new client
            if self._setup_client(account_data):
                self.current_account_id = account_id
                logger.info(f"Successfully switched to account: {account_data.get('name', 'Unknown')}")
                return True
            else:
                logger.error(f"Failed to switch to account: {account_data.get('name', 'Unknown')}")
                return False
                
        except Exception as e:
            logger.error(f"Error switching account: {e}")
            return False
    
    def get_current_config(self):
        """Get current account configuration values."""
        try:
            active_account = self.config.get_active_account()
            if not active_account:
                # Fallback to legacy config
                return {
                    'TOKEN': self.config['DISCORD_TOKEN'],
                    'FRIEND_WEBHOOK': self.config['WEBHOOK_URL_FRIEND'],
                    'MESSAGE_WEBHOOK': self.config['WEBHOOK_URL_MESSAGE'],
                    'COMMAND_WEBHOOK': self.config['WEBHOOK_URL_COMMAND']
                }
            
            webhook_urls = active_account.get('webhook_urls', {})
            return {
                'TOKEN': active_account['discord_token'],
                'FRIEND_WEBHOOK': webhook_urls.get('friend', ''),
                'MESSAGE_WEBHOOK': webhook_urls.get('message', ''),
                'COMMAND_WEBHOOK': webhook_urls.get('command', '')
            }
        except Exception as e:
            logger.error(f"Error getting current config: {e}")
            return {}
    
    def get_client(self):
        """Get current Discord client."""
        return self.current_client
    
    def get_user_id(self):
        """Get current user ID."""
        return self.current_user_id
    
    def get_user_data(self):
        """Get current user data."""
        return self.current_user_data
    
    def get_account_id(self):
        """Get current account ID."""
        return self.current_account_id

# Initialize Discord client manager
client_manager = DiscordClientManager(config)

# Get current configuration values
current_config = client_manager.get_current_config()
TOKEN = current_config.get('TOKEN', '')
FRIEND_WEBHOOK = current_config.get('FRIEND_WEBHOOK', '')
MESSAGE_WEBHOOK = current_config.get('MESSAGE_WEBHOOK', '')
COMMAND_WEBHOOK = current_config.get('COMMAND_WEBHOOK', '')

# Prepare attachments directory
def setup_attachments_directory() -> Path:
    """Create and return the attachments directory."""
    try:
        attach_dir = Path(__file__).parent / 'attachments'
        attach_dir.mkdir(exist_ok=True)
        logger.info(f'Attachments directory ready: {attach_dir}')
        return attach_dir
    except Exception as e:
        logger.error(f'Failed to create attachments directory: {e}')
        raise

ATTACH_DIR = setup_attachments_directory()

# Channel name cache to avoid repeated API calls
channel_name_cache = {}

# Global restart flag
should_restart = False

# Duplicate detection storage
duplicate_detection_cache = {}  # Store recent messages for duplicate detection
flagged_duplicates = {}  # Store flagged duplicate messages

def fetch_channel_info(token: str, channel_id: str) -> Optional[Dict[str, str]]:
    """Fetch channel information from Discord API."""
    if channel_id in channel_name_cache:
        return channel_name_cache[channel_id]
        
    try:
        headers = {'authorization': token, 'User-Agent': 'DiscordBot (https://github.com/user/repo, 1.0)'}
        response = requests.get(f'https://discord.com/api/v9/channels/{channel_id}', headers=headers, timeout=10)
        response.raise_for_status()
        
        channel_data = response.json()
        channel_name = channel_data.get('name', f'Channel-{channel_id[:8]}')
        channel_type = channel_data.get('type', 0)
        
        # Handle different channel types
        if channel_type == 1:  # DM
            channel_display = 'Direct Message'
        elif channel_type == 3:  # Group DM
            channel_display = f'Group: {channel_name}' if channel_name else 'Group DM'
        else:  # Guild channel
            guild_id = channel_data.get('guild_id')
            if guild_id:
                # Try to get guild name
                try:
                    guild_response = requests.get(f'https://discord.com/api/v9/guilds/{guild_id}', headers=headers, timeout=5)
                    if guild_response.status_code == 200:
                        guild_data = guild_response.json()
                        guild_name = guild_data.get('name', 'Unknown Server')
                        channel_display = f'#{channel_name} ({guild_name})'
                    else:
                        channel_display = f'#{channel_name}'
                except:
                    channel_display = f'#{channel_name}'
            else:
                channel_display = f'#{channel_name}'
        
        result = {
            'name': channel_name,
            'display': channel_display,
            'type': channel_type
        }
        
        # Cache the result
        channel_name_cache[channel_id] = result
        logger.debug(f'Cached channel info for {channel_id}: {channel_display}')
        
        return result
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            logger.debug(f'No access to channel {channel_id}')
            result = {'name': 'Private Channel', 'display': 'Private Channel', 'type': 0}
        elif e.response.status_code == 404:
            logger.debug(f'Channel {channel_id} not found')
            result = {'name': 'Deleted Channel', 'display': 'Deleted Channel', 'type': 0}
        else:
            logger.warning(f'HTTP error fetching channel {channel_id}: {e.response.status_code}')
            result = {'name': f'Channel-{channel_id[:8]}', 'display': f'Channel-{channel_id[:8]}', 'type': 0}
        
        # Cache error results too to avoid repeated failed requests
        channel_name_cache[channel_id] = result
        return result
        
    except Exception as e:
        logger.warning(f'Error fetching channel info for {channel_id}: {e}')
        result = {'name': f'Channel-{channel_id[:8]}', 'display': f'Channel-{channel_id[:8]}', 'type': 0}
        channel_name_cache[channel_id] = result
        return result

# Get current client and user ID from client manager
bot = client_manager.get_client()
MY_ID = client_manager.get_user_id()

if not bot or not MY_ID:
    logger.critical('Failed to initialize Discord client or fetch user ID. Exiting.')
    sys.exit(1)

# Get configuration constants
CACHE_MAX = config['CACHE_MAX']
ATTACHMENT_SIZE_LIMIT = config['ATTACHMENT_SIZE_LIMIT']
REQUEST_TIMEOUT = config['REQUEST_TIMEOUT']
WEBHOOK_TIMEOUT = config['WEBHOOK_TIMEOUT']
RATE_LIMIT_DELAY = config['RATE_LIMIT_DELAY']
MAX_DELETE_ITERATIONS = config['MAX_DELETE_ITERATIONS']

# In-memory cache for mention and delete-event logging
message_cache = {}

# Web server settings cache
_settings_cache = {'webhook_enabled': True, 'last_fetch': 0}
SETTINGS_CACHE_DURATION = 30  # Cache settings for 30 seconds

def get_webhook_settings() -> bool:
    """Get webhook settings from web server with caching.
    
    Returns:
        bool: True if webhooks are enabled, False otherwise
    """
    global _settings_cache
    
    current_time = time.time()
    
    # Check if cache is still valid
    if current_time - _settings_cache['last_fetch'] < SETTINGS_CACHE_DURATION:
        return _settings_cache['webhook_enabled']
    
    try:
        # Try to fetch from web server
        response = requests.get('http://127.0.0.1:5002/api/settings', timeout=2)
        if response.status_code == 200:
            settings = response.json()
            _settings_cache['webhook_enabled'] = settings.get('webhook_enabled', True)
            _settings_cache['last_fetch'] = current_time
            logger.debug(f"Fetched webhook settings: {_settings_cache['webhook_enabled']}")
        else:
            logger.warning(f"Failed to fetch settings from web server: {response.status_code}")
    except Exception as e:
        logger.debug(f"Could not fetch settings from web server: {e}")
        # Keep using cached value or default
    
    return _settings_cache['webhook_enabled']

def send_user_profile_to_web_server():
    """Send user profile data to web server for dashboard display."""
    try:
        if not bot or not MY_ID:
            logger.warning("Cannot send user profile: Discord client not initialized")
            return
        
        # Get user info from client manager (stored from Discord API) - try this first
        user_info = None
        
        # First, try to get user data from client manager
        try:
            stored_user_data = client_manager.get_user_data()
            logger.info(f"Client manager user data: {stored_user_data}")
            if stored_user_data:
                user_info = {
                    'id': str(stored_user_data.get('id', MY_ID)),
                    'username': stored_user_data.get('username', 'Unknown'),
                    'discriminator': stored_user_data.get('discriminator', '0'),
                    'global_name': stored_user_data.get('global_name'),
                    'avatar': stored_user_data.get('avatar')
                }
                logger.info(f"Got user info from client manager: {user_info}")
            else:
                logger.warning("Client manager returned no user data")
        except Exception as manager_error:
            logger.warning(f"Error accessing client manager user data: {manager_error}")
        
        # Debug: Check what's available in the session (only if client manager failed)
        if not user_info:
            logger.info(f"Session object: {hasattr(bot.gateway, 'session')}")
            if hasattr(bot.gateway, 'session'):
                logger.info(f"Session has cachedUsers: {hasattr(bot.gateway.session, 'cachedUsers')}")
                logger.info(f"Session has user: {hasattr(bot.gateway.session, 'user')}")
        
        # Fallback: try bot.user directly
        if not user_info:
            try:
                if hasattr(bot, 'user') and bot.user:
                    user_info = {
                        'id': str(bot.user.id),
                        'username': bot.user.username,
                        'discriminator': getattr(bot.user, 'discriminator', '0'),
                        'avatar': getattr(bot.user, 'avatar', None)
                    }
                    logger.info(f"Got user info from bot.user: {user_info}")
            except Exception as bot_user_error:
                logger.warning(f"Error accessing bot.user: {bot_user_error}")
        
        # If bot.user didn't work, try session approach
        if not user_info:
            try:
                if hasattr(bot.gateway, 'session'):
                    # Try to access cachedUsers directly first
                    if hasattr(bot.gateway.session, 'cachedUsers'):
                        try:
                            cached_users = getattr(bot.gateway.session, 'cachedUsers', None)
                            logger.info(f"Cached users available: {cached_users is not None}")
                            if cached_users:
                                logger.info(f"Cached users keys (first 10): {list(cached_users.keys())[:10]}")
                                logger.info(f"Looking for MY_ID: {MY_ID} (type: {type(MY_ID)})")
                                
                                # Try both integer and string versions of MY_ID
                                if MY_ID in cached_users:
                                    user_info = cached_users[MY_ID]
                                    logger.info(f"Found user in cache with int ID: {user_info}")
                                elif str(MY_ID) in cached_users:
                                    user_info = cached_users[str(MY_ID)]
                                    logger.info(f"Found user in cache with string ID: {user_info}")
                                else:
                                    # Try to find any user that might be the current user
                                    for key, user_data in list(cached_users.items())[:5]:
                                        logger.info(f"Sample cached user - Key: {key} (type: {type(key)}), Data: {user_data}")
                                    logger.info(f"User ID {MY_ID} not found in cached users")
                        except Exception as cache_error:
                            logger.warning(f"Error accessing cached users: {cache_error}")
                    
                    # Also try to access session.user if available
                    try:
                        session_user = getattr(bot.gateway.session, 'user', None)
                        logger.info(f"Session user type: {type(session_user)}, value: {session_user}")
                        if isinstance(session_user, dict) and not user_info:
                            user_info = session_user
                            logger.info(f"Got user from session.user: {user_info}")
                    except Exception as session_error:
                        logger.warning(f"Error accessing session.user: {session_error}")
            except Exception as e:
                 logger.warning(f"Error accessing session: {e} (type: {type(e)})")
        
        # Fallback: try bot.user
        if not user_info and hasattr(bot, 'user'):
            user_info = bot.user
            logger.info(f"Got user from bot: {user_info}")
        
        # Final fallback: create basic user info from what we know
        if not user_info:
            logger.info("Creating basic user info from available data")
            user_info = {
                'id': MY_ID,
                'username': 'Unknown',
                'discriminator': '0000',
                'avatar': None
            }
        
        # Build avatar URL
        avatar_url = None
        if user_info.get('avatar'):
            avatar_hash = user_info['avatar']
            # Check if it's a GIF (animated avatar)
            if avatar_hash.startswith('a_'):
                avatar_url = f"https://cdn.discordapp.com/avatars/{MY_ID}/{avatar_hash}.gif?size=128"
            else:
                avatar_url = f"https://cdn.discordapp.com/avatars/{MY_ID}/{avatar_hash}.png?size=128"
        
        # Get user status from Discord presence
        status = 'offline'  # Default to offline
        try:
            # Try to get status from bot as a member in guilds (most reliable method)
            if hasattr(bot, 'guilds') and bot.guilds:
                for guild in bot.guilds:
                    try:
                        member = guild.get_member(int(MY_ID))
                        if member and hasattr(member, 'status'):
                            status = str(member.status)
                            logger.debug(f"Got status from guild member: {status}")
                            break
                    except Exception as guild_error:
                        logger.debug(f"Could not get member from guild {guild.id}: {guild_error}")
                        continue
            
            # Fallback: try to get status from bot's user presence
            if status == 'offline' and hasattr(bot, 'user') and bot.user:
                # Check if user has status attribute
                if hasattr(bot.user, 'status'):
                    status = str(bot.user.status)
                    logger.debug(f"Got status from bot.user.status: {status}")
                # Fallback: check raw status from user object
                elif hasattr(bot.user, '_status'):
                    status = str(bot.user._status)
                    logger.debug(f"Got status from bot.user._status: {status}")
            
            # Alternative: try to get from gateway presence
            if status == 'offline' and hasattr(bot, 'gateway') and bot.gateway:
                if hasattr(bot.gateway, 'session') and bot.gateway.session:
                    if hasattr(bot.gateway.session, 'presence') and bot.gateway.session.presence:
                        presence = bot.gateway.session.presence
                        if isinstance(presence, dict) and 'status' in presence:
                            status = presence['status']
                            logger.debug(f"Got status from gateway presence: {status}")
            
            # If we're connected to Discord, we should at least be online
            if status == 'offline' and bot.is_ready():
                status = 'online'
                logger.debug("Defaulting to online since bot is ready")
            
            # Additional debugging: log what we found
            logger.info(f"Final determined status: {status}")
            if hasattr(bot, 'guilds') and bot.guilds:
                logger.info(f"Bot is in {len(bot.guilds)} guilds")
            else:
                logger.info("Bot has no guilds loaded yet")
                
        except Exception as status_error:
            logger.debug(f"Could not get user status: {status_error}")
            # If we're connected, default to online
            if hasattr(bot, 'is_ready') and bot.is_ready():
                status = 'online'
        
        # Prepare profile data
        profile_data = {
            'id': str(MY_ID),
            'username': user_info.get('username', 'Unknown'),
            'discriminator': user_info.get('discriminator', '0000'),
            'global_name': user_info.get('global_name'),
            'avatar_url': avatar_url,
            'status': status
        }
        
        logger.info(f"Sending profile data with status: {status}")
        
        # Send to web server
        response = requests.post(
            'http://127.0.0.1:5002/api/user/profile',
            json=profile_data,
            timeout=5,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            logger.info("User profile sent to web server successfully")
        else:
            logger.warning(f"Failed to send user profile to web server: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending user profile to web server: {e}")
        # Even if there's an error, try to send basic profile data
        try:
            basic_profile_data = {
                'id': str(MY_ID),
                'username': 'Unknown',
                'discriminator': '0000',
                'global_name': None,
                'avatar_url': None,
                'status': 'online'
            }
            
            response = requests.post(
                'http://127.0.0.1:5002/api/user/profile',
                json=basic_profile_data,
                timeout=5,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                logger.info("Basic user profile sent to web server successfully")
            else:
                logger.warning(f"Failed to send basic user profile to web server: {response.status_code}")
        except Exception as fallback_error:
            logger.error(f"Failed to send even basic profile data: {fallback_error}")


@monitor_performance("send_embed", include_args=True)
def send_embed(webhook_url: str, title: str, description: str, image_url: Optional[str] = None) -> bool:
    """Send an embed to the specified webhook with async optimization and rate limiting.
    
    Args:
        webhook_url: Discord webhook URL
        title: Embed title
        description: Embed description
        image_url: Optional image URL to include
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if webhooks are enabled via web server settings
        if not get_webhook_settings():
            logger.debug(f"Webhook disabled via settings, skipping: {title}")
            return False
        # Try async processing first (non-blocking)
        try:
            success = async_wrapper.send_embed_async(
                webhook_url, title, description, image_url
            )
            if success:
                logger.debug(f"Embed scheduled for async processing: {title}")
                return True
        except Exception as e:
            logger.warning(f"Async processing failed, falling back to sync: {e}")
        
        # Fallback to synchronous processing
        # Validate inputs
        if not webhook_url or not title:
            logger.warning('Invalid webhook URL or title provided')
            return False
            
        # Apply rate limiting before making request
        wait_time = wait_for_webhook()
        if wait_time > 0:
            logger.info(f'Rate limited, waited {wait_time:.2f}s before webhook request')
            
        # Truncate description if too long (Discord limit is 4096 characters)
        if len(description) > 4000:
            description = description[:3997] + '...'
            logger.warning('Description truncated due to length limit')
        
        embed = {
            'title': title[:256],  # Discord title limit
            'description': description,
            'color': random.randint(0, 0xFFFFFF),
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        if image_url:
            embed['image'] = {'url': image_url}
        
        response = requests.post(
            webhook_url, 
            json={'embeds': [embed]},
            timeout=10,
            headers={'User-Agent': 'Discord-Logger/1.0'}
        )
        
        if response.status_code == 429:
            # Rate limited by Discord
            retry_after = response.headers.get('Retry-After', '1')
            wait_time = float(retry_after)
            logger.warning(f'Discord rate limited, triggering cooldown: {wait_time}s')
            rate_limiter = get_rate_limiter()
            rate_limiter.trigger_cooldown(RateLimitType.WEBHOOK, wait_time)
            return False
            
        response.raise_for_status()
        
        logger.debug(f'Successfully sent embed to webhook: {title}')
        return True
        
    except requests.exceptions.Timeout:
        logger.error(f'Timeout sending webhook: {title}')
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            logger.warning(f'Rate limited on webhook: {title}')
        else:
            logger.error(f'HTTP error sending webhook ({e.response.status_code}): {title}')
    except requests.exceptions.RequestException as e:
        logger.error(f'Network error sending webhook: {e}')
    except Exception as e:
        logger.error(f'Unexpected error sending webhook: {e}')
    
    return False


@monitor_performance("download_attachment", include_args=True)
def download_attachment(url: str, filename: str) -> bool:
    """Download attachment to the attachments folder with async optimization and rate limiting.
    
    Args:
        url: Attachment URL
        filename: Filename to save as
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Try async processing first (non-blocking)
        try:
            success = async_wrapper.download_attachment_async(url, filename, ATTACH_DIR)
            if success:
                logger.debug(f"Download scheduled for async processing: {filename}")
                return True
        except Exception as e:
            logger.warning(f"Async download failed, falling back to sync: {e}")
        
        # Fallback to synchronous processing
        # Validate inputs
        if not url or not filename:
            logger.warning('Invalid URL or filename provided for attachment download')
            return False
            
        # Apply rate limiting before download
        wait_time = wait_for_download()
        if wait_time > 0:
            logger.info(f'Rate limited, waited {wait_time:.2f}s before download')
            
        # Sanitize filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        if not safe_filename:
            safe_filename = f'attachment_{int(time.time())}'
            
        file_path = ATTACH_DIR / safe_filename
        
        # Check if file already exists
        if file_path.exists():
            logger.info(f'Attachment already exists: {safe_filename}')
            return True
            
        # Download with proper headers and timeout
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, stream=True, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Check content length
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > 100 * 1024 * 1024:  # 100MB limit
            logger.warning(f'Attachment too large ({content_length} bytes): {safe_filename}')
            return False
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Get file size for logging
        file_size = file_path.stat().st_size
        
        logger.info(f'Successfully saved attachment: {file_path}')
        
        # Log attachment download to web dashboard
        log_attachment_download(safe_filename, file_size, url, True)
        
        return True
        
    except requests.exceptions.Timeout:
        logger.error(f'Timeout downloading attachment: {filename}')
    except requests.exceptions.HTTPError as e:
        logger.error(f'HTTP error downloading attachment ({e.response.status_code}): {filename}')
    except requests.exceptions.RequestException as e:
        logger.error(f'Network error downloading attachment: {e}')
    except OSError as e:
        logger.error(f'File system error saving attachment: {e}')
    except Exception as e:
        logger.error(f'Unexpected error downloading attachment: {e}')
    
    return False

@bot.gateway.command
@monitor_performance("on_message")
def on_message(resp):
    """Handle delete commands, cache messages, detect pings, and save attachments with async optimization."""
    try:
        if not resp.event.message:
            return
            
        data = resp.parsed.auto()
        if not data:
            logger.warning('Received empty message data')
            return
            
        # Extract message information safely
        content = data.get('content', '')
        author_data = data.get('author', {})
        author_id = author_data.get('id')
        channel_id = data.get('channel_id')
        message_id = data.get('id')
        
        if not author_id or not channel_id:
            logger.warning('Missing author ID or channel ID in message data')
            return
            
        username = author_data.get('username', 'Unknown')
        discriminator = author_data.get('discriminator', '0000')
        author_tag = f"{username}#{discriminator}"
        
        logger.debug(f'Processing message from {author_tag} in channel {channel_id}')
        
        # Try async message processing first (for Direct Messages and Group Chats)
        is_dm_for_async = data.get('guild_id') is None
        if is_dm_for_async:
            try:
                message_data = {
                    'author': author_data,
                    'content': content,
                    'channel_id': channel_id,
                    'message_id': message_id,
                    'attachments': data.get('attachments', []),
                    'guild_id': data.get('guild_id')
                }
                
                success = async_wrapper.process_message_async(message_data)
                if success:
                    message_type = "Group Chat" if is_group_chat else "DM"
                    logger.debug(f"{message_type} {message_id} scheduled for async processing")
                    # Still need to handle delete commands and caching synchronously
                    if not (content.startswith('$delete ') and author_id == MY_ID):
                        # Skip the synchronous web dashboard logging since async handles it
                        # But still do message caching for deletion tracking
                        try:
                            msg_id = data.get('id')
                            if msg_id and should_log_message:
                                logger.info(f"Caching message for deletion tracking: msg_id={msg_id}, author={author_tag}")
                                message_cache[msg_id] = {
                                    'content': content,
                                    'author': author_tag,
                                    'channel': channel_id,
                                    'timestamp': datetime.datetime.now().isoformat(),
                                    'is_dm': is_dm,
                                    'is_group_chat': is_group_chat,
                                    'is_mention': is_mention,
                                    'is_bot': is_bot
                                }
                                
                                # Clean cache if it gets too large
                                if len(message_cache) > CACHE_MAX:
                                    oldest_keys = list(message_cache.keys())[:len(message_cache) - CACHE_MAX + 1000]
                                    for key in oldest_keys:
                                        message_cache.pop(key, None)
                                    logger.debug(f'Cleaned message cache, removed {len(oldest_keys)} entries')
                        except Exception as e:
                            logger.error(f'Error caching message: {e}')
                        return
            except Exception as e:
                logger.warning(f"Async processing failed, falling back to sync: {e}")
        else:
            logger.debug(f"Skipping async processing for server message {message_id}")
        
        # Security monitoring removed
        
        # Content sanitization removed

        # === Save and forward attachments ===
        attachments = data.get('attachments', [])
        if attachments:
            logger.info(f'Processing {len(attachments)} attachments from {author_tag}')
            
        for att in attachments:
            try:
                url = att.get('url')
                if not url:
                    logger.warning('Attachment missing URL')
                    continue
                    
                # URL validation removed
                
                # Determine filename with fallback
                filename = att.get('filename')
                if not filename:
                    filename = os.path.basename(url.split('?')[0]) or f'attachment_{int(time.time())}'
                
                # Filename sanitization removed
                safe_filename = InputSanitizer.sanitize_filename(filename)
                filename = safe_filename
                
                success = download_attachment(url, filename)
                if success:
                    attachment_emoji = '👥🖼️' if is_group_chat else '🖼️'
                    desc = f"**Author:** {author_tag}\n**Channel:** <#{channel_id}>\n**Saved as:** `{filename}`"
                    send_embed(MESSAGE_WEBHOOK, f'{attachment_emoji} Image/Attachment received', desc, image_url=url)
                    
            except Exception as e:
                logger.error(f'Error processing attachment: {e}')

        # === Delete command ===
        if content.startswith('$delete ') and author_id == MY_ID:
            try:
                parts = content.split(maxsplit=1)
                if len(parts) < 2:
                    send_embed(COMMAND_WEBHOOK, '❌ Invalid command', 'Usage: `$delete <channelID>`')
                    return
                    
                target_ch = parts[1].strip()
                if not target_ch.isdigit():
                    send_embed(COMMAND_WEBHOOK, '❌ Invalid command', 'Channel ID must be numeric')
                    return
                
                logger.info(f'Starting message deletion in channel {target_ch}')
                deleted_count = 0
                after_id = None
                max_iterations = 100  # Prevent infinite loops
                iteration = 0
                
                while iteration < max_iterations:
                    try:
                        # Apply rate limiting before API call
                        wait_time = wait_for_api()
                        if wait_time > 0:
                            logger.info(f'Rate limited, waited {wait_time:.2f}s before API request')
                            
                        if after_id:
                            resp2 = bot.getMessages(target_ch, 100, after_id)
                        else:
                            resp2 = bot.getMessages(target_ch, 100)
                        
                        if not resp2 or resp2.status_code != 200:
                            logger.warning(f'Failed to fetch messages: {resp2.status_code if resp2 else "No response"}')
                            break
                            
                        msgs = resp2.json()
                        if not msgs or not isinstance(msgs, list):
                            break
                            
                        found_own_message = False
                        for m in msgs:
                            if m.get('author', {}).get('id') == MY_ID:
                                found_own_message = True
                                try:
                                    delete_resp = bot.deleteMessage(target_ch, m['id'])
                                    if delete_resp and delete_resp.status_code in (200, 204):
                                        deleted_count += 1
                                        logger.debug(f'Deleted message {m["id"]}')
                                    time.sleep(1.5)  # Rate limiting
                                except Exception as e:
                                    logger.warning(f'Failed to delete message {m.get("id", "unknown")}: {e}')
                        
                        if not found_own_message:
                            break
                            
                        after_id = msgs[-1]['id']
                        iteration += 1
                        
                    except Exception as e:
                        logger.error(f'Error during message deletion iteration: {e}')
                        break
                
                logger.info(f'Deletion complete: {deleted_count} messages deleted')
                send_embed(
                    COMMAND_WEBHOOK,
                    '✅ Deletion complete',
                    f'Deleted {deleted_count} messages in <#{target_ch}>'
                )
                return
                
            except Exception as e:
                logger.error(f'Error in delete command: {e}')
                send_embed(COMMAND_WEBHOOK, '❌ Delete command failed', f'Error: {str(e)}')
                return

        # === Determine if message should be logged ===
        should_log_message = False
        is_dm = data.get('guild_id') is None  # DM if no guild_id
        is_bot = author_data.get('bot', False)
        is_mention = False
        
        # Get channel info to determine if it's a group chat
        channel_info = fetch_channel_info(TOKEN, channel_id)
        is_group_chat = channel_info and channel_info.get('type') == 3  # Group DM
        
        # Check for mentions
        if not is_bot and author_id != MY_ID:
            mentions = data.get('mentions', [])
            for m in mentions:
                if m.get('id') == MY_ID:
                    is_mention = True
                    break
        
        # Log if it's a DM, Group DM, and not from the connected user
        should_log_message = (is_dm or is_group_chat) and author_id != MY_ID
        
        # === Cache messages for mention/deletion logging ===
        try:
            msg_id = data.get('id')
            if msg_id and should_log_message:
                logger.info(f"Processing message cache: msg_id={msg_id}, author={author_tag}, is_dm={is_dm}, is_mention={is_mention}")
                message_cache[msg_id] = {
                    'content': content,
                    'author': author_tag,
                    'channel': channel_id,
                    'timestamp': datetime.datetime.now().isoformat(),
                    'is_dm': is_dm,
                    'is_group_chat': is_group_chat,
                    'is_mention': is_mention,
                    'is_bot': is_bot
                }
                
                # === Duplicate Detection for Group Chats ===
                if is_group_chat and content.strip():  # Only check duplicates in group chats with content
                    duplicate_key = f"{channel_id}:{content.strip().lower()}"
                    current_time = time.time()
                    
                    # Check if this message content was seen recently (within 5 minutes)
                    if duplicate_key in duplicate_detection_cache:
                        last_seen_time, last_author, last_msg_id = duplicate_detection_cache[duplicate_key]
                        if current_time - last_seen_time < 300:  # 5 minutes
                            if last_author != author_tag:  # Different author = potential duplicate
                                # Flag as duplicate
                                duplicate_id = f"{msg_id}_{int(current_time)}"
                                flagged_duplicates[duplicate_id] = {
                                    'original_msg_id': last_msg_id,
                                    'duplicate_msg_id': msg_id,
                                    'original_author': last_author,
                                    'duplicate_author': author_tag,
                                    'content': content,
                                    'channel_id': channel_id,
                                    'timestamp': datetime.datetime.now().isoformat(),
                                    'flagged_at': current_time
                                }
                                
                                # Save flagged duplicates to file for web dashboard access
                                try:
                                    duplicates_file = Path(__file__).parent / 'flagged_duplicates.json'
                                    with open(duplicates_file, 'w', encoding='utf-8') as f:
                                        json.dump(flagged_duplicates, f, indent=2, ensure_ascii=False)
                                except Exception as e:
                                    logger.error(f"Error saving flagged duplicates: {e}")
                                
                                logger.info(f"Duplicate detected in group chat {channel_id}: '{content[:50]}...' by {author_tag} (original by {last_author})")
                                
                                # Log to web dashboard
                                try:
                                    from web_integration import log_duplicate_message
                                    log_duplicate_message(
                                        duplicate_id,
                                        last_msg_id,
                                        msg_id,
                                        last_author,
                                        author_tag,
                                        content,
                                        channel_id
                                    )
                                except ImportError:
                                    logger.warning("Web integration not available for duplicate logging")
                    
                    # Update cache with current message
                    duplicate_detection_cache[duplicate_key] = (current_time, author_tag, msg_id)
                    
                    # Clean old entries from duplicate cache (older than 5 minutes)
                    keys_to_remove = []
                    for key, (timestamp, _, _) in duplicate_detection_cache.items():
                        if current_time - timestamp > 300:
                            keys_to_remove.append(key)
                    for key in keys_to_remove:
                        duplicate_detection_cache.pop(key, None)
                    
                    # Clean old flagged duplicates (older than 24 hours)
                    flagged_keys_to_remove = []
                    for dup_id, dup_data in flagged_duplicates.items():
                        if current_time - dup_data['flagged_at'] > 86400:  # 24 hours
                            flagged_keys_to_remove.append(dup_id)
                    for key in flagged_keys_to_remove:
                        flagged_duplicates.pop(key, None)
                
                # Web dashboard logging is handled by async processing for DMs/Group Chats
                # Only log synchronously if async processing was not used
                if (is_dm or is_group_chat) and not is_dm_for_async:
                    message_type = "Group Chat" if is_group_chat else "DM"
                    logger.info(f"Logging {message_type} to dashboard (sync fallback): msg_id={msg_id}")
                    channel_name = channel_info['display'] if channel_info else f'Channel-{channel_id[:8]}'
                    
                    log_message(author_tag, content, str(channel_id), channel_name, str(msg_id), attachments)
                    logger.info(f"log_message call completed for msg_id={msg_id}")
                
                # Clean cache if it gets too large
                if len(message_cache) > CACHE_MAX:
                    # Remove oldest entries
                    oldest_keys = list(message_cache.keys())[:len(message_cache) - CACHE_MAX + 1000]
                    for key in oldest_keys:
                        message_cache.pop(key, None)
                    logger.debug(f'Cleaned message cache, removed {len(oldest_keys)} entries')
                    
        except Exception as e:
            logger.error(f'Error caching message: {e}')

        # === Mention logging disabled (only logging DMs) ===
        # Mention detection is disabled since we only want to log Direct Messages
        pass
                
    except Exception as e:
        logger.error(f'Unexpected error in message handler: {e}')

@bot.gateway.command
def on_message_delete(resp):
    """Log message deletions with improved error handling."""
    try:
        if not resp.event.message_deleted:
            return
            
        data = resp.parsed.auto()
        if not data:
            logger.warning('Received empty message deletion data')
            return
            
        msg_id = data.get('id')
        channel_id = data.get('channel_id')
        
        if not msg_id or not channel_id:
            logger.warning('Missing message ID or channel ID in deletion event')
            return
            
        # Retrieve cached message info
        cached = message_cache.pop(msg_id, None)
        
        if cached:
            author = cached.get('author', 'Unknown')
            content = cached.get('content', '[unavailable]')
            timestamp = cached.get('timestamp', 'Unknown')
            is_dm = cached.get('is_dm', False)
            is_group_chat = cached.get('is_group_chat', False)
            is_mention = cached.get('is_mention', False)
            is_bot = cached.get('is_bot', False)
            
            # Log deletion if it was a Direct Message or Group Chat
            if is_dm or is_group_chat:
                message_type = "Group Chat" if is_group_chat else "DM"
                logger.info(f'{message_type} deleted by {author} in channel {channel_id}')
                
                # Truncate content if too long
                if len(content) > 1000:
                    content = content[:997] + '...'
                    
                desc = (
                    f"**Type:** {message_type}\n"
                    f"**Author:** {author}\n"
                    f"**Channel:** <#{channel_id}>\n"
                    f"**Content:** {content}\n"
                    f"**Cached at:** {timestamp}"
                )
                
                emoji = '👥🗑️' if is_group_chat else '🗑️'
                title = f'{message_type} deleted'
                send_embed(MESSAGE_WEBHOOK, f'{emoji} {title}', desc)
                
                # Log deletion to web dashboard
                try:
                    channel_info = fetch_channel_info(TOKEN, channel_id)
                    channel_name = channel_info['display'] if channel_info else f'Channel-{channel_id[:8]}'
                    log_deletion(author, content, str(channel_id), channel_name, str(msg_id))
                except Exception as e:
                    logger.error(f'Failed to log deletion to web dashboard: {e}')
            else:
                logger.debug(f'Skipped logging deletion for non-DM/group chat message {msg_id}')
        else:
            logger.debug(f'Deleted message {msg_id} was not in cache or not tracked')
        
    except Exception as e:
        logger.error(f'Error in message deletion handler: {e}')

@bot.gateway.command
def on_ready(resp):
    """Handle Discord client ready event and send user profile to web server."""
    try:
        logger.info("Discord client is ready and connected")
        
        # Wait a moment for guilds to load
        import time
        time.sleep(2)
        
        # Send user profile to web server now that client is fully connected
        try:
            send_user_profile_to_web_server()
            logger.info("User profile sent to web server successfully")
        except Exception as e:
            logger.warning(f"Failed to send user profile to web server: {e}")
            
    except Exception as e:
        logger.error(f"Error in on_ready handler: {e}")

@bot.gateway.command
def on_presence_update(resp):
    """Handle presence/status changes and update web server."""
    try:
        if not resp.raw:
            return
            
        event_data = resp.raw.get('d', {})
        user_id = event_data.get('user', {}).get('id')
        
        # Debug: log all presence updates to understand the data structure
        logger.debug(f"Presence update received: user_id={user_id}, event_data={event_data}")
        
        # Only handle our own presence updates
        if user_id == str(MY_ID):
            status = event_data.get('status', 'online')
            logger.info(f"MY STATUS CHANGED TO: {status}")
            logger.info(f"Full presence data: {event_data}")
            
            # Update and send user profile with new status
            try:
                send_user_profile_to_web_server()
                logger.info(f"User profile updated with new status: {status}")
            except Exception as e:
                logger.error(f"Failed to update user profile after status change: {e}")
        else:
            # Log other users' status changes for debugging
            if user_id:
                other_status = event_data.get('status', 'unknown')
                logger.debug(f"Other user {user_id} status changed to: {other_status}")
                
    except Exception as e:
        logger.error(f'Error in presence update handler: {e}')

@bot.gateway.command
def on_relationship_event(resp):
    """Log friend requests and blocks with improved error handling."""
    try:
        if not resp.raw:
            logger.warning('Received empty relationship event data')
            return
            
        event_type = resp.raw.get('t')
        if event_type not in ('RELATIONSHIP_ADD', 'RELATIONSHIP_REMOVE'):
            return
            
        data = resp.raw.get('d', {})
        if not data:
            logger.warning('Missing data in relationship event')
            return
            
        relationship_type = data.get('type')
        user_id = data.get('id')
        user_data = data.get('user', {})
        
        if not user_id:
            logger.warning('Missing user ID in relationship event')
            return
            
        # Map relationship types
        type_map = {
            1: 'Friend',
            2: 'Incoming Request', 
            3: 'Outgoing Request',
            4: 'Blocked'
        }
        
        relationship_name = type_map.get(relationship_type, f'Unknown ({relationship_type})')
        action = 'Added' if event_type == 'RELATIONSHIP_ADD' else 'Removed'
        
        # Get enhanced user information
        username = user_data.get('username', 'Unknown')
        discriminator = user_data.get('discriminator', '0000')
        display_name = user_data.get('global_name') or user_data.get('display_name')
        avatar = user_data.get('avatar')
        user_tag = f"{username}#{discriminator}" if username != 'Unknown' else 'Unknown'
        
        # Build avatar URL if available
        avatar_url = None
        if avatar and user_id:
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128"
        
        logger.info(f'Relationship {action.lower()}: {relationship_name} - {user_tag} ({user_id})')
        
        desc = (
            f"**Action:** {action} {relationship_name}\n"
            f"**User:** <@{user_id}> (`{user_tag}`)\n"
            f"**Display Name:** {display_name or 'None'}\n"
            f"**User ID:** `{user_id}`"
        )
        
        send_embed(FRIEND_WEBHOOK, '🔄 Relationship update', desc)
        
        # Log enhanced friend event to web dashboard
        enhanced_user_data = {
            'username': username,
            'discriminator': discriminator,
            'display_name': display_name,
            'avatar_url': avatar_url,
            'user_tag': user_tag
        }
        log_friend_update(action, str(user_id), enhanced_user_data, relationship_name)
        
    except Exception as e:
        logger.error(f'Error in relationship event handler: {e}')

@bot.gateway.command
def on_message_update(resp):
    """Log message edits in DMs and group chats."""
    try:
        if not resp.event.message_updated:
            return
            
        data = resp.parsed.auto()
        if not data:
            logger.warning('Received empty message update data')
            return
            
        # Extract message information
        content = data.get('content', '')
        author_data = data.get('author', {})
        author_id = author_data.get('id')
        channel_id = data.get('channel_id')
        message_id = data.get('id')
        
        if not author_id or not channel_id or not message_id:
            logger.warning('Missing required fields in message update event')
            return
            
        # Skip if message is from the connected user
        if author_id == MY_ID:
            return
            
        username = author_data.get('username', 'Unknown')
        discriminator = author_data.get('discriminator', '0000')
        author_tag = f"{username}#{discriminator}"
        
        # Determine if this is a DM or group chat
        is_dm = data.get('guild_id') is None
        channel_info = fetch_channel_info(TOKEN, channel_id)
        is_group_chat = channel_info and channel_info.get('type') == 3
        
        # Only log edits for DMs and group chats
        if not (is_dm or is_group_chat):
            return
            
        message_type = "Group Chat" if is_group_chat else "DM"
        logger.info(f'{message_type} message edited by {author_tag} in channel {channel_id}')
        
        # Get original message from cache if available
        cached_message = message_cache.get(message_id, {})
        original_content = cached_message.get('content', '[Original content not cached]')
        
        # Truncate content if too long
        if len(content) > 800:
            content = content[:797] + '...'
        if len(original_content) > 800:
            original_content = original_content[:797] + '...'
            
        # Create webhook embed
        channel_name = channel_info['display'] if channel_info else f'Channel-{channel_id[:8]}'
        desc = (
            f"**Type:** {message_type}\n"
            f"**Author:** {author_tag}\n"
            f"**Channel:** <#{channel_id}>\n"
            f"**Original:** {original_content}\n"
            f"**Edited:** {content}\n"
            f"**Message ID:** `{message_id}`"
        )
        
        edit_emoji = '👥✏️' if is_group_chat else '✏️'
        send_embed(MESSAGE_WEBHOOK, f'{edit_emoji} Message edited', desc)
        
        # Update cached message with new content
        if message_id in message_cache:
            message_cache[message_id]['content'] = content
            message_cache[message_id]['edited'] = True
            
        # Log to web dashboard
        try:
            # Create a special log entry for edits
            edit_data = {
                'type': 'edit',
                'original_content': original_content,
                'edited_content': content,
                'message_id': message_id
            }
            log_message(author_tag, f"[EDITED] {content}", str(channel_id), channel_name, str(message_id), [], edit_data)
        except Exception as e:
            logger.error(f'Failed to log message edit to web dashboard: {e}')
            
    except Exception as e:
        logger.error(f'Error in message update handler: {e}')

@bot.gateway.command
def on_channel_recipient_add(resp):
    """Log when a user is added to a group chat."""
    try:
        if not resp.raw:
            return
            
        event_type = resp.raw.get('t')
        if event_type != 'CHANNEL_RECIPIENT_ADD':
            return
            
        data = resp.raw.get('d', {})
        if not data:
            logger.warning('Received empty channel recipient add data')
            return
            
        channel_id = data.get('channel_id')
        user_data = data.get('user', {})
        user_id = user_data.get('id')
        
        if not channel_id or not user_id:
            logger.warning('Missing channel ID or user ID in recipient add event')
            return
            
        # Get channel info to confirm it's a group chat
        channel_info = fetch_channel_info(TOKEN, channel_id)
        if not channel_info or channel_info.get('type') != 3:
            return  # Not a group DM
            
        username = user_data.get('username', 'Unknown')
        discriminator = user_data.get('discriminator', '0000')
        display_name = user_data.get('global_name') or user_data.get('display_name')
        user_tag = f"{username}#{discriminator}"
        
        logger.info(f'User {user_tag} added to group chat {channel_id}')
        
        channel_name = channel_info['display'] if channel_info else f'Group-{channel_id[:8]}'
        desc = (
            f"**Action:** User Added to Group Chat\n"
            f"**User:** <@{user_id}> (`{user_tag}`)\n"
            f"**Display Name:** {display_name or 'None'}\n"
            f"**Group:** {channel_name}\n"
            f"**Channel ID:** `{channel_id}`"
        )
        
        send_embed(MESSAGE_WEBHOOK, '➕ Group Chat Member Added', desc)
        
    except Exception as e:
        logger.error(f'Error in channel recipient add handler: {e}')

@bot.gateway.command
def on_channel_recipient_remove(resp):
    """Log when a user is removed from a group chat."""
    try:
        if not resp.raw:
            return
            
        event_type = resp.raw.get('t')
        if event_type != 'CHANNEL_RECIPIENT_REMOVE':
            return
            
        data = resp.raw.get('d', {})
        if not data:
            logger.warning('Received empty channel recipient remove data')
            return
            
        channel_id = data.get('channel_id')
        user_data = data.get('user', {})
        user_id = user_data.get('id')
        
        if not channel_id or not user_id:
            logger.warning('Missing channel ID or user ID in recipient remove event')
            return
            
        # Get channel info to confirm it's a group chat
        channel_info = fetch_channel_info(TOKEN, channel_id)
        if not channel_info or channel_info.get('type') != 3:
            return  # Not a group DM
            
        username = user_data.get('username', 'Unknown')
        discriminator = user_data.get('discriminator', '0000')
        display_name = user_data.get('global_name') or user_data.get('display_name')
        user_tag = f"{username}#{discriminator}"
        
        logger.info(f'User {user_tag} removed from group chat {channel_id}')
        
        channel_name = channel_info['display'] if channel_info else f'Group-{channel_id[:8]}'
        desc = (
            f"**Action:** User Removed from Group Chat\n"
            f"**User:** <@{user_id}> (`{user_tag}`)\n"
            f"**Display Name:** {display_name or 'None'}\n"
            f"**Group:** {channel_name}\n"
            f"**Channel ID:** `{channel_id}`"
        )
        
        send_embed(MESSAGE_WEBHOOK, '➖ Group Chat Member Removed', desc)
        
    except Exception as e:
        logger.error(f'Error in channel recipient remove handler: {e}')

def handle_account_switch(account_id):
    """Handle account switching from web interface."""
    global bot, MY_ID, TOKEN, FRIEND_WEBHOOK, MESSAGE_WEBHOOK, COMMAND_WEBHOOK, should_restart
    
    try:
        logger.info(f"Switching to account: {account_id}")
        
        # Switch account in client manager
        if client_manager.switch_account(account_id):
            # Update global variables
            bot = client_manager.get_client()
            MY_ID = client_manager.get_user_id()
            
            # Update webhook URLs
            current_config = client_manager.get_current_config()
            TOKEN = current_config.get('TOKEN', '')
            FRIEND_WEBHOOK = current_config.get('FRIEND_WEBHOOK', '')
            MESSAGE_WEBHOOK = current_config.get('MESSAGE_WEBHOOK', '')
            COMMAND_WEBHOOK = current_config.get('COMMAND_WEBHOOK', '')
            
            # Clear channel cache since we're switching accounts
            global channel_name_cache
            channel_name_cache.clear()
            
            logger.info(f"Successfully switched to account {account_id} (User ID: {MY_ID})")
            
            # Send notification about account switch
            if COMMAND_WEBHOOK:
                try:
                    active_account = config.get_active_account()
                    account_name = active_account.get('name', 'Unknown') if active_account else 'Unknown'
                    desc = (
                        f"**Account:** {account_name}\n"
                        f"**User ID:** `{MY_ID}`\n"
                        f"**Status:** Successfully switched and reconnected"
                    )
                    send_embed(COMMAND_WEBHOOK, '🔄 Account Switched', desc)
                except Exception as e:
                    logger.warning(f"Failed to send account switch notification: {e}")
            
            # Signal for restart instead of trying to restart gateway in place
            should_restart = True
            logger.info("Account switch completed - signaling for restart")
            
            # Close current gateway connection
            if bot:
                try:
                    bot.gateway.close()
                    logger.info("Closed current gateway connection")
                except Exception as e:
                    logger.warning(f"Error closing gateway: {e}")
            
            return True
        else:
            logger.error(f"Failed to switch to account {account_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error handling account switch: {e}")
        return False

def monitor_account_switch_signal():
    """Monitor for account switch signal file from web server."""
    global should_restart
    signal_file = Path("account_switch_signal.json")
    
    while not should_restart:
        try:
            if signal_file.exists():
                logger.info("Account switch signal detected from web server")
                try:
                    with open(signal_file, 'r') as f:
                        signal_data = json.load(f)
                    account_id = signal_data.get('account_id')
                    if account_id:
                        logger.info(f"Processing account switch to: {account_id}")
                        handle_account_switch(account_id)
                    # Remove the signal file
                    signal_file.unlink()
                except Exception as e:
                    logger.error(f"Error processing account switch signal: {e}")
                    # Remove the signal file even if there was an error
                    try:
                        signal_file.unlink()
                    except:
                        pass
            time.sleep(1)  # Check every second
        except Exception as e:
            logger.error(f"Error in signal monitoring: {e}")
            time.sleep(5)  # Wait longer on error

def check_restart_signal():
    """Check if restart is needed and handle it."""
    global should_restart
    if should_restart:
        logger.info("Restart signal detected, shutting down for restart...")
        should_restart = False
        return True
    return False

def main():
    """Main function to start the Discord logger."""
    global should_restart
    
    while True:
        should_restart = False
        try:
            logger.info('='*50)
            logger.info('Discord Selfbot Logger Starting')
            logger.info('='*50)
            
            # Get current account info
            active_account = config.get_active_account()
            account_name = active_account.get('name', 'Unknown') if active_account else 'Legacy Config'
            
            logger.info(f'Active Account: {account_name}')
            logger.info(f'User ID: {MY_ID}')
            logger.info(f'Attachments directory: {ATTACH_DIR}')
            logger.info(f'Cache limit: {CACHE_MAX:,} messages')
            logger.info('Webhooks configured for:')
            logger.info(f'  - Friends: {"✓" if FRIEND_WEBHOOK else "✗"}')
            logger.info(f'  - Messages: {"✓" if MESSAGE_WEBHOOK else "✗"}')
            logger.info(f'  - Commands: {"✓" if COMMAND_WEBHOOK else "✗"}')
            logger.info('='*50)
            
            # Send startup notification
            startup_desc = (
                f"**User ID:** `{MY_ID}`\n"
                f"**Cache Limit:** {CACHE_MAX:,} messages\n"
                f"**Attachments:** `{ATTACH_DIR}`\n"
                f"**Status:** Online and monitoring"
            )
            send_embed(COMMAND_WEBHOOK, '🚀 Discord Logger Started', startup_desc)
            
            # Initialize web integration
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # Use port 5002 to match the web server
                loop.run_until_complete(start_web_integration("http://127.0.0.1:5002", True))
                # Don't close the loop - web integration needs it to process events
                logger.info("Web integration started successfully")
            except Exception as e:
                logger.warning(f"Failed to start web integration: {e}")
                logger.info("Continuing without web dashboard integration")
            
            # User profile will be sent automatically when Discord client is ready (on_ready event)
            
            # Start signal monitoring thread
            signal_thread = threading.Thread(target=monitor_account_switch_signal, daemon=True)
            signal_thread.start()
            logger.info('Started account switch signal monitoring')
            
            logger.info('Starting Discord gateway connection...')
            bot.gateway.run(auto_reconnect=True)
            
        except KeyboardInterrupt:
            logger.info('Received shutdown signal (Ctrl+C)')
            break
        except Exception as e:
            logger.critical(f'Critical error in main: {e}')
            if not should_restart:
                raise
            logger.info('Restarting due to account switch...')
            continue
        
        # Check if we need to restart
        if should_restart:
            logger.info('Restarting due to account switch...')
            continue
        else:
            break
    
    logger.info('Discord Logger shutting down...')
    # Send shutdown notification
    try:
        send_embed(COMMAND_WEBHOOK, '🛑 Discord Logger Stopped', 'Logger has been shut down')
    except:
        pass  # Don't fail on shutdown notification

if __name__ == '__main__':
    main()