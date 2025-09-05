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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import requests

# Import our modules
from config import get_config, ConfigurationError
from rate_limiter import get_rate_limiter, RateLimitType
from security import SecurityMonitor, log_security_event

from async_wrapper import get_async_wrapper

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

# Settings storage
settings = {
    'webhook_enabled': True
}

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
            # For web server, we can use basic config without token validation
            from config import ConfigManager
            config_manager = ConfigManager()
            config = config_manager.config
            logger.warning(f"Using basic config due to validation error: {e}")
        
        logger.info("Configuration loaded successfully")
        
        # Initialize rate limiter
        rate_limiter = get_rate_limiter()
        logger.info("Rate limiter initialized")
        
        # Initialize security monitor
        security_monitor = SecurityMonitor()
        logger.info("Security monitor initialized")
        
        # Initialize event store with current active account
        initialize_event_store_account()
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        raise

# Routes
@app.route('/')
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/status')
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

@app.route('/api/config')
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
        
        return jsonify({
            'success': True,
            'settings': settings
        })
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
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
            
            # Signal main application to restart selfbot with new account
            try:
                import os
                signal_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'account_switch_signal.json')
                signal_data = {
                    'account_id': account_id,
                    'timestamp': datetime.now().isoformat(),
                    'action': 'switch_account'
                }
                with open(signal_file, 'w') as f:
                    json.dump(signal_data, f)
                logger.info(f"Created account switch signal for main application: {account_id}")
            except Exception as e:
                logger.error(f"Failed to create account switch signal: {e}")
            
            # Emit event to notify clients about account switch
            socketio.emit('account_switched', {
                'account_id': account_id,
                'timestamp': datetime.now().isoformat()
            })
            
            return jsonify({
                'success': True,
                'active_account': account_id,
                'message': 'Account switched successfully - selfbot will restart with new token'
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
        port = int(os.environ.get('WEB_PORT', 5000))
        debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        
        socketio.run(app, 
                    host='0.0.0.0', 
                    port=port, 
                    debug=debug,
                    allow_unsafe_werkzeug=True)
        
    except Exception as e:
        logger.error(f"Failed to start web server: {e}")
        sys.exit(1)