#!/usr/bin/env python3
"""
Web Dashboard Server for Discord Selfbot Logger

Provides a modern web interface for monitoring Discord events,
managing configuration, and viewing performance metrics.
"""

import os
import sys
import json
import logging
import asyncio
import psutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from flask import Flask, render_template, jsonify, request, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import requests
import hashlib
import secrets

# Import our modules
from config import get_config, ConfigurationError
from rate_limiter import get_rate_limiter, RateLimitType
from security import SecurityMonitor, log_security_event
from database import get_database
from async_wrapper import get_async_wrapper
from monitoring import get_monitoring_system
from error_handler import get_error_handler, ErrorSeverity
import csv
from io import StringIO

# Initialize Flask app
app = Flask(__name__, 
           template_folder='templates',
           static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
config = None
rate_limiter = None

security_monitor = None
event_history = []
connected_clients = set()
server_start_time = datetime.now()

# Store user profile data from Discord client
user_profile_data = None

# Settings storage
settings = {
    'webhook_enabled': True,
    'auth_enabled': False,
    'auth_password_hash': None  # SHA256 hash of password
}

# Session management
def hash_password(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(password: str, password_hash: str) -> bool:
    """Check if password matches hash."""
    return hash_password(password) == password_hash

def require_auth(f):
    """Decorator to require authentication."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if settings.get('auth_enabled', False):
            if 'authenticated' not in session or not session['authenticated']:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Authentication required'}), 401
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Event storage
MAX_EVENTS = 1000
event_buffer = []

class EventStore:
    """Manages event storage and statistics with account isolation."""
    
    def __init__(self, max_events: int = MAX_EVENTS):
        self.account_events = {}  # account_id -> events list
        self.account_stats = {}   # account_id -> stats dict
        self.max_events = max_events
        self.current_account_id = None
        
    def set_current_account(self, account_id: str):
        """Set the current active account for event logging."""
        self.current_account_id = account_id
        if account_id not in self.account_events:
            self.account_events[account_id] = []
            self.account_stats[account_id] = {
                'total_events': 0,
                'messages': 0,
                'mentions': 0,
                'deletions': 0,
                'friends': 0
            }
    
    def add_event(self, event_type: str, data: Dict[str, Any]):
        """Add a new event to the store for the current account."""
        if not self.current_account_id:
            # If no account is set, use a default account
            self.set_current_account('default')
            
        account_id = self.current_account_id
        events = self.account_events[account_id]
        stats = self.account_stats[account_id]
        
        event = {
            'id': len(events) + 1,
            'type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'account_id': account_id
        }
        
        events.append(event)
        stats['total_events'] += 1
        
        # Update type-specific stats
        if event_type == 'message':
            stats['messages'] += 1
        elif event_type == 'mention':
            stats['mentions'] += 1
        elif event_type == 'deletion':
            stats['deletions'] += 1
        elif event_type == 'friend':
            stats['friends'] += 1
        
        # Keep only recent events
        if len(events) > self.max_events:
            events.pop(0)
        
        # Emit to connected clients
        socketio.emit('new_event', event)
        
        return event
    
    def get_events(self, limit: int = 50, event_type: str = None, account_id: str = None) -> List[Dict]:
        """Get recent events, optionally filtered by type and account."""
        if account_id is None:
            account_id = self.current_account_id or 'default'
            
        if account_id not in self.account_events:
            return []
            
        events = self.account_events[account_id]
        
        if event_type:
            events = [e for e in events if e['type'] == event_type]
        
        return events[-limit:] if limit else events
    
    def clear_events(self, account_id: str = None):
        """Clear events for the specified account."""
        if account_id is None:
            account_id = self.current_account_id or 'default'
            
        if account_id in self.account_events:
            self.account_events[account_id].clear()
            self.account_stats[account_id] = {
                'total_events': 0,
                'messages': 0,
                'mentions': 0,
                'deletions': 0,
                'friends': 0
            }
        
        # Emit clear event to connected clients
        socketio.emit('events_cleared')
        
        logger.info(f"Events and statistics cleared for account: {account_id}")

# Initialize event store
event_store = EventStore()

def initialize_event_store_account():
    """Initialize event store with the current active account."""
    try:
        accounts_file = Path(__file__).parent.parent / 'accounts.json'
        if accounts_file.exists():
            with open(accounts_file, 'r') as f:
                accounts_data = json.load(f)
            
            # Get active account ID
            active_account_id = accounts_data.get('active_account')
            if active_account_id and active_account_id in accounts_data.get('accounts', {}):
                active_account = accounts_data['accounts'][active_account_id]
                event_store.set_current_account(active_account_id)
                logger.info(f"Event store initialized with account: {active_account.get('name', active_account_id)}")
            else:
                event_store.set_current_account('default')
                logger.info("Event store initialized with default account")
        else:
            event_store.set_current_account('default')
            logger.info("Event store initialized with default account (no accounts file)")
    except Exception as e:
        logger.error(f"Error initializing event store account: {e}")
        event_store.set_current_account('default')

def initialize_components():
    """Initialize all components."""
    global config, rate_limiter, security_monitor
    
    try:
        # Initialize configuration (skip token validation for web server)
        try:
            config = get_config()
            config.validate()
        except Exception as e:
            # For web server, we can use basic config without strict token validation
            from config import Config
            config = Config(strict_token_validation=False)
            logger.warning(f"Using basic config with lenient validation due to validation error: {e}")
        
        logger.info("Configuration loaded successfully")
        
        # Initialize rate limiter
        rate_limiter = get_rate_limiter()
        logger.info("Rate limiter initialized")
        
        # Initialize security monitor
        security_monitor = SecurityMonitor()
        logger.info("Security monitor initialized")
        
        # Initialize monitoring system
        monitoring_system = get_monitoring_system()
        logger.info("Monitoring system initialized")
        
        # Initialize error handler
        error_handler = get_error_handler()
        logger.info("Error handler initialized")
        
        # Initialize event store with current active account
        initialize_event_store_account()
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        raise

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page for dashboard authentication."""
    if not settings.get('auth_enabled', False):
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        password_hash = settings.get('auth_password_hash')
        
        if password_hash and check_password(password, password_hash):
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid password'), 401
    
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    """Logout and clear session."""
    session.pop('authenticated', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/')
@require_auth
def dashboard():
    """Main dashboard page."""
    try:
        # Get current account name
        current_account_name = "Loading..."
        if config:
            accounts = config.get_accounts()
            if accounts:
                active_account = next((acc for acc in accounts.values() if acc.get('active')), None)
                if active_account:
                    current_account_name = active_account.get('name', 'Unknown Account')
                elif accounts:
                    # If no active account, use the first one
                    current_account_name = list(accounts.values())[0].get('name', 'Unknown Account')
                else:
                    current_account_name = "No Account"
        
        return render_template('dashboard.html', current_account_name=current_account_name)
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return render_template('dashboard.html', current_account_name="Error")

@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    """Get authentication status."""
    return jsonify({
        'auth_enabled': settings.get('auth_enabled', False),
        'authenticated': session.get('authenticated', False)
    })

@app.route('/api/auth/setup', methods=['POST'])
def api_auth_setup():
    """Setup authentication (first time setup or change password)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        password = data.get('password')
        enable = data.get('enable', True)
        
        if enable:
            if not password or len(password) < 6:
                return jsonify({'error': 'Password must be at least 6 characters'}), 400
            
            settings['auth_password_hash'] = hash_password(password)
            settings['auth_enabled'] = True
            session['authenticated'] = True
            logger.info("Authentication enabled for web dashboard")
        else:
            settings['auth_enabled'] = False
            settings['auth_password_hash'] = None
            session.pop('authenticated', None)
            logger.info("Authentication disabled for web dashboard")
        
        return jsonify({
            'success': True,
            'auth_enabled': settings['auth_enabled']
        })
    except Exception as e:
        logger.error(f"Error setting up authentication: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint."""
    try:
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'services': {
                'web_server': 'online',
                'database': 'unknown',
                'discord_client': 'unknown'
            }
        }
        
        # Check database
        try:
            db = get_database()
            db.get_statistics()  # Test database connection
            health_status['services']['database'] = 'online'
        except Exception as e:
            health_status['services']['database'] = 'offline'
            health_status['database_error'] = str(e)
        
        # Check Discord client (try to ping main process)
        try:
            response = requests.get('http://127.0.0.1:5002/api/status', timeout=2)
            if response.status_code == 200:
                health_status['services']['discord_client'] = 'online'
            else:
                health_status['services']['discord_client'] = 'degraded'
        except:
            health_status['services']['discord_client'] = 'offline'
        
        # Determine overall status
        if all(status == 'online' for status in health_status['services'].values()):
            health_status['status'] = 'healthy'
        elif health_status['services']['web_server'] == 'online':
            health_status['status'] = 'degraded'
        else:
            health_status['status'] = 'unhealthy'
        
        status_code = 200 if health_status['status'] == 'healthy' else 503
        return jsonify(health_status), status_code
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 503

@app.route('/api/status')
@require_auth
def api_status():
    """Get system status."""
    try:
        # Get rate limiter status
        rate_status = {
            'webhook': rate_limiter.can_proceed(RateLimitType.WEBHOOK) if rate_limiter else True,
            'api': rate_limiter.can_proceed(RateLimitType.API_REQUEST) if rate_limiter else True,
            'download': rate_limiter.can_proceed(RateLimitType.FILE_DOWNLOAD) if rate_limiter else True
        }
        
        # Get event stats
        event_stats = event_store.account_stats.get(event_store.current_account_id or 'default', {
            'total_events': 0,
            'messages': 0,
            'mentions': 0,
            'deletions': 0,
            'friends': 0
        })
        
        return jsonify({
            'status': 'online',
            'timestamp': datetime.now().isoformat(),
            'rate_limits': rate_status,
            'events': event_stats,
            'uptime': get_uptime()
        })
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events')
def api_events():
    """Get recent events."""
    try:
        limit = request.args.get('limit', 50, type=int)
        event_type = request.args.get('type')
        
        events = event_store.get_events(limit=limit, event_type=event_type)
        
        # Get total count for current account
        current_account_id = event_store.current_account_id or 'default'
        total_events = len(event_store.account_events.get(current_account_id, []))
        
        return jsonify({
            'events': events,
            'total': total_events
        })
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/accounts')
def api_events_by_account():
    """Get events for all accounts with account information."""
    try:
        accounts_data = {}
        
        for account_id, events in event_store.account_events.items():
            stats = event_store.account_stats.get(account_id, {})
            
            # Get account name from accounts.json if available
            account_name = account_id
            try:
                accounts_file = Path(__file__).parent.parent / 'accounts.json'
                if accounts_file.exists():
                    with open(accounts_file, 'r') as f:
                        accounts_config = json.load(f)
                    account_info = accounts_config.get('accounts', {}).get(account_id, {})
                    account_name = account_info.get('name', account_id)
            except Exception:
                pass
            
            accounts_data[account_id] = {
                'name': account_name,
                'event_count': len(events),
                'stats': stats,
                'is_current': account_id == event_store.current_account_id
            }
        
        return jsonify({
            'accounts': accounts_data,
            'current_account': event_store.current_account_id
        })
    except Exception as e:
        logger.error(f"Error getting account events: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/account/<account_id>')
def api_events_for_account(account_id):
    """Get events for a specific account."""
    try:
        limit = request.args.get('limit', 50, type=int)
        event_type = request.args.get('type')
        
        events = event_store.get_events(limit=limit, event_type=event_type, account_id=account_id)
        total_events = len(event_store.account_events.get(account_id, []))
        stats = event_store.account_stats.get(account_id, {})
        
        # Get account name
        account_name = account_id
        try:
            accounts_file = Path(__file__).parent.parent / 'accounts.json'
            if accounts_file.exists():
                with open(accounts_file, 'r') as f:
                    accounts_config = json.load(f)
                account_info = accounts_config.get('accounts', {}).get(account_id, {})
                account_name = account_info.get('name', account_id)
        except Exception:
            pass
        
        return jsonify({
            'events': events,
            'total': total_events,
            'stats': stats,
            'account_id': account_id,
            'account_name': account_name
        })
    except Exception as e:
        logger.error(f"Error getting events for account {account_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config')
@require_auth
def api_config():
    """Get configuration (sanitized)."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        # Return sanitized config (no sensitive data)
        safe_config = {
            'log_level': config.get('LOG_LEVEL', 'INFO'),
            'max_concurrent_requests': config.get('MAX_CONCURRENT_REQUESTS', 10),
            'request_timeout': config.get('REQUEST_TIMEOUT', 30),
            'attachment_size_limit': config.get('ATTACHMENT_SIZE_LIMIT', 50 * 1024 * 1024),
            'cache_max': config.get('CACHE_MAX', 10000),
            'rate_limit_delay': config.get('RATE_LIMIT_DELAY', 1)
        }
        
        return jsonify(safe_config)
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/security')
def api_security():
    """Get security events and status."""
    try:
        # This would be implemented with actual security data
        return jsonify({
            'status': 'secure',
            'recent_events': [],
            'threat_level': 'low'
        })
    except Exception as e:
        logger.error(f"Error getting security data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/attachments')
def api_attachments():
    """Get list of downloaded attachments."""
    try:
        attach_dir = Path(__file__).parent / 'attachments'
        if not attach_dir.exists():
            return jsonify({'attachments': []})
        
        attachments = []
        for file_path in attach_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                attachments.append({
                    'name': file_path.name,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'url': f'/api/attachments/download/{file_path.name}'
                })
        
        # Sort by modification time (newest first)
        attachments.sort(key=lambda x: x['modified'], reverse=True)
        
        return jsonify({'attachments': attachments})
    except Exception as e:
        logger.error(f"Error getting attachments: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get current settings."""
    try:
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
@require_auth
def api_update_settings():
    """Update settings."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Update webhook_enabled setting
        if 'webhook_enabled' in data:
            settings['webhook_enabled'] = bool(data['webhook_enabled'])
            logger.info(f"Webhook notifications {'enabled' if settings['webhook_enabled'] else 'disabled'}")
        
        # Update log_level setting
        if 'log_level' in data:
            valid_levels = ['NONE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            new_level = data['log_level'].upper()
            if new_level in valid_levels:
                # Update config
                if config:
                    config.set('LOG_LEVEL', new_level)
                    config.save_settings()
                
                # Apply logging level immediately
                if new_level == 'NONE':
                    # Disable all logging by setting to highest level + 1
                    logging.getLogger().setLevel(logging.CRITICAL + 1)
                    logger.info(f"Logging disabled (NONE level set)")
                else:
                    numeric_level = getattr(logging, new_level)
                    logging.getLogger().setLevel(numeric_level)
                    logger.info(f"Logging level changed to {new_level}")
            else:
                return jsonify({'error': f'Invalid log level. Must be one of: {valid_levels}'}), 400
        
        return jsonify({
            'success': True,
            'settings': settings
        })
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500

# User Preferences API endpoints
@app.route('/api/preferences', methods=['GET'])
def api_get_preferences():
    """Get user preferences for context menu features."""
    try:
        # Load preferences from settings or return defaults
        preferences = settings.get('user_preferences', {
            'tagged_channels': [],
            'favorite_users': [],
            'auto_download_users': []
        })
        return jsonify(preferences)
    except Exception as e:
        logger.error(f"Error getting preferences: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/preferences/channel/tag', methods=['POST'])
def api_tag_channel():
    """Tag or untag a channel as group."""
    try:
        data = request.get_json()
        if not data or 'channel_id' not in data:
            return jsonify({'error': 'channel_id is required'}), 400
        
        channel_id = data['channel_id']
        channel_name = data.get('channel_name', 'Unknown Channel')
        action = data.get('action', 'tag')  # 'tag' or 'untag'
        
        # Initialize preferences if not exists
        if 'user_preferences' not in settings:
            settings['user_preferences'] = {
                'tagged_channels': [],
                'favorite_users': [],
                'auto_download_users': []
            }
        
        tagged_channels = settings['user_preferences']['tagged_channels']
        
        if action == 'tag':
            if channel_id not in tagged_channels:
                tagged_channels.append(channel_id)
                logger.info(f"Tagged channel {channel_name} ({channel_id}) as group")
        else:  # untag
            if channel_id in tagged_channels:
                tagged_channels.remove(channel_id)
                logger.info(f"Removed group tag from channel {channel_name} ({channel_id})")
        
        return jsonify({
            'success': True,
            'action': action,
            'channel_id': channel_id,
            'tagged_channels': tagged_channels
        })
    except Exception as e:
        logger.error(f"Error tagging channel: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/preferences/user/favorite', methods=['POST'])
def api_favorite_user():
    """Favorite or unfavorite a user."""
    try:
        data = request.get_json()
        if not data or 'username' not in data:
            return jsonify({'error': 'username is required'}), 400
        
        username = data['username']
        action = data.get('action', 'favorite')  # 'favorite' or 'unfavorite'
        
        # Initialize preferences if not exists
        if 'user_preferences' not in settings:
            settings['user_preferences'] = {
                'tagged_channels': [],
                'favorite_users': [],
                'auto_download_users': []
            }
        
        favorite_users = settings['user_preferences']['favorite_users']
        
        if action == 'favorite':
            if username not in favorite_users:
                favorite_users.append(username)
                logger.info(f"Added {username} to favorites")
        else:  # unfavorite
            if username in favorite_users:
                favorite_users.remove(username)
                logger.info(f"Removed {username} from favorites")
        
        return jsonify({
            'success': True,
            'action': action,
            'username': username,
            'favorite_users': favorite_users
        })
    except Exception as e:
        logger.error(f"Error favoriting user: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/preferences/user/autodownload', methods=['POST'])
def api_toggle_autodownload():
    """Enable or disable auto-download for a user."""
    try:
        data = request.get_json()
        if not data or 'username' not in data:
            return jsonify({'error': 'username is required'}), 400
        
        username = data['username']
        action = data.get('action', 'enable')  # 'enable' or 'disable'
        
        # Initialize preferences if not exists
        if 'user_preferences' not in settings:
            settings['user_preferences'] = {
                'tagged_channels': [],
                'favorite_users': [],
                'auto_download_users': []
            }
        
        auto_download_users = settings['user_preferences']['auto_download_users']
        
        if action == 'enable':
            if username not in auto_download_users:
                auto_download_users.append(username)
                logger.info(f"Enabled auto-download for {username}")
        else:  # disable
            if username in auto_download_users:
                auto_download_users.remove(username)
                logger.info(f"Disabled auto-download for {username}")
        
        return jsonify({
            'success': True,
            'action': action,
            'username': username,
            'auto_download_users': auto_download_users
        })
    except Exception as e:
        logger.error(f"Error toggling auto-download: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/attachments/download/<filename>')
def download_attachment(filename):
    """Download an attachment file."""
    try:
        # Attachments are stored in the root project directory
        attach_dir = Path(__file__).parent.parent / 'attachments'
        return send_from_directory(attach_dir, filename)
    except Exception as e:
        logger.error(f"Error downloading attachment: {e}")
        return jsonify({'error': str(e)}), 404

# Account Management API Endpoints
@app.route('/api/accounts', methods=['GET'])
def api_get_accounts():
    """Get all accounts and active account info."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        accounts = config.get_accounts()
        active_account_id = config.get_active_account_id()
        
        # Remove sensitive data (tokens) from response and format as object
        safe_accounts = {}
        for account_id, account_data in accounts.items():
            safe_accounts[account_id] = {
                'id': account_id,
                'name': account_data.get('name', 'Unknown'),
                'created_at': account_data.get('created_at'),
                'last_used': account_data.get('last_used'),
                'settings': account_data.get('settings', {}),
                'active': account_id == active_account_id
            }
        
        return jsonify({
            'success': True,
            'accounts': safe_accounts,
            'active_account': active_account_id
        })
    except Exception as e:
        logger.error(f"Error getting accounts: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/user/profile', methods=['POST'])
def api_update_user_profile():
    """Update user profile data from Discord client."""
    global user_profile_data
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        user_profile_data = data
        user_profile_data['last_updated'] = datetime.now().isoformat()
        
        logger.info(f"User profile updated: {data.get('username', 'Unknown')}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/user/profile')
def api_get_user_profile():
    """Get current Discord user profile information."""
    try:
        if not user_profile_data:
            logger.info("No user profile data available")
            return jsonify({
                'success': False,
                'error': 'Discord client not initialized',
                'message': 'Discord client has not been started yet'
            }), 503
        
        return jsonify({
            'success': True,
            'user': user_profile_data
        })
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'message': 'An unexpected error occurred while fetching user profile'
        }), 500

@app.route('/api/accounts', methods=['POST'])
def api_add_account():
    """Add a new account."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        required_fields = ['name', 'discord_token']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Validate Discord token format
        token = data['discord_token']
        if not config._validate_discord_token(token):
            return jsonify({'error': 'Invalid Discord token format'}), 400
        
        # Generate account ID
        import uuid
        account_id = f"account_{uuid.uuid4().hex[:8]}"
        
        # Prepare account data
        name = data['name']
        webhook_urls = data.get('webhook_urls', {})
        settings = data.get('settings', {})
        
        # Add the account
        config.add_account(account_id, name, token, webhook_urls, settings)
        
        logger.info(f"Added new account: {data['name']} ({account_id})")
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'message': 'Account added successfully'
        })
        
    except Exception as e:
        logger.error(f"Error adding account: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/switch', methods=['POST'])
def api_switch_account():
    """Switch to a different account."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        data = request.get_json()
        if not data or 'account_id' not in data:
            return jsonify({'error': 'Account ID required'}), 400
        
        account_id = data['account_id']
        
        # Switch account
        success = config.switch_account(account_id)
        
        if success:
            logger.info(f"Switched to account: {account_id}")
            
            # Update event store current account
            event_store.set_current_account(account_id)
            
            # Restart main.py with new account
            try:
                import os
                import psutil
                import subprocess
                import time
                
                # Find and terminate main.py process
                main_process = None
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.info['cmdline'] and len(proc.info['cmdline']) > 1:
                            if 'main.py' in proc.info['cmdline'][1]:
                                main_process = proc
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                if main_process:
                    logger.info(f"Terminating main.py process (PID: {main_process.pid}) for account switch")
                    main_process.terminate()
                    
                    # Wait for process to terminate
                    try:
                        main_process.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        logger.warning("Force killing main.py process")
                        main_process.kill()
                
                # Wait a moment before restarting
                time.sleep(1)
                
                # Restart main.py
                main_script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'main.py')
                if os.path.exists(main_script_path):
                    logger.info(f"Restarting main.py with account: {account_id}")
                    subprocess.Popen([sys.executable, main_script_path], 
                                   cwd=os.path.dirname(os.path.dirname(__file__)),
                                   creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
                else:
                    logger.error(f"main.py not found at {main_script_path}")
                    
            except Exception as e:
                logger.error(f"Failed to restart main.py: {e}")
            
            # Emit event to notify clients about account switch
            socketio.emit('account_switched', {
                'account_id': account_id,
                'timestamp': datetime.now().isoformat()
            })
            
            return jsonify({
                'success': True,
                'active_account': account_id,
                'message': 'Account switched successfully - main.py has been restarted with new account'
            })
        else:
            return jsonify({'error': 'Failed to switch account'}), 400
            
    except Exception as e:
        logger.error(f"Error switching account: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<account_id>', methods=['DELETE'])
def api_remove_account(account_id):
    """Remove an account."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        accounts = config.get_accounts()
        if len(accounts) <= 1:
            return jsonify({'error': 'Cannot remove the only account'}), 400
        
        if account_id not in accounts:
            return jsonify({'error': 'Account not found'}), 404
        
        # Check if we're removing the active account
        active_account_id = config.get_active_account_id()
        switched_account = False
        
        if account_id == active_account_id:
            # Switch to another account before removing
            remaining_accounts = [aid for aid in accounts.keys() if aid != account_id]
            if remaining_accounts:
                config.switch_account(remaining_accounts[0])
                switched_account = True
                logger.info(f"Switched to account {remaining_accounts[0]} before removing {account_id}")
        
        # Remove the account
        account_name = accounts[account_id].get('name', 'Unknown')
        success = config.remove_account(account_id)
        
        if success:
            logger.info(f"Removed account: {account_name} ({account_id})")
            
            # Emit event to notify clients
            socketio.emit('account_removed', {
                'account_id': account_id,
                'switched_account': switched_account,
                'timestamp': datetime.now().isoformat()
            })
            
            return jsonify({
                'success': True,
                'switched_account': switched_account,
                'message': 'Account removed successfully'
            })
        else:
            return jsonify({'error': 'Failed to remove account'}), 500
            
    except Exception as e:
        logger.error(f"Error removing account: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<account_id>', methods=['PUT'])
def api_update_account(account_id):
    """Update an account's settings."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        accounts = config.get_accounts()
        if account_id not in accounts:
            return jsonify({'error': 'Account not found'}), 404
        
        # Update account
        success = config.update_account(account_id, data)
        
        if success:
            logger.info(f"Updated account: {account_id}")
            return jsonify({
                'success': True,
                'message': 'Account updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to update account'}), 500
            
    except Exception as e:
        logger.error(f"Error updating account: {e}")
        return jsonify({'error': str(e)}), 500

# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    connected_clients.add(request.sid)
    logger.info(f"Client connected: {request.sid}")
    emit('status', {'message': 'Connected to Discord Logger Dashboard'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    connected_clients.discard(request.sid)
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('request_status')
def handle_status_request():
    """Handle status request from client."""
    try:
        # Send current status
        status_data = {
            'timestamp': datetime.now().isoformat(),
            'events': event_store.account_stats.get(event_store.current_account_id or 'default', {
                'total_events': 0,
                'messages': 0,
                'mentions': 0,
                'deletions': 0,
                'friends': 0
            }),
            'connected_clients': len(connected_clients)
        }
        emit('status_update', status_data)
    except Exception as e:
        logger.error(f"Error handling status request: {e}")
        emit('error', {'message': str(e)})

# Utility functions
def get_uptime() -> str:
    """Get server uptime."""
    uptime_delta = datetime.now() - server_start_time
    total_seconds = int(uptime_delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def log_discord_event(event_type: str, data: Dict[str, Any]):
    """Log a Discord event to the dashboard."""
    try:
        event_store.add_event(event_type, data)
        logger.info(f"Logged {event_type} event")
    except Exception as e:
        logger.error(f"Error logging event: {e}")

# API endpoint for external event logging
@app.route('/api/events', methods=['POST'])
def api_log_event():
    """Log an event from external source (like main Discord bot)."""
    try:
        data = request.get_json()
        if not data or 'type' not in data:
            return jsonify({'error': 'Invalid event data'}), 400
        
        event_type = data['type']
        event_data = data.get('data', {})
        
        event = event_store.add_event(event_type, event_data)
        
        return jsonify({
            'success': True,
            'event_id': event['id']
        })
    except Exception as e:
        logger.error(f"Error logging event: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/clear', methods=['POST'])
def api_clear_events():
    """Clear all events and reset statistics."""
    try:
        event_store.clear_events()
        return jsonify({
            'success': True,
            'message': 'All events and statistics cleared'
        })
    except Exception as e:
        logger.error(f"Error clearing events: {e}")
        return jsonify({'error': str(e)}), 500

# Duplicate Message Management API Endpoints
@app.route('/api/duplicates', methods=['GET'])
def api_get_duplicates():
    """Get all flagged duplicate messages."""
    try:
        # Get duplicates from the main process via a signal file or shared storage
        # For now, return empty list - this will be enhanced when main process integration is complete
        duplicates_file = Path(__file__).parent.parent / 'flagged_duplicates.json'
        
        if duplicates_file.exists():
            with open(duplicates_file, 'r', encoding='utf-8') as f:
                duplicates = json.load(f)
        else:
            duplicates = {}
        
        # Convert to list format for frontend
        duplicates_list = []
        for dup_id, dup_data in duplicates.items():
            duplicates_list.append({
                'id': dup_id,
                **dup_data
            })
        
        # Sort by timestamp (newest first)
        duplicates_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return jsonify({
            'success': True,
            'duplicates': duplicates_list,
            'count': len(duplicates_list)
        })
    except Exception as e:
        logger.error(f"Error getting duplicates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/duplicates/<duplicate_id>', methods=['DELETE'])
def api_remove_duplicate(duplicate_id):
    """Remove a flagged duplicate from the list."""
    try:
        duplicates_file = Path(__file__).parent.parent / 'flagged_duplicates.json'
        
        if duplicates_file.exists():
            with open(duplicates_file, 'r', encoding='utf-8') as f:
                duplicates = json.load(f)
        else:
            duplicates = {}
        
        if duplicate_id in duplicates:
            del duplicates[duplicate_id]
            
            # Save updated duplicates
            with open(duplicates_file, 'w', encoding='utf-8') as f:
                json.dump(duplicates, f, indent=2)
            
            return jsonify({
                'success': True,
                'message': 'Duplicate removed successfully'
            })
        else:
            return jsonify({'error': 'Duplicate not found'}), 404
            
    except Exception as e:
        logger.error(f"Error removing duplicate: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/duplicates/clear', methods=['POST'])
def api_clear_duplicates():
    """Clear all flagged duplicates."""
    try:
        duplicates_file = Path(__file__).parent.parent / 'flagged_duplicates.json'
        
        # Write empty object to file
        with open(duplicates_file, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        
        return jsonify({
            'success': True,
            'message': 'All duplicates cleared successfully'
        })
    except Exception as e:
        logger.error(f"Error clearing duplicates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/messages', methods=['GET'])
def api_export_messages():
    """Export messages to JSON or CSV format."""
    try:
        format_type = request.args.get('format', 'json').lower()
        account_id = request.args.get('account_id')
        channel_id = request.args.get('channel_id')
        author_id = request.args.get('author_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        limit = request.args.get('limit', 1000, type=int)
        
        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid start_date format'}), 400
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid end_date format'}), 400
        
        # Get messages from database
        db = get_database()
        messages = db.get_messages(
            account_id=account_id,
            channel_id=channel_id,
            author_id=author_id,
            limit=limit,
            start_date=start_dt,
            end_date=end_dt
        )
        
        if format_type == 'csv':
            import csv
            import io
            from flask import Response
            
            output = io.StringIO()
            if messages:
                writer = csv.DictWriter(output, fieldnames=messages[0].keys())
                writer.writeheader()
                writer.writerows(messages)
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
            )
        else:  # JSON
            return jsonify({
                'success': True,
                'count': len(messages),
                'messages': messages,
                'exported_at': datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"Error exporting messages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/events', methods=['GET'])
def api_export_events():
    """Export all events (messages, deletions, edits, friends) to JSON."""
    try:
        account_id = request.args.get('account_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid start_date format'}), 400
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid end_date format'}), 400
        
        db = get_database()
        
        # Get all event types
        messages = db.get_messages(account_id=account_id, limit=10000, start_date=start_dt, end_date=end_dt)
        
        # Get deletions, edits, friend updates, attachments
        # Note: These methods need to be added to database.py or we use direct queries
        # For now, return messages and indicate other types need implementation
        
        return jsonify({
            'success': True,
            'messages': messages,
            'message_count': len(messages),
            'exported_at': datetime.now().isoformat(),
            'note': 'Additional event types (deletions, edits, friends) export coming soon'
        })
    except Exception as e:
        logger.error(f"Error exporting events: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/attachments', methods=['GET'])
def api_export_attachments():
    """Export attachments list to JSON or CSV."""
    try:
        format_type = request.args.get('format', 'json').lower()
        account_id = request.args.get('account_id')
        
        db = get_database()
        
        # Get attachments from database
        with db._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM attachments WHERE 1=1'
            params = []
            
            if account_id:
                query += ' AND account_id = ?'
                params.append(account_id)
            
            query += ' ORDER BY timestamp DESC'
            cursor.execute(query, params)
            rows = cursor.fetchall()
            attachments = [dict(row) for row in rows]
        
        if format_type == 'csv':
            import csv
            import io
            from flask import Response
            
            output = io.StringIO()
            if attachments:
                writer = csv.DictWriter(output, fieldnames=attachments[0].keys())
                writer.writeheader()
                writer.writerows(attachments)
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=attachments_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
            )
        else:  # JSON
            return jsonify({
                'success': True,
                'count': len(attachments),
                'attachments': attachments,
                'exported_at': datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"Error exporting attachments: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search/messages', methods=['GET'])
def api_search_messages():
    """Search messages using full-text search."""
    try:
        query = request.args.get('q', '')
        account_id = request.args.get('account_id')
        limit = request.args.get('limit', 100, type=int)
        
        if not query:
            return jsonify({'error': 'Search query is required'}), 400
        
        db = get_database()
        results = db.search_messages(query, account_id=account_id, limit=limit)
        
        return jsonify({
            'success': True,
            'query': query,
            'count': len(results),
            'results': results
        })
    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/filter/messages', methods=['GET'])
def api_filter_messages():
    """Filter messages by various criteria."""
    try:
        account_id = request.args.get('account_id')
        channel_id = request.args.get('channel_id')
        author_id = request.args.get('author_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid start_date format'}), 400
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                return jsonify({'error': 'Invalid end_date format'}), 400
        
        db = get_database()
        messages = db.get_messages(
            account_id=account_id,
            channel_id=channel_id,
            author_id=author_id,
            limit=limit,
            offset=offset,
            start_date=start_dt,
            end_date=end_dt
        )
        
        return jsonify({
            'success': True,
            'count': len(messages),
            'messages': messages,
            'offset': offset,
            'limit': limit
        })
    except Exception as e:
        logger.error(f"Error filtering messages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup/create', methods=['POST'])
def api_create_backup():
    """Create a manual backup of accounts.json."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        data = request.get_json() or {}
        encrypt = data.get('encrypt', False)
        
        backup_path = config.create_backup(encrypt=encrypt)
        
        return jsonify({
            'success': True,
            'backup_path': str(backup_path),
            'filename': backup_path.name,
            'encrypted': encrypt,
            'message': 'Backup created successfully'
        })
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup/list', methods=['GET'])
def api_list_backups():
    """List available backup files."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        backups = config.list_backups()
        
        return jsonify({
            'success': True,
            'backups': backups,
            'count': len(backups)
        })
    except Exception as e:
        logger.error(f"Error listing backups: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup/restore', methods=['POST'])
def api_restore_backup():
    """Restore accounts from a backup file."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        data = request.get_json()
        if not data or 'backup_path' not in data:
            return jsonify({'error': 'backup_path is required'}), 400
        
        backup_path = Path(data['backup_path'])
        encrypted = data.get('encrypted', False)
        
        success = config.restore_backup(backup_path, encrypted=encrypted)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Backup restored successfully. Please restart the application.'
            })
        else:
            return jsonify({'error': 'Failed to restore backup'}), 500
            
    except Exception as e:
        logger.error(f"Error restoring backup: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/accounts', methods=['GET'])
def api_export_accounts():
    """Export account configurations (sanitized, no tokens)."""
    try:
        if not config:
            return jsonify({'error': 'Configuration not loaded'}), 500
        
        accounts = config.get_accounts()
        active_account_id = config.get_active_account_id()
        
        # Sanitize accounts (remove tokens)
        safe_accounts = {}
        for account_id, account_data in accounts.items():
            safe_accounts[account_id] = {
                'id': account_id,
                'name': account_data.get('name', 'Unknown'),
                'created_at': account_data.get('created_at'),
                'last_used': account_data.get('last_used'),
                'settings': account_data.get('settings', {}),
                'active': account_id == active_account_id,
                'webhook_urls': {
                    'friend': '***' if account_data.get('webhook_urls', {}).get('friend') else None,
                    'message': '***' if account_data.get('webhook_urls', {}).get('message') else None,
                    'command': '***' if account_data.get('webhook_urls', {}).get('command') else None
                }
            }
        
        return jsonify({
            'success': True,
            'accounts': safe_accounts,
            'active_account': active_account_id,
            'exported_at': datetime.now().isoformat(),
            'note': 'Tokens and webhook URLs are redacted for security'
        })
    except Exception as e:
        logger.error(f"Error exporting accounts: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/restart', methods=['POST'])
def api_restart_server():
    """Restart both the web server and selfbot process using start_all.py."""
    try:
        logger.info("Server and selfbot restart requested via API")
        
        # Schedule restart after a short delay
        def restart_all():
            import time
            import subprocess
            import psutil
            import os
            
            time.sleep(1)  # Give time for response to be sent
            logger.info("Stopping all processes and restarting with start_all.py...")
            
            # Find and terminate both main.py and start_web_server.py processes
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    if proc.info['name'] == 'python.exe' and proc.info['cmdline']:
                        cmdline = ' '.join(proc.info['cmdline'])
                        if 'main.py' in cmdline or 'start_web_server.py' in cmdline:
                            logger.info(f"Terminating process: {proc.info['pid']} - {cmdline}")
                            try:
                                proc.terminate()
                                proc.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                logger.warning(f"Force killing process: {proc.info['pid']}")
                                proc.kill()
            except Exception as e:
                logger.warning(f"Could not terminate processes: {e}")
            
            # Start the launcher script
            try:
                main_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                start_all_path = os.path.join(main_dir, 'start_all.py')
                
                if os.path.exists(start_all_path):
                    # Use start_all.py if it exists
                    subprocess.Popen(['python', 'start_all.py'], cwd=main_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    logger.info("Restarted using start_all.py")
                else:
                    # Fallback to individual restarts
                    subprocess.Popen(['python', 'start_web_server.py'], cwd=main_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    time.sleep(2)  # Wait for web server to start
                    subprocess.Popen(['python', 'main.py'], cwd=main_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    logger.info("Restarted individual processes")
                    
            except Exception as e:
                logger.error(f"Failed to restart processes: {e}")
            
            # Exit current process
            os._exit(0)
        
        import threading
        restart_thread = threading.Thread(target=restart_all)
        restart_thread.daemon = True
        restart_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Server and selfbot restart initiated using start_all.py'
        })
    except Exception as e:
        logger.error(f"Error restarting server: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    try:
        # Initialize components
        initialize_components()
        
        # Create templates and static directories
        templates_dir = Path(__file__).parent / 'templates'
        static_dir = Path(__file__).parent / 'static'
        templates_dir.mkdir(exist_ok=True)
        static_dir.mkdir(exist_ok=True)
        
        logger.info("Starting Discord Logger Web Dashboard...")
        
        # Run the server
        port = int(os.environ.get('WEB_PORT', 5002))
        debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        
        socketio.run(app, 
                    host='0.0.0.0', 
                    port=port, 
                    debug=debug,
                    allow_unsafe_werkzeug=True)
        
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
        sys.exit(1)