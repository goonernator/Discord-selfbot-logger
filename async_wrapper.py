"""Async wrapper for Discord Selfbot Logger.

This module provides async wrappers for the existing Discord event handlers,
allowing for gradual migration to async/await patterns while maintaining
backward compatibility.
"""

import asyncio
import logging
import threading
from typing import Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from async_optimizer import (
    AsyncWebhookSender, AsyncFileDownloader, AsyncMessageProcessor,
    AsyncConfig, async_send_embed, async_download_attachment,
    async_process_message, cleanup_async_resources
)

logger = logging.getLogger(__name__)

class AsyncEventLoop:
    """Manages the async event loop for Discord events."""
    
    def __init__(self, config: AsyncConfig = None):
        self.config = config or AsyncConfig()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AsyncEvent")
        self._shutdown_event = threading.Event()
        self._running = False
    
    def start(self):
        """Start the async event loop in a separate thread."""
        if self._running:
            logger.warning("Async event loop is already running")
            return
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        # Wait for loop to be ready
        while self.loop is None:
            threading.Event().wait(0.01)
        
        logger.info("Async event loop started")
    
    def _run_loop(self):
        """Run the async event loop."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._running = True
            
            # Run until shutdown
            self.loop.run_until_complete(self._loop_main())
            
        except Exception as e:
            logger.error(f"Error in async event loop: {e}")
        finally:
            self._running = False
            if self.loop and not self.loop.is_closed():
                self.loop.close()
    
    async def _loop_main(self):
        """Main async loop function."""
        try:
            # Keep the loop running
            while not self._shutdown_event.is_set():
                await asyncio.sleep(0.1)
        finally:
            # Cleanup resources
            await cleanup_async_resources()
    
    def stop(self):
        """Stop the async event loop."""
        if not self._running:
            return
        
        logger.info("Stopping async event loop...")
        self._shutdown_event.set()
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        
        self.executor.shutdown(wait=True)
        logger.info("Async event loop stopped")
    
    def run_async(self, coro):
        """Schedule a coroutine to run in the async loop."""
        if not self._running or not self.loop:
            logger.error("Async event loop is not running")
            return None
        
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future
    
    def run_async_nowait(self, coro):
        """Schedule a coroutine without waiting for result."""
        if not self._running or not self.loop:
            logger.error("Async event loop is not running")
            return
        
        asyncio.run_coroutine_threadsafe(coro, self.loop)

class AsyncDiscordWrapper:
    """Wrapper for Discord event handlers with async optimization."""
    
    def __init__(self, config: Dict[str, Any], async_config: AsyncConfig = None):
        self.config = config
        self.async_config = async_config or AsyncConfig()
        self.event_loop = AsyncEventLoop(self.async_config)
        self.message_queue = asyncio.Queue(maxsize=1000)
        
        # Batch processing queues
        self.webhook_batch_queue = asyncio.Queue(maxsize=1000)
        self.download_batch_queue = asyncio.Queue(maxsize=1000)
        self.batch_size = config.get('BATCH_SIZE', 10)
        self.batch_timeout = config.get('BATCH_TIMEOUT', 2.0)  # seconds
        
        self._stats = {
            'messages_processed': 0,
            'webhooks_sent': 0,
            'files_downloaded': 0,
            'batches_processed': 0,
            'errors': 0
        }
        
        # Start batch processors
        self._start_batch_processors()
    
    def _start_batch_processors(self):
        """Start batch processing tasks."""
        if self.event_loop._running:
            self.event_loop.run_async_nowait(self._webhook_batch_processor())
            self.event_loop.run_async_nowait(self._download_batch_processor())
    
    async def _webhook_batch_processor(self):
        """Process webhook batches."""
        batch = []
        last_batch_time = asyncio.get_event_loop().time()
        
        while True:
            try:
                # Wait for item with timeout
                try:
                    item = await asyncio.wait_for(
                        self.webhook_batch_queue.get(),
                        timeout=self.batch_timeout
                    )
                    batch.append(item)
                except asyncio.TimeoutError:
                    # Timeout - process batch if not empty
                    pass
                
                # Process batch if full or timeout
                current_time = asyncio.get_event_loop().time()
                if len(batch) >= self.batch_size or (
                    batch and current_time - last_batch_time >= self.batch_timeout
                ):
                    await self._process_webhook_batch(batch)
                    batch = []
                    last_batch_time = current_time
                    
            except Exception as e:
                logger.error(f"Error in webhook batch processor: {e}")
                await asyncio.sleep(1)
    
    async def _download_batch_processor(self):
        """Process download batches."""
        batch = []
        last_batch_time = asyncio.get_event_loop().time()
        
        while True:
            try:
                # Wait for item with timeout
                try:
                    item = await asyncio.wait_for(
                        self.download_batch_queue.get(),
                        timeout=self.batch_timeout
                    )
                    batch.append(item)
                except asyncio.TimeoutError:
                    # Timeout - process batch if not empty
                    pass
                
                # Process batch if full or timeout
                current_time = asyncio.get_event_loop().time()
                if len(batch) >= self.batch_size or (
                    batch and current_time - last_batch_time >= self.batch_timeout
                ):
                    await self._process_download_batch(batch)
                    batch = []
                    last_batch_time = current_time
                    
            except Exception as e:
                logger.error(f"Error in download batch processor: {e}")
                await asyncio.sleep(1)
    
    async def _process_webhook_batch(self, batch: list):
        """Process a batch of webhook sends."""
        if not batch:
            return
        
        try:
            # Process all webhooks concurrently
            tasks = [
                async_send_embed(
                    item['webhook_url'], item['title'], item['description'],
                    item.get('author_name'), item.get('author_icon'),
                    item.get('image_url'), item.get('color', 0x7289da)
                )
                for item in batch
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if r is True)
            self._stats['webhooks_sent'] += success_count
            self._stats['batches_processed'] += 1
            
            if success_count < len(batch):
                self._stats['errors'] += len(batch) - success_count
                logger.warning(f"Batch webhook send: {success_count}/{len(batch)} succeeded")
            else:
                logger.debug(f"Batch webhook send: {len(batch)} webhooks sent successfully")
                
        except Exception as e:
            logger.error(f"Error processing webhook batch: {e}")
            self._stats['errors'] += len(batch)
    
    async def _process_download_batch(self, batch: list):
        """Process a batch of downloads."""
        if not batch:
            return
        
        try:
            # Process all downloads concurrently
            tasks = [
                async_download_attachment(
                    item['url'], item['filepath'], item.get('max_size')
                )
                for item in batch
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if isinstance(r, tuple) and r[0] is True)
            self._stats['files_downloaded'] += success_count
            self._stats['batches_processed'] += 1
            
            if success_count < len(batch):
                self._stats['errors'] += len(batch) - success_count
                logger.warning(f"Batch download: {success_count}/{len(batch)} succeeded")
            else:
                logger.debug(f"Batch download: {len(batch)} files downloaded successfully")
                
        except Exception as e:
            logger.error(f"Error processing download batch: {e}")
            self._stats['errors'] += len(batch)
    
    def start(self):
        """Start the async wrapper."""
        self.event_loop.start()
        self._start_batch_processors()
        logger.info("AsyncDiscordWrapper started")
    
    def stop(self):
        """Stop the async wrapper."""
        self.event_loop.stop()
        logger.info(f"AsyncDiscordWrapper stopped. Stats: {self._stats}")
    
    def send_embed_async(self, webhook_url: str, title: str, description: str,
                        author_name: str = None, author_icon: str = None,
                        image_url: str = None, color: int = 0x7289da, batch: bool = True) -> bool:
        """Send embed asynchronously (non-blocking).
        
        Args:
            webhook_url: Discord webhook URL
            title: Embed title
            description: Embed description
            author_name: Author name (optional)
            author_icon: Author icon URL (optional)
            image_url: Image URL (optional)
            color: Embed color
            batch: Whether to use batch processing (default True)
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            if batch:
                # Add to batch queue
                item = {
                    'webhook_url': webhook_url,
                    'title': title,
                    'description': description,
                    'author_name': author_name,
                    'author_icon': author_icon,
                    'image_url': image_url,
                    'color': color
                }
                self.event_loop.run_async_nowait(
                    self._add_to_webhook_batch(item)
                )
            else:
                # Send immediately
                coro = self._send_embed_coro(webhook_url, title, description,
                                           author_name, author_icon, image_url, color)
                self.event_loop.run_async_nowait(coro)
            return True
        except Exception as e:
            logger.error(f"Error scheduling async embed send: {e}")
            self._stats['errors'] += 1
            return False
    
    async def _add_to_webhook_batch(self, item: dict):
        """Add item to webhook batch queue."""
        try:
            await self.webhook_batch_queue.put(item)
        except asyncio.QueueFull:
            logger.warning("Webhook batch queue full, dropping item")
            self._stats['errors'] += 1
    
    async def _send_embed_coro(self, webhook_url: str, title: str, description: str,
                              author_name: str = None, author_icon: str = None,
                              image_url: str = None, color: int = 0x7289da):
        """Coroutine for sending embed."""
        try:
            success = await async_send_embed(webhook_url, title, description,
                                            author_name, author_icon, image_url, color)
            if success:
                self._stats['webhooks_sent'] += 1
            else:
                self._stats['errors'] += 1
        except Exception as e:
            logger.error(f"Error in async embed send: {e}")
            self._stats['errors'] += 1
    
    def download_attachment_async(self, url: str, filename: str, 
                                 attachment_dir: Path = None, batch: bool = True) -> bool:
        """Download attachment asynchronously (non-blocking).
        
        Args:
            url: File URL to download
            filename: Local filename
            attachment_dir: Directory to save file (optional)
            batch: Whether to use batch processing (default True)
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            if attachment_dir is None:
                attachment_dir = Path(self.config.get('ATTACH_DIR', 'attachments'))
            
            filepath = attachment_dir / filename
            max_size = self.config.get('ATTACHMENT_SIZE_LIMIT', 50 * 1024 * 1024)
            
            if batch:
                # Add to batch queue
                item = {
                    'url': url,
                    'filepath': filepath,
                    'max_size': max_size
                }
                self.event_loop.run_async_nowait(
                    self._add_to_download_batch(item)
                )
            else:
                # Download immediately
                coro = self._download_attachment_coro(url, filepath, max_size)
                self.event_loop.run_async_nowait(coro)
            return True
        except Exception as e:
            logger.error(f"Error scheduling async download: {e}")
            self._stats['errors'] += 1
            return False
    
    async def _add_to_download_batch(self, item: dict):
        """Add item to download batch queue."""
        try:
            await self.download_batch_queue.put(item)
        except asyncio.QueueFull:
            logger.warning("Download batch queue full, dropping item")
            self._stats['errors'] += 1
    
    async def _download_attachment_coro(self, url: str, filepath: Path, max_size: int):
        """Coroutine for downloading attachment."""
        try:
            success, error = await async_download_attachment(url, filepath, max_size)
            if success:
                self._stats['files_downloaded'] += 1
                logger.info(f"Downloaded: {filepath.name}")
            else:
                self._stats['errors'] += 1
                logger.error(f"Download failed: {error}")
        except Exception as e:
            logger.error(f"Error in async download: {e}")
            self._stats['errors'] += 1
    
    def process_message_async(self, message_data: Dict[str, Any]) -> bool:
        """Process Discord message asynchronously (non-blocking).
        
        Args:
            message_data: Discord message data
            
        Returns:
            bool: True if scheduled successfully
        """
        try:
            coro = self._process_message_coro(message_data)
            self.event_loop.run_async_nowait(coro)
            return True
        except Exception as e:
            logger.error(f"Error scheduling async message processing: {e}")
            self._stats['errors'] += 1
            return False
    
    async def _process_message_coro(self, message_data: Dict[str, Any]):
        """Coroutine for processing message."""
        try:
            success = await async_process_message(message_data, self.config)
            if success:
                self._stats['messages_processed'] += 1
            else:
                self._stats['errors'] += 1
        except Exception as e:
            logger.error(f"Error in async message processing: {e}")
            self._stats['errors'] += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Get processing statistics."""
        return self._stats.copy()
    
    def reset_stats(self):
        """Reset processing statistics."""
        self._stats = {
            'messages_processed': 0,
            'webhooks_sent': 0,
            'files_downloaded': 0,
            'errors': 0
        }

# Global async wrapper instance
_async_wrapper: Optional[AsyncDiscordWrapper] = None

def get_async_wrapper(config: Dict[str, Any] = None, 
                     async_config: AsyncConfig = None) -> AsyncDiscordWrapper:
    """Get or create global async wrapper instance."""
    global _async_wrapper
    if _async_wrapper is None:
        if config is None:
            raise ValueError("Config required for first initialization")
        _async_wrapper = AsyncDiscordWrapper(config, async_config)
        _async_wrapper.start()
    return _async_wrapper

def cleanup_async_wrapper():
    """Clean up the global async wrapper."""
    global _async_wrapper
    if _async_wrapper:
        _async_wrapper.stop()
        _async_wrapper = None

# Convenience functions for backward compatibility
def async_send_embed_compat(webhook_url: str, title: str, description: str,
                           author_name: str = None, author_icon: str = None,
                           image_url: str = None, color: int = 0x7289da,
                           config: Dict[str, Any] = None) -> bool:
    """Send embed asynchronously (backward compatible)."""
    wrapper = get_async_wrapper(config)
    return wrapper.send_embed_async(webhook_url, title, description,
                                   author_name, author_icon, image_url, color)

def async_download_attachment_compat(url: str, filename: str,
                                    config: Dict[str, Any] = None) -> bool:
    """Download attachment asynchronously (backward compatible)."""
    wrapper = get_async_wrapper(config)
    return wrapper.download_attachment_async(url, filename)

def async_process_message_compat(message_data: Dict[str, Any],
                                config: Dict[str, Any] = None) -> bool:
    """Process message asynchronously (backward compatible)."""
    wrapper = get_async_wrapper(config)
    return wrapper.process_message_async(message_data)

def get_async_stats(config: Dict[str, Any] = None) -> Dict[str, int]:
    """Get async processing statistics."""
    wrapper = get_async_wrapper(config)
    return wrapper.get_stats()