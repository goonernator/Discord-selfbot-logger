#!/usr/bin/env python3
"""
Web Dashboard Integration Module

Integrates the Discord selfbot logger with the web dashboard
by sending events to the web server in real-time.
"""

import asyncio
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

import aiohttp
import requests

logger = logging.getLogger(__name__)

class WebDashboardIntegration:
    """Handles integration between Discord bot and web dashboard."""
    
    def __init__(self, dashboard_url: str = "http://localhost:5000", enabled: bool = True):
        self.dashboard_url = dashboard_url.rstrip('/')
        self.enabled = enabled
        self.session = None
        self.event_queue = asyncio.Queue() if enabled else None
        self.worker_task = None
        
        if enabled:
            logger.info(f"Web dashboard integration enabled: {self.dashboard_url}")
        else:
            logger.info("Web dashboard integration disabled")
    
    async def start(self):
        """Start the web integration service."""
        if not self.enabled:
            return
        
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
            
            # Start event worker
            self.worker_task = asyncio.create_task(self._event_worker())
            
            # Test connection
            await self._test_connection()
            
            logger.info("Web dashboard integration started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start web dashboard integration: {e}")
            await self.stop()
    
    async def stop(self):
        """Stop the web integration service."""
        if not self.enabled:
            return
        
        try:
            # Cancel worker task
            if self.worker_task and not self.worker_task.done():
                self.worker_task.cancel()
                try:
                    await self.worker_task
                except asyncio.CancelledError:
                    pass
            
            # Close HTTP session
            if self.session and not self.session.closed:
                await self.session.close()
            
            logger.info("Web dashboard integration stopped")
            
        except Exception as e:
            logger.error(f"Error stopping web dashboard integration: {e}")
    
    async def _test_connection(self):
        """Test connection to the web dashboard."""
        try:
            async with self.session.get(f"{self.dashboard_url}/api/status") as response:
                if response.status == 200:
                    logger.info("Successfully connected to web dashboard")
                else:
                    logger.warning(f"Web dashboard returned status {response.status}")
        except Exception as e:
            logger.warning(f"Could not connect to web dashboard: {e}")
    
    async def _event_worker(self):
        """Worker task that processes events from the queue."""
        while True:
            try:
                # Get event from queue (wait up to 1 second)
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                
                # Send event to dashboard
                await self._send_event(event)
                
                # Mark task as done
                self.event_queue.task_done()
                
            except asyncio.TimeoutError:
                # No events in queue, continue
                continue
            except asyncio.CancelledError:
                # Task was cancelled
                break
            except Exception as e:
                logger.error(f"Error in event worker: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying
    
    async def _send_event(self, event: Dict[str, Any]):
        """Send an event to the web dashboard."""
        if not self.session or self.session.closed:
            return
        
        try:
            async with self.session.post(
                f"{self.dashboard_url}/api/events",
                json=event,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent {event['type']} event to dashboard")
                else:
                    logger.warning(f"Dashboard returned status {response.status} for event")
                    
        except Exception as e:
            logger.error(f"Failed to send event to dashboard: {e}")
    
    def log_message_event(self, author: str, content: str, channel_id: str, 
                         message_id: str, attachments: list = None):
        """Log a message event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'message',
            'data': {
                'author': author,
                'content': content[:500] + '...' if len(content) > 500 else content,
                'channel_id': channel_id,
                'message_id': message_id,
                'has_attachments': bool(attachments),
                'attachment_count': len(attachments) if attachments else 0
            }
        }
        
        self._queue_event(event)
    
    def log_mention_event(self, author: str, content: str, channel_id: str, message_id: str):
        """Log a mention event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'mention',
            'data': {
                'author': author,
                'content': content[:200] + '...' if len(content) > 200 else content,
                'channel_id': channel_id,
                'message_id': message_id
            }
        }
        
        self._queue_event(event)
    
    def log_deletion_event(self, author: str, content: str, channel_id: str, message_id: str):
        """Log a message deletion event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'deletion',
            'data': {
                'author': author,
                'content': content[:200] + '...' if len(content) > 200 else content,
                'channel_id': channel_id,
                'message_id': message_id
            }
        }
        
        self._queue_event(event)
    
    def log_friend_event(self, action: str, user_id: str, username: str = None):
        """Log a friend-related event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'friend',
            'data': {
                'action': action,
                'user_id': user_id,
                'username': username or f'User {user_id}'
            }
        }
        
        self._queue_event(event)
    
    def log_attachment_event(self, filename: str, size: int, url: str, success: bool):
        """Log an attachment download event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'attachment',
            'data': {
                'filename': filename,
                'size': size,
                'url': url,
                'success': success
            }
        }
        
        self._queue_event(event)
    
    def log_performance_event(self, operation: str, duration: float, success: bool, 
                            metadata: Dict[str, Any] = None):
        """Log a performance event."""
        if not self.enabled:
            return
        
        event = {
            'type': 'performance',
            'data': {
                'operation': operation,
                'duration': duration,
                'success': success,
                'metadata': metadata or {}
            }
        }
        
        self._queue_event(event)
    
    def _queue_event(self, event: Dict[str, Any]):
        """Queue an event for sending to the dashboard."""
        if not self.enabled or not self.event_queue:
            return
        
        # Add timestamp
        event['timestamp'] = datetime.now().isoformat()
        
        try:
            # Try to add to queue (non-blocking)
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Event queue is full, dropping event")
        except Exception as e:
            logger.error(f"Failed to queue event: {e}")

# Global instance
_web_integration = None

def get_web_integration(dashboard_url: str = None, enabled: bool = True) -> WebDashboardIntegration:
    """Get or create the global web integration instance."""
    global _web_integration
    
    if _web_integration is None:
        url = dashboard_url or "http://127.0.0.1:5002"
        _web_integration = WebDashboardIntegration(url, enabled)
    
    return _web_integration

async def start_web_integration(dashboard_url: str = None, enabled: bool = True):
    """Start the web integration service."""
    integration = get_web_integration(dashboard_url, enabled)
    await integration.start()
    return integration

async def stop_web_integration():
    """Stop the web integration service."""
    global _web_integration
    
    if _web_integration:
        await _web_integration.stop()
        _web_integration = None

# Convenience functions for logging events
def log_message(author: str, content: str, channel_id: str, channel_name: str, message_id: str, attachments: list = None):
    """Log a message event to the web dashboard."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"log_message called: author={author}, channel_id={channel_id}, channel_name={channel_name}, message_id={message_id}")
    
    # Use synchronous integration for immediate sending
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    
    event_data = {
        'author': author,
        'content': content[:500] + '...' if len(content) > 500 else content,
        'channel_id': channel_id,
        'channel_name': channel_name,
        'message_id': message_id,
        'has_attachments': bool(attachments),
        'attachment_count': len(attachments) if attachments else 0
    }
    
    sync_integration.log_event_sync('message', event_data)
    logger.info(f"Message event sent to dashboard: {message_id}")

def log_mention(author: str, content: str, channel_id: str, channel_name: str, message_id: str):
    """Log a mention event to the web dashboard."""
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    event_data = {
        'author': author,
        'content': content[:200] + '...' if len(content) > 200 else content,
        'channel_id': channel_id,
        'channel_name': channel_name,
        'message_id': message_id
    }
    sync_integration.log_event_sync('mention', event_data)

def log_deletion(author: str, content: str, channel_id: str, channel_name: str, message_id: str):
    """Log a deletion event to the web dashboard."""
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    event_data = {
        'author': author,
        'content': content[:200] + '...' if len(content) > 200 else content,
        'channel_id': channel_id,
        'channel_name': channel_name,
        'message_id': message_id
    }
    sync_integration.log_event_sync('deletion', event_data)

def log_friend_update(action: str, user_id: str, user_data, relationship_type: str = None):
    """Log a friend update event to the web dashboard with enhanced user information."""
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    
    # Handle both old format (string) and new format (dict) for backward compatibility
    if isinstance(user_data, str):
        event_data = {
            'action': action,
            'user_id': user_id,
            'username': user_data or f'User {user_id}',
            'relationship_type': relationship_type
        }
    else:
        event_data = {
            'action': action,
            'user_id': user_id,
            'username': user_data.get('username', 'Unknown'),
            'discriminator': user_data.get('discriminator', '0000'),
            'display_name': user_data.get('display_name'),
            'avatar_url': user_data.get('avatar_url'),
            'user_tag': user_data.get('user_tag', f'User {user_id}'),
            'relationship_type': relationship_type
        }
    
    sync_integration.log_event_sync('friend', event_data)

def log_attachment_download(filename: str, size: int, url: str, success: bool):
    """Log an attachment download event to the web dashboard."""
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    event_data = {
        'filename': filename,
        'size': size,
        'success': success
    }
    sync_integration.log_event_sync('attachment', event_data)

def log_performance(operation: str, duration: float, success: bool, metadata: Dict[str, Any] = None):
    """Log a performance event to the web dashboard."""
    sync_integration = get_sync_web_integration("http://127.0.0.1:5002", True)
    event_data = {
        'operation': operation,
        'duration': duration,
        'success': success,
        'metadata': metadata or {}
    }
    sync_integration.log_event_sync('performance', event_data)

# Synchronous fallback for non-async contexts
class SyncWebIntegration:
    """Synchronous wrapper for web integration."""
    
    def __init__(self, dashboard_url: str = "http://localhost:5000", enabled: bool = True):
        self.dashboard_url = dashboard_url.rstrip('/')
        self.enabled = enabled
        
        if enabled:
            logger.info(f"Sync web dashboard integration enabled: {self.dashboard_url}")
    
    def send_event_sync(self, event: Dict[str, Any]):
        """Send an event synchronously."""
        if not self.enabled:
            return
        
        try:
            response = requests.post(
                f"{self.dashboard_url}/api/events",
                json=event,
                timeout=5,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                logger.debug(f"Successfully sent {event['type']} event to dashboard (sync)")
            else:
                logger.warning(f"Dashboard returned status {response.status_code} for event (sync)")
                
        except Exception as e:
            logger.error(f"Failed to send event to dashboard (sync): {e}")
    
    def log_event_sync(self, event_type: str, data: Dict[str, Any]):
        """Log an event synchronously."""
        event = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        
        self.send_event_sync(event)

# Global sync instance
_sync_web_integration = None

def get_sync_web_integration(dashboard_url: str = None, enabled: bool = True) -> SyncWebIntegration:
    """Get or create the global sync web integration instance."""
    global _sync_web_integration
    
    if _sync_web_integration is None:
        url = dashboard_url or "http://127.0.0.1:5002"
        _sync_web_integration = SyncWebIntegration(url, enabled)
    
    return _sync_web_integration