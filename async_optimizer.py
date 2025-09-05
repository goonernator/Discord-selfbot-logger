"""Async optimization module for Discord Selfbot Logger.

This module provides async/await implementations for performance-critical operations
including network requests, file I/O, and concurrent message processing.
"""

import asyncio
import aiohttp
import aiofiles
import logging
import time
from typing import Optional, Dict, Any, List, Tuple, Callable
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from rate_limiter import async_wait_for_webhook, async_wait_for_api, async_wait_for_download
from security import InputSanitizer, SecurityMonitor, log_security_event

logger = logging.getLogger(__name__)

@dataclass
class AsyncConfig:
    """Configuration for async operations."""
    max_concurrent_downloads: int = 5
    max_concurrent_webhooks: int = 3
    connection_timeout: float = 10.0
    read_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    semaphore_timeout: float = 60.0

class AsyncWebhookSender:
    """Async webhook sender with connection pooling and rate limiting."""
    
    def __init__(self, config: AsyncConfig = None):
        self.config = config or AsyncConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self.webhook_semaphore = asyncio.Semaphore(self.config.max_concurrent_webhooks)
        self._session_lock = asyncio.Lock()
    
    async def __aenter__(self):
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(
                    total=self.config.connection_timeout + self.config.read_timeout,
                    connect=self.config.connection_timeout,
                    sock_read=self.config.read_timeout
                )
                
                connector = aiohttp.TCPConnector(
                    limit=100,  # Total connection pool size
                    limit_per_host=10,  # Per-host connection limit
                    ttl_dns_cache=300,  # DNS cache TTL
                    use_dns_cache=True,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True
                )
                
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={'User-Agent': 'Discord-Logger-Async/1.0'}
                )
                
                logger.debug("Created new aiohttp session")
    
    async def send_embed(self, webhook_url: str, title: str, description: str, 
                        author_name: str = None, author_icon: str = None,
                        image_url: str = None, color: int = 0x7289da) -> bool:
        """Send embed to Discord webhook asynchronously.
        
        Args:
            webhook_url: Discord webhook URL
            title: Embed title
            description: Embed description
            author_name: Author name (optional)
            author_icon: Author icon URL (optional)
            image_url: Image URL (optional)
            color: Embed color (default Discord blue)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not webhook_url:
            return False
        
        # Rate limiting
        await async_wait_for_webhook()
        
        async with self.webhook_semaphore:
            try:
                await self._ensure_session()
                
                # Build embed
                embed = {
                    'title': title[:256],  # Discord limit
                    'description': description[:4096],  # Discord limit
                    'color': color,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
                }
                
                if author_name:
                    embed['author'] = {
                        'name': author_name[:256],
                        'icon_url': author_icon
                    }
                
                if image_url:
                    embed['image'] = {'url': image_url}
                
                payload = {'embeds': [embed]}
                
                # Send with retries
                for attempt in range(self.config.max_retries):
                    try:
                        async with self.session.post(webhook_url, json=payload) as response:
                            if response.status == 429:
                                # Rate limited by Discord
                                retry_after = float(response.headers.get('Retry-After', '1'))
                                logger.warning(f'Discord rate limited, waiting {retry_after}s')
                                await asyncio.sleep(retry_after)
                                continue
                            
                            response.raise_for_status()
                            logger.debug(f'Successfully sent embed: {title}')
                            return True
                            
                    except aiohttp.ClientError as e:
                        logger.warning(f'Webhook attempt {attempt + 1} failed: {e}')
                        if attempt < self.config.max_retries - 1:
                            await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                        continue
                
                logger.error(f'Failed to send webhook after {self.config.max_retries} attempts')
                return False
                
            except Exception as e:
                logger.error(f'Unexpected error sending webhook: {e}')
                return False
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("Closed aiohttp session")

class AsyncFileDownloader:
    """Async file downloader with concurrent downloads and progress tracking."""
    
    def __init__(self, config: AsyncConfig = None):
        self.config = config or AsyncConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self.download_semaphore = asyncio.Semaphore(self.config.max_concurrent_downloads)
        self._session_lock = asyncio.Lock()
        self.active_downloads: Dict[str, asyncio.Task] = {}
    
    async def __aenter__(self):
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(
                    total=self.config.read_timeout + 10,
                    connect=self.config.connection_timeout,
                    sock_read=self.config.read_timeout
                )
                
                connector = aiohttp.TCPConnector(
                    limit=50,
                    limit_per_host=10,
                    ttl_dns_cache=300,
                    use_dns_cache=True
                )
                
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={'User-Agent': 'Discord-Logger-Downloader/1.0'}
                )
    
    async def download_file(self, url: str, filepath: Path, 
                           max_size: int = None) -> Tuple[bool, Optional[str]]:
        """Download file asynchronously.
        
        Args:
            url: File URL to download
            filepath: Local file path to save
            max_size: Maximum file size in bytes (optional)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # Rate limiting
        await async_wait_for_download()
        
        # Security validation
        if not InputSanitizer.validate_url(url):
            return False, "Invalid or suspicious URL"
        
        async with self.download_semaphore:
            try:
                await self._ensure_session()
                
                # Create directory if needed
                filepath.parent.mkdir(parents=True, exist_ok=True)
                
                # Download with streaming
                async with self.session.get(url) as response:
                    if response.status == 429:
                        retry_after = float(response.headers.get('Retry-After', '1'))
                        logger.warning(f'Download rate limited, waiting {retry_after}s')
                        await asyncio.sleep(retry_after)
                        return False, "Rate limited"
                    
                    response.raise_for_status()
                    
                    # Check content length
                    content_length = response.headers.get('Content-Length')
                    if content_length and max_size:
                        if int(content_length) > max_size:
                            return False, f"File too large: {content_length} bytes"
                    
                    # Stream download
                    total_size = 0
                    async with aiofiles.open(filepath, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            total_size += len(chunk)
                            
                            # Check size limit during download
                            if max_size and total_size > max_size:
                                await f.close()
                                filepath.unlink(missing_ok=True)
                                return False, f"File too large: {total_size} bytes"
                            
                            await f.write(chunk)
                    
                    logger.info(f'Downloaded {filepath.name} ({total_size} bytes)')
                    return True, None
                    
            except aiohttp.ClientError as e:
                logger.error(f'Download failed for {url}: {e}')
                return False, str(e)
            except Exception as e:
                logger.error(f'Unexpected download error: {e}')
                return False, str(e)
    
    async def download_multiple(self, downloads: List[Tuple[str, Path, Optional[int]]]) -> List[Tuple[bool, Optional[str]]]:
        """Download multiple files concurrently.
        
        Args:
            downloads: List of (url, filepath, max_size) tuples
            
        Returns:
            List of (success, error_message) tuples
        """
        tasks = []
        for url, filepath, max_size in downloads:
            task = asyncio.create_task(self.download_file(url, filepath, max_size))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append((False, str(result)))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def close(self):
        """Close the session and cancel active downloads."""
        # Cancel active downloads
        for task in self.active_downloads.values():
            if not task.done():
                task.cancel()
        
        if self.active_downloads:
            await asyncio.gather(*self.active_downloads.values(), return_exceptions=True)
            self.active_downloads.clear()
        
        if self.session and not self.session.closed:
            await self.session.close()

class AsyncMessageProcessor:
    """Async message processor for handling Discord events concurrently."""
    
    def __init__(self, webhook_sender: AsyncWebhookSender, 
                 file_downloader: AsyncFileDownloader,
                 max_concurrent_messages: int = 10):
        self.webhook_sender = webhook_sender
        self.file_downloader = file_downloader
        self.message_semaphore = asyncio.Semaphore(max_concurrent_messages)
        self.processing_queue = asyncio.Queue(maxsize=1000)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AsyncMsg")
    
    async def process_message(self, message_data: Dict[str, Any], 
                            config: Dict[str, Any]) -> bool:
        """Process a Discord message asynchronously.
        
        Args:
            message_data: Discord message data
            config: Configuration dictionary
            
        Returns:
            bool: True if processed successfully
        """
        async with self.message_semaphore:
            try:
                # Extract message info
                author_id = message_data.get('author', {}).get('id', 'Unknown')
                channel_id = message_data.get('channel_id', 'Unknown')
                content = message_data.get('content', '')
                message_id = message_data.get('id', 'Unknown')
                attachments = message_data.get('attachments', [])
                
                # Security monitoring (non-blocking)
                asyncio.create_task(self._log_security_event(message_data))
                
                # Log to web integration (non-blocking)
                asyncio.create_task(self._log_web_event(message_data))
                
                # Process attachments concurrently
                download_tasks = []
                if attachments:
                    for attachment in attachments:
                        url = attachment.get('url')
                        filename = attachment.get('filename', f'attachment_{int(time.time())}')
                        
                        if url and filename:
                            # Sanitize filename
                            safe_filename = InputSanitizer.sanitize_filename(filename)
                            filepath = Path(config.get('ATTACH_DIR', 'attachments')) / safe_filename
                            max_size = config.get('ATTACHMENT_SIZE_LIMIT', 50 * 1024 * 1024)
                            
                            download_tasks.append((url, filepath, max_size))
                
                # Start downloads and webhook sending concurrently
                tasks = []
                
                # Download attachments
                if download_tasks:
                    download_task = asyncio.create_task(
                        self.file_downloader.download_multiple(download_tasks)
                    )
                    tasks.append(download_task)
                
                # Send webhook
                if content and config.get('MESSAGE_WEBHOOK'):
                    webhook_task = asyncio.create_task(
                        self.webhook_sender.send_embed(
                            config['MESSAGE_WEBHOOK'],
                            '💬 Message',
                            content[:4000],  # Truncate long messages
                            author_name=f"User {author_id}"
                        )
                    )
                    tasks.append(webhook_task)
                
                # Wait for all tasks to complete
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Log any exceptions
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f'Task {i} failed for message {message_id}: {result}')
                
                return True
                
            except Exception as e:
                logger.error(f'Error processing message {message_data.get("id", "unknown")}: {e}')
                return False
    
    async def _log_security_event(self, message_data: Dict[str, Any]):
        """Log security event asynchronously."""
        try:
            from security import log_security_event
            # Try both 'message_id' and 'id' keys for message ID
            msg_id = message_data.get('message_id') or message_data.get('id', 'Unknown')
            log_security_event('message_processed', {
                'message_id': str(msg_id),
                'author_id': str(message_data.get('author', {}).get('id', 'Unknown')),
                'channel_id': str(message_data.get('channel_id', 'Unknown')),
                'content_length': len(message_data.get('content', '')),
                'has_attachments': bool(message_data.get('attachments'))
            })
        except Exception as e:
            logger.error(f'Error logging security event: {e}')
    
    async def _log_web_event(self, message_data: Dict[str, Any]):
        """Log event to web integration asynchronously (only for Direct Messages)."""
        try:
            # Only log Direct Messages (no guild_id means it's a DM)
            is_dm = message_data.get('guild_id') is None
            if not is_dm:
                logger.debug(f"Skipping non-DM message {message_data.get('id', 'unknown')} in async processing")
                return
                
            # Skip messages from the connected user
            author_info = message_data.get('author', {})
            author_id = author_info.get('id')
            
            # Import MY_ID from main module
            import main
            if hasattr(main, 'MY_ID') and author_id == main.MY_ID:
                logger.debug(f"Skipping message from connected user {author_id}")
                return
                
            from web_integration import log_message
            
            # Try both 'message_id' and 'id' keys for message ID
            msg_id = message_data.get('message_id') or message_data.get('id', 'Unknown')
            author_info = message_data.get('author', {})
            author_name = author_info.get('username', f"User {author_info.get('id', 'Unknown')}")
            
            # Get channel information for proper display
            channel_id = str(message_data.get('channel_id', 'Unknown'))
            channel_name = f'Channel-{channel_id[:8]}' if channel_id != 'Unknown' else 'Unknown Channel'
            
            logger.info(f"Logging DM to dashboard via async: msg_id={msg_id}")
            log_message(
                author=author_name,
                content=message_data.get('content', ''),
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=str(msg_id),
                attachments=message_data.get('attachments', [])
            )
        except Exception as e:
            logger.error(f'Error logging web event: {e}')
    
    async def close(self):
        """Close the message processor."""
        self.executor.shutdown(wait=True)

# Global instances
_webhook_sender: Optional[AsyncWebhookSender] = None
_file_downloader: Optional[AsyncFileDownloader] = None
_message_processor: Optional[AsyncMessageProcessor] = None

async def get_webhook_sender(config: AsyncConfig = None) -> AsyncWebhookSender:
    """Get or create global webhook sender instance."""
    global _webhook_sender
    if _webhook_sender is None:
        _webhook_sender = AsyncWebhookSender(config)
        await _webhook_sender._ensure_session()
    return _webhook_sender

async def get_file_downloader(config: AsyncConfig = None) -> AsyncFileDownloader:
    """Get or create global file downloader instance."""
    global _file_downloader
    if _file_downloader is None:
        _file_downloader = AsyncFileDownloader(config)
        await _file_downloader._ensure_session()
    return _file_downloader

async def get_message_processor(config: AsyncConfig = None) -> AsyncMessageProcessor:
    """Get or create global message processor instance."""
    global _message_processor
    if _message_processor is None:
        webhook_sender = await get_webhook_sender(config)
        file_downloader = await get_file_downloader(config)
        _message_processor = AsyncMessageProcessor(webhook_sender, file_downloader)
    return _message_processor

async def cleanup_async_resources():
    """Clean up all async resources."""
    global _webhook_sender, _file_downloader, _message_processor
    
    if _message_processor:
        await _message_processor.close()
        _message_processor = None
    
    if _webhook_sender:
        await _webhook_sender.close()
        _webhook_sender = None
    
    if _file_downloader:
        await _file_downloader.close()
        _file_downloader = None
    
    logger.info("Cleaned up async resources")

# Convenience functions for backward compatibility
async def async_send_embed(webhook_url: str, title: str, description: str, 
                          author_name: str = None, author_icon: str = None,
                          image_url: str = None, color: int = 0x7289da) -> bool:
    """Send embed asynchronously (convenience function)."""
    sender = await get_webhook_sender()
    return await sender.send_embed(webhook_url, title, description, 
                                  author_name, author_icon, image_url, color)

async def async_download_attachment(url: str, filepath: Path, 
                                   max_size: int = None) -> Tuple[bool, Optional[str]]:
    """Download attachment asynchronously (convenience function)."""
    downloader = await get_file_downloader()
    return await downloader.download_file(url, filepath, max_size)

async def async_process_message(message_data: Dict[str, Any], 
                               config: Dict[str, Any]) -> bool:
    """Process message asynchronously (convenience function)."""
    processor = await get_message_processor()
    return await processor.process_message(message_data, config)