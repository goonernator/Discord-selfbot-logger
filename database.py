"""Database persistence module for Discord Selfbot Logger.

This module provides SQLite-based storage for events, messages, and other data
with proper indexing, migrations, and data retention policies.
"""

import os
import sqlite3
import logging
import json
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
import threading

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    """Raised when there's a database-related error."""
    pass

class Database:
    """SQLite database manager for Discord logger events."""
    
    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.
        
        Args:
            db_path: Path to database file. Defaults to 'discord_logger.db' in script directory.
        """
        self.db_path = db_path or Path(__file__).parent / 'discord_logger.db'
        self._lock = threading.RLock()
        self._connection = None
        self._ensure_database()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper locking."""
        with self._lock:
            if self._connection is None:
                self._connection = sqlite3.connect(
                    str(self.db_path),
                    check_same_thread=False,
                    timeout=30.0
                )
                self._connection.row_factory = sqlite3.Row
                # Enable WAL mode for better concurrency
                self._connection.execute('PRAGMA journal_mode=WAL')
                self._connection.execute('PRAGMA foreign_keys=ON')
            
            try:
                yield self._connection
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                raise DatabaseError(f"Database operation failed: {e}")
    
    def _ensure_database(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_tag TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    channel_name TEXT,
                    content TEXT,
                    guild_id TEXT,
                    is_dm BOOLEAN DEFAULT 0,
                    is_group_chat BOOLEAN DEFAULT 0,
                    is_mention BOOLEAN DEFAULT 0,
                    is_bot BOOLEAN DEFAULT 0,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(message_id, account_id)
                )
            ''')
            
            # Message edits table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_edits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    original_content TEXT,
                    edited_content TEXT,
                    author_tag TEXT,
                    channel_id TEXT,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES messages(message_id)
                )
            ''')
            
            # Message deletions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    author_tag TEXT,
                    content TEXT,
                    channel_id TEXT,
                    channel_name TEXT,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Friend updates table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS friend_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    discriminator TEXT,
                    display_name TEXT,
                    action TEXT NOT NULL,
                    relationship_type TEXT,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Attachments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_path TEXT,
                    file_size INTEGER,
                    url TEXT,
                    message_id TEXT,
                    author_tag TEXT,
                    channel_id TEXT,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Duplicate messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS duplicate_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    duplicate_id TEXT NOT NULL,
                    original_msg_id TEXT NOT NULL,
                    duplicate_msg_id TEXT NOT NULL,
                    original_author TEXT NOT NULL,
                    duplicate_author TEXT NOT NULL,
                    content TEXT,
                    channel_id TEXT NOT NULL,
                    account_id TEXT,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(duplicate_id)
                )
            ''')
            
            # Create indexes for common queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_account ON messages(account_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id)')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_deletions_timestamp ON message_deletions(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_deletions_account ON message_deletions(account_id)')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_edits_timestamp ON message_edits(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_edits_account ON message_edits(account_id)')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_friends_timestamp ON friend_updates(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_friends_account ON friend_updates(account_id)')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_attachments_timestamp ON attachments(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_attachments_account ON attachments(account_id)')
            
            # Full-text search index for messages (using FTS5 if available)
            try:
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        message_id, content, author_tag, channel_name,
                        content=messages, content_rowid=id
                    )
                ''')
            except sqlite3.OperationalError:
                logger.warning("FTS5 not available, full-text search disabled")
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def insert_message(self, message_id: str, author_id: str, author_tag: str, 
                      channel_id: str, channel_name: Optional[str], content: str,
                      guild_id: Optional[str] = None, is_dm: bool = False,
                      is_group_chat: bool = False, is_mention: bool = False,
                      is_bot: bool = False, account_id: Optional[str] = None,
                      timestamp: Optional[datetime] = None) -> bool:
        """Insert a message into the database.
        
        Args:
            message_id: Discord message ID
            author_id: Author user ID
            author_tag: Author tag (username#discriminator)
            channel_id: Channel ID
            channel_name: Channel name
            content: Message content
            guild_id: Guild ID (if server message)
            is_dm: Whether it's a DM
            is_group_chat: Whether it's a group chat
            is_mention: Whether user was mentioned
            is_bot: Whether author is a bot
            account_id: Account ID that received the message
            timestamp: Message timestamp (defaults to now)
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO messages 
                    (message_id, author_id, author_tag, channel_id, channel_name, content,
                     guild_id, is_dm, is_group_chat, is_mention, is_bot, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (message_id, author_id, author_tag, channel_id, channel_name, content,
                      guild_id, 1 if is_dm else 0, 1 if is_group_chat else 0,
                      1 if is_mention else 0, 1 if is_bot else 0, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert message: {e}")
            return False
    
    def insert_message_edit(self, message_id: str, original_content: str,
                           edited_content: str, author_tag: str, channel_id: str,
                           account_id: Optional[str] = None,
                           timestamp: Optional[datetime] = None) -> bool:
        """Insert a message edit record.
        
        Args:
            message_id: Discord message ID
            original_content: Original message content
            edited_content: Edited message content
            author_tag: Author tag
            channel_id: Channel ID
            account_id: Account ID
            timestamp: Edit timestamp
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO message_edits 
                    (message_id, original_content, edited_content, author_tag, channel_id, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (message_id, original_content, edited_content, author_tag, channel_id, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert message edit: {e}")
            return False
    
    def insert_message_deletion(self, message_id: str, author_tag: str, content: str,
                               channel_id: str, channel_name: Optional[str],
                               account_id: Optional[str] = None,
                               timestamp: Optional[datetime] = None) -> bool:
        """Insert a message deletion record.
        
        Args:
            message_id: Discord message ID
            author_tag: Author tag
            content: Message content (before deletion)
            channel_id: Channel ID
            channel_name: Channel name
            account_id: Account ID
            timestamp: Deletion timestamp
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO message_deletions 
                    (message_id, author_tag, content, channel_id, channel_name, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (message_id, author_tag, content, channel_id, channel_name, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert message deletion: {e}")
            return False
    
    def insert_friend_update(self, user_id: str, username: str, discriminator: str,
                           display_name: Optional[str], action: str,
                           relationship_type: Optional[str] = None,
                           account_id: Optional[str] = None,
                           timestamp: Optional[datetime] = None) -> bool:
        """Insert a friend update record.
        
        Args:
            user_id: User ID
            username: Username
            discriminator: Discriminator
            display_name: Display name
            action: Action (Added/Removed)
            relationship_type: Relationship type
            account_id: Account ID
            timestamp: Update timestamp
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO friend_updates 
                    (user_id, username, discriminator, display_name, action, relationship_type, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, username, discriminator, display_name, action, relationship_type, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert friend update: {e}")
            return False
    
    def insert_attachment(self, filename: str, file_path: Optional[str], file_size: int,
                         url: str, message_id: Optional[str], author_tag: str,
                         channel_id: str, account_id: Optional[str] = None,
                         timestamp: Optional[datetime] = None) -> bool:
        """Insert an attachment record.
        
        Args:
            filename: Filename
            file_path: Local file path
            file_size: File size in bytes
            url: Original URL
            message_id: Associated message ID
            author_tag: Author tag
            channel_id: Channel ID
            account_id: Account ID
            timestamp: Download timestamp
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO attachments 
                    (filename, file_path, file_size, url, message_id, author_tag, channel_id, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (filename, file_path, file_size, url, message_id, author_tag, channel_id, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert attachment: {e}")
            return False
    
    def insert_duplicate_message(self, duplicate_id: str, original_msg_id: str,
                                 duplicate_msg_id: str, original_author: str,
                                 duplicate_author: str, content: str, channel_id: str,
                                 account_id: Optional[str] = None,
                                 timestamp: Optional[datetime] = None) -> bool:
        """Insert a duplicate message record.
        
        Args:
            duplicate_id: Unique duplicate ID
            original_msg_id: Original message ID
            duplicate_msg_id: Duplicate message ID
            original_author: Original author tag
            duplicate_author: Duplicate author tag
            content: Message content
            channel_id: Channel ID
            account_id: Account ID
            timestamp: Detection timestamp
            
        Returns:
            True if successful
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO duplicate_messages 
                    (duplicate_id, original_msg_id, duplicate_msg_id, original_author,
                     duplicate_author, content, channel_id, account_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (duplicate_id, original_msg_id, duplicate_msg_id, original_author,
                      duplicate_author, content, channel_id, account_id, timestamp))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to insert duplicate message: {e}")
            return False
    
    def get_messages(self, account_id: Optional[str] = None, channel_id: Optional[str] = None,
                    author_id: Optional[str] = None, limit: int = 100,
                    offset: int = 0, start_date: Optional[datetime] = None,
                    end_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get messages with filters.
        
        Args:
            account_id: Filter by account ID
            channel_id: Filter by channel ID
            author_id: Filter by author ID
            limit: Maximum results
            offset: Offset for pagination
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            List of message dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = 'SELECT * FROM messages WHERE 1=1'
                params = []
                
                if account_id:
                    query += ' AND account_id = ?'
                    params.append(account_id)
                
                if channel_id:
                    query += ' AND channel_id = ?'
                    params.append(channel_id)
                
                if author_id:
                    query += ' AND author_id = ?'
                    params.append(author_id)
                
                if start_date:
                    query += ' AND timestamp >= ?'
                    params.append(start_date)
                
                if end_date:
                    query += ' AND timestamp <= ?'
                    params.append(end_date)
                
                query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
                params.extend([limit, offset])
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []
    
    def search_messages(self, search_term: str, account_id: Optional[str] = None,
                       limit: int = 100) -> List[Dict[str, Any]]:
        """Search messages using full-text search.
        
        Args:
            search_term: Search term
            account_id: Filter by account ID
            limit: Maximum results
            
        Returns:
            List of matching messages
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Try FTS5 search first
                try:
                    query = '''
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.message_id = fts.message_id
                        WHERE messages_fts MATCH ?
                    '''
                    params = [search_term]
                    
                    if account_id:
                        query += ' AND m.account_id = ?'
                        params.append(account_id)
                    
                    query += ' ORDER BY m.timestamp DESC LIMIT ?'
                    params.append(limit)
                    
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
                except sqlite3.OperationalError:
                    # Fallback to LIKE search if FTS5 not available
                    query = '''
                        SELECT * FROM messages
                        WHERE (content LIKE ? OR author_tag LIKE ? OR channel_name LIKE ?)
                    '''
                    params = [f'%{search_term}%', f'%{search_term}%', f'%{search_term}%']
                    
                    if account_id:
                        query += ' AND account_id = ?'
                        params.append(account_id)
                    
                    query += ' ORDER BY timestamp DESC LIMIT ?'
                    params.append(limit)
                    
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to search messages: {e}")
            return []
    
    def cleanup_old_data(self, retention_days: int = 90, account_id: Optional[str] = None):
        """Clean up old data based on retention policy.
        
        Args:
            retention_days: Number of days to retain data
            account_id: Optional account ID filter
        """
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                tables = ['messages', 'message_deletions', 'message_edits', 
                         'friend_updates', 'attachments', 'duplicate_messages']
                
                for table in tables:
                    query = f'DELETE FROM {table} WHERE timestamp < ?'
                    params = [cutoff_date]
                    
                    if account_id:
                        query = query.replace('WHERE', 'WHERE account_id = ? AND')
                        params.insert(0, account_id)
                    
                    cursor.execute(query, params)
                    deleted = cursor.rowcount
                    if deleted > 0:
                        logger.info(f"Cleaned up {deleted} old records from {table}")
                
                conn.commit()
                
                # Vacuum database to reclaim space
                cursor.execute('VACUUM')
                logger.info("Database cleanup completed")
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
    
    def get_statistics(self, account_id: Optional[str] = None,
                      start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Get database statistics.
        
        Args:
            account_id: Filter by account ID
            start_date: Start date filter
            end_date: End date filter
            
        Returns:
            Dictionary with statistics
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                stats = {}
                
                # Build WHERE clause
                where_clause = 'WHERE 1=1'
                params = []
                
                if account_id:
                    where_clause += ' AND account_id = ?'
                    params.append(account_id)
                
                if start_date:
                    where_clause += ' AND timestamp >= ?'
                    params.append(start_date)
                
                if end_date:
                    where_clause += ' AND timestamp <= ?'
                    params.append(end_date)
                
                # Count messages
                cursor.execute(f'SELECT COUNT(*) FROM messages {where_clause}', params)
                stats['total_messages'] = cursor.fetchone()[0]
                
                # Count deletions
                cursor.execute(f'SELECT COUNT(*) FROM message_deletions {where_clause}', params)
                stats['total_deletions'] = cursor.fetchone()[0]
                
                # Count edits
                cursor.execute(f'SELECT COUNT(*) FROM message_edits {where_clause}', params)
                stats['total_edits'] = cursor.fetchone()[0]
                
                # Count friend updates
                cursor.execute(f'SELECT COUNT(*) FROM friend_updates {where_clause}', params)
                stats['total_friend_updates'] = cursor.fetchone()[0]
                
                # Count attachments
                cursor.execute(f'SELECT COUNT(*) FROM attachments {where_clause}', params)
                stats['total_attachments'] = cursor.fetchone()[0]
                
                # Total attachment size
                cursor.execute(f'SELECT SUM(file_size) FROM attachments {where_clause}', params)
                result = cursor.fetchone()[0]
                stats['total_attachment_size'] = result or 0
                
                return stats
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def close(self):
        """Close database connection."""
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
                logger.info("Database connection closed")

# Global database instance
_db_instance: Optional[Database] = None

def get_database(db_path: Optional[Path] = None) -> Database:
    """Get global database instance.
    
    Args:
        db_path: Optional custom database path
        
    Returns:
        Database instance
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance

