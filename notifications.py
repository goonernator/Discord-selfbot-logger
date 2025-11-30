"""Notification system for Discord Selfbot Logger.

This module provides configurable notification rules for various events
with support for email, webhook, and desktop notifications.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, time as dt_time
from pathlib import Path
from enum import Enum
import requests

logger = logging.getLogger(__name__)

class NotificationType(Enum):
    """Types of notifications."""
    EMAIL = "email"
    WEBHOOK = "webhook"
    DESKTOP = "desktop"

class NotificationRule:
    """Represents a notification rule."""
    
    def __init__(
        self,
        rule_id: str,
        name: str,
        event_types: List[str],
        conditions: Dict[str, Any],
        notification_type: NotificationType,
        target: str,
        enabled: bool = True,
        quiet_hours_start: Optional[dt_time] = None,
        quiet_hours_end: Optional[dt_time] = None,
        throttle_seconds: int = 0
    ):
        """Initialize notification rule.
        
        Args:
            rule_id: Unique rule ID
            name: Rule name
            event_types: List of event types to trigger on (message, deletion, edit, friend, etc.)
            conditions: Conditions dictionary (e.g., {'author_id': '123', 'channel_id': '456'})
            notification_type: Type of notification
            target: Target address/URL (email, webhook URL, etc.)
            enabled: Whether rule is enabled
            quiet_hours_start: Start of quiet hours (24-hour format)
            quiet_hours_end: End of quiet hours (24-hour format)
            throttle_seconds: Minimum seconds between notifications
        """
        self.rule_id = rule_id
        self.name = name
        self.event_types = event_types
        self.conditions = conditions
        self.notification_type = notification_type
        self.target = target
        self.enabled = enabled
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.throttle_seconds = throttle_seconds
        self.last_notification_time: Dict[str, float] = {}
    
    def matches(self, event_type: str, event_data: Dict[str, Any]) -> bool:
        """Check if rule matches an event.
        
        Args:
            event_type: Type of event
            event_data: Event data dictionary
            
        Returns:
            True if rule matches
        """
        if not self.enabled:
            return False
        
        if event_type not in self.event_types:
            return False
        
        # Check conditions
        for key, value in self.conditions.items():
            if key not in event_data:
                return False
            if event_data[key] != value:
                return False
        
        # Check quiet hours
        if self.quiet_hours_start and self.quiet_hours_end:
            now = datetime.now().time()
            if self.quiet_hours_start <= self.quiet_hours_end:
                # Normal case: start < end
                if self.quiet_hours_start <= now <= self.quiet_hours_end:
                    return False
            else:
                # Wraps midnight: start > end
                if now >= self.quiet_hours_start or now <= self.quiet_hours_end:
                    return False
        
        # Check throttle
        if self.throttle_seconds > 0:
            last_time = self.last_notification_time.get(event_type, 0)
            if time.time() - last_time < self.throttle_seconds:
                return False
        
        return True
    
    def record_notification(self, event_type: str):
        """Record that a notification was sent."""
        self.last_notification_time[event_type] = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert rule to dictionary."""
        return {
            'rule_id': self.rule_id,
            'name': self.name,
            'event_types': self.event_types,
            'conditions': self.conditions,
            'notification_type': self.notification_type.value,
            'target': self.target,
            'enabled': self.enabled,
            'quiet_hours_start': self.quiet_hours_start.isoformat() if self.quiet_hours_start else None,
            'quiet_hours_end': self.quiet_hours_end.isoformat() if self.quiet_hours_end else None,
            'throttle_seconds': self.throttle_seconds
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NotificationRule':
        """Create rule from dictionary."""
        quiet_start = None
        quiet_end = None
        if data.get('quiet_hours_start'):
            quiet_start = dt_time.fromisoformat(data['quiet_hours_start'])
        if data.get('quiet_hours_end'):
            quiet_end = dt_time.fromisoformat(data['quiet_hours_end'])
        
        return cls(
            rule_id=data['rule_id'],
            name=data['name'],
            event_types=data['event_types'],
            conditions=data['conditions'],
            notification_type=NotificationType(data['notification_type']),
            target=data['target'],
            enabled=data.get('enabled', True),
            quiet_hours_start=quiet_start,
            quiet_hours_end=quiet_end,
            throttle_seconds=data.get('throttle_seconds', 0)
        )

class NotificationManager:
    """Manages notification rules and sending notifications."""
    
    def __init__(self, config_file: Optional[Path] = None):
        """Initialize notification manager.
        
        Args:
            config_file: Path to notification rules file
        """
        self.config_file = config_file or Path(__file__).parent / 'notification_rules.json'
        self.rules: List[NotificationRule] = []
        self.load_rules()
    
    def load_rules(self):
        """Load notification rules from file."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.rules = [NotificationRule.from_dict(rule_data) for rule_data in data.get('rules', [])]
                logger.info(f"Loaded {len(self.rules)} notification rules")
            else:
                self.rules = []
                logger.info("No notification rules file found, starting with empty rules")
        except Exception as e:
            logger.error(f"Failed to load notification rules: {e}")
            self.rules = []
    
    def save_rules(self):
        """Save notification rules to file."""
        try:
            data = {
                'rules': [rule.to_dict() for rule in self.rules],
                'updated_at': datetime.now().isoformat()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(self.rules)} notification rules")
        except Exception as e:
            logger.error(f"Failed to save notification rules: {e}")
    
    def add_rule(self, rule: NotificationRule) -> bool:
        """Add a notification rule.
        
        Args:
            rule: Notification rule to add
            
        Returns:
            True if successful
        """
        # Check for duplicate rule_id
        if any(r.rule_id == rule.rule_id for r in self.rules):
            logger.warning(f"Rule with ID {rule.rule_id} already exists")
            return False
        
        self.rules.append(rule)
        self.save_rules()
        logger.info(f"Added notification rule: {rule.name}")
        return True
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a notification rule.
        
        Args:
            rule_id: Rule ID to remove
            
        Returns:
            True if successful
        """
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        
        if len(self.rules) < original_count:
            self.save_rules()
            logger.info(f"Removed notification rule: {rule_id}")
            return True
        else:
            logger.warning(f"Rule {rule_id} not found")
            return False
    
    def send_notification(self, notification_type: NotificationType, target: str, 
                         title: str, message: str, event_data: Optional[Dict[str, Any]] = None) -> bool:
        """Send a notification.
        
        Args:
            notification_type: Type of notification
            target: Target address/URL
            title: Notification title
            message: Notification message
            event_data: Optional event data
            
        Returns:
            True if successful
        """
        try:
            if notification_type == NotificationType.WEBHOOK:
                return self._send_webhook_notification(target, title, message, event_data)
            elif notification_type == NotificationType.EMAIL:
                return self._send_email_notification(target, title, message)
            elif notification_type == NotificationType.DESKTOP:
                return self._send_desktop_notification(title, message)
            else:
                logger.warning(f"Unknown notification type: {notification_type}")
                return False
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    def _send_webhook_notification(self, webhook_url: str, title: str, 
                                   message: str, event_data: Optional[Dict[str, Any]] = None) -> bool:
        """Send webhook notification."""
        try:
            embed = {
                'title': title,
                'description': message,
                'color': 0x3498db,
                'timestamp': datetime.now().isoformat()
            }
            
            if event_data:
                # Add fields from event data
                fields = []
                for key, value in event_data.items():
                    if key not in ['content', 'description'] and value:
                        fields.append({
                            'name': key.replace('_', ' ').title(),
                            'value': str(value)[:1024],
                            'inline': True
                        })
                if fields:
                    embed['fields'] = fields[:25]  # Discord limit
            
            payload = {'embeds': [embed]}
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            return False
    
    def _send_email_notification(self, email: str, title: str, message: str) -> bool:
        """Send email notification (placeholder - requires email service)."""
        logger.warning("Email notifications not yet implemented - requires email service configuration")
        # TODO: Implement email sending with SMTP or email service
        return False
    
    def _send_desktop_notification(self, title: str, message: str) -> bool:
        """Send desktop notification."""
        try:
            # Try using plyer for cross-platform desktop notifications
            try:
                from plyer import notification
                notification.notify(
                    title=title,
                    message=message[:200],  # Truncate for desktop notifications
                    timeout=10
                )
                return True
            except ImportError:
                logger.warning("plyer not installed, desktop notifications unavailable")
                return False
        except Exception as e:
            logger.error(f"Failed to send desktop notification: {e}")
            return False
    
    def process_event(self, event_type: str, event_data: Dict[str, Any]):
        """Process an event and send notifications for matching rules.
        
        Args:
            event_type: Type of event
            event_data: Event data dictionary
        """
        for rule in self.rules:
            if rule.matches(event_type, event_data):
                try:
                    # Build notification message
                    title = f"{event_type.title()} Event"
                    message = f"Event: {event_type}\n"
                    
                    # Add relevant data to message
                    if 'author' in event_data:
                        message += f"Author: {event_data['author']}\n"
                    if 'content' in event_data:
                        content = str(event_data['content'])[:200]
                        message += f"Content: {content}\n"
                    if 'channel_id' in event_data:
                        message += f"Channel: {event_data['channel_id']}\n"
                    
                    # Send notification
                    success = self.send_notification(
                        rule.notification_type,
                        rule.target,
                        title,
                        message,
                        event_data
                    )
                    
                    if success:
                        rule.record_notification(event_type)
                        logger.info(f"Sent notification for {event_type} via rule {rule.name}")
                except Exception as e:
                    logger.error(f"Error processing notification rule {rule.rule_id}: {e}")

# Global notification manager instance
_notification_manager: Optional[NotificationManager] = None

def get_notification_manager() -> NotificationManager:
    """Get global notification manager instance."""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager

