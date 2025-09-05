"""Performance monitoring for Discord Selfbot Logger.

This module provides performance monitoring and metrics collection
to track the benefits of async optimization and identify bottlenecks.
"""

import time
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timedelta
import json
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetric:
    """Individual performance metric."""
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self, success: bool = True, error: Optional[str] = None):
        """Mark the metric as finished."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.success = success
        self.error = error

@dataclass
class PerformanceStats:
    """Aggregated performance statistics."""
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    total_duration: float = 0.0
    avg_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    operations_per_second: float = 0.0
    
    def update(self, metric: PerformanceMetric):
        """Update stats with a new metric."""
        if metric.duration is None:
            return
        
        self.total_operations += 1
        if metric.success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
        
        self.total_duration += metric.duration
        self.avg_duration = self.total_duration / self.total_operations
        self.min_duration = min(self.min_duration, metric.duration)
        self.max_duration = max(self.max_duration, metric.duration)
        
        if self.total_duration > 0:
            self.operations_per_second = self.total_operations / self.total_duration

class PerformanceMonitor:
    """Performance monitoring and metrics collection."""
    
    def __init__(self, max_metrics: int = 10000, report_interval: int = 300):
        self.max_metrics = max_metrics
        self.report_interval = report_interval
        self._metrics: deque = deque(maxlen=max_metrics)
        self._stats: Dict[str, PerformanceStats] = defaultdict(PerformanceStats)
        self._active_metrics: Dict[str, PerformanceMetric] = {}
        self._lock = threading.RLock()
        self._last_report = time.time()
        self._start_time = time.time()
    
    def start_operation(self, operation_name: str, metadata: Dict[str, Any] = None) -> str:
        """Start tracking a performance operation.
        
        Args:
            operation_name: Name of the operation
            metadata: Additional metadata for the operation
            
        Returns:
            str: Unique operation ID
        """
        operation_id = f"{operation_name}_{int(time.time() * 1000000)}"
        metric = PerformanceMetric(
            name=operation_name,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        with self._lock:
            self._active_metrics[operation_id] = metric
        
        return operation_id
    
    def finish_operation(self, operation_id: str, success: bool = True, 
                        error: Optional[str] = None):
        """Finish tracking a performance operation.
        
        Args:
            operation_id: Operation ID returned by start_operation
            success: Whether the operation was successful
            error: Error message if operation failed
        """
        with self._lock:
            metric = self._active_metrics.pop(operation_id, None)
            if metric:
                metric.finish(success, error)
                self._metrics.append(metric)
                self._stats[metric.name].update(metric)
                
                # Auto-report if interval passed
                if time.time() - self._last_report > self.report_interval:
                    self._generate_report()
    
    def record_operation(self, operation_name: str, duration: float, 
                       success: bool = True, error: Optional[str] = None,
                       metadata: Dict[str, Any] = None):
        """Record a completed operation directly.
        
        Args:
            operation_name: Name of the operation
            duration: Duration in seconds
            success: Whether the operation was successful
            error: Error message if operation failed
            metadata: Additional metadata
        """
        metric = PerformanceMetric(
            name=operation_name,
            start_time=time.time() - duration,
            end_time=time.time(),
            duration=duration,
            success=success,
            error=error,
            metadata=metadata or {}
        )
        
        with self._lock:
            self._metrics.append(metric)
            self._stats[metric.name].update(metric)
    
    def get_stats(self, operation_name: Optional[str] = None) -> Dict[str, PerformanceStats]:
        """Get performance statistics.
        
        Args:
            operation_name: Specific operation name, or None for all
            
        Returns:
            Dict of operation names to their stats
        """
        with self._lock:
            if operation_name:
                return {operation_name: self._stats.get(operation_name, PerformanceStats())}
            return dict(self._stats)
    
    def get_recent_metrics(self, operation_name: Optional[str] = None, 
                          minutes: int = 5) -> List[PerformanceMetric]:
        """Get recent metrics for analysis.
        
        Args:
            operation_name: Filter by operation name
            minutes: How many minutes back to look
            
        Returns:
            List of recent metrics
        """
        cutoff_time = time.time() - (minutes * 60)
        
        with self._lock:
            recent = []
            for metric in reversed(self._metrics):
                if metric.start_time < cutoff_time:
                    break
                if operation_name is None or metric.name == operation_name:
                    recent.append(metric)
            
            return list(reversed(recent))
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get a comprehensive performance summary.
        
        Returns:
            Dict containing performance summary
        """
        with self._lock:
            uptime = time.time() - self._start_time
            total_operations = sum(stats.total_operations for stats in self._stats.values())
            total_successful = sum(stats.successful_operations for stats in self._stats.values())
            total_failed = sum(stats.failed_operations for stats in self._stats.values())
            
            summary = {
                'uptime_seconds': uptime,
                'uptime_formatted': str(timedelta(seconds=int(uptime))),
                'total_operations': total_operations,
                'successful_operations': total_successful,
                'failed_operations': total_failed,
                'success_rate': (total_successful / total_operations * 100) if total_operations > 0 else 0,
                'operations_per_minute': (total_operations / uptime * 60) if uptime > 0 else 0,
                'active_operations': len(self._active_metrics),
                'operation_stats': {}
            }
            
            # Add per-operation stats
            for op_name, stats in self._stats.items():
                summary['operation_stats'][op_name] = {
                    'total': stats.total_operations,
                    'successful': stats.successful_operations,
                    'failed': stats.failed_operations,
                    'success_rate': (stats.successful_operations / stats.total_operations * 100) if stats.total_operations > 0 else 0,
                    'avg_duration_ms': stats.avg_duration * 1000,
                    'min_duration_ms': stats.min_duration * 1000 if stats.min_duration != float('inf') else 0,
                    'max_duration_ms': stats.max_duration * 1000,
                    'ops_per_second': stats.operations_per_second
                }
            
            return summary
    
    def _generate_report(self):
        """Generate and log a performance report."""
        try:
            summary = self.get_performance_summary()
            
            logger.info("=== Performance Report ===")
            logger.info(f"Uptime: {summary['uptime_formatted']}")
            logger.info(f"Total Operations: {summary['total_operations']}")
            logger.info(f"Success Rate: {summary['success_rate']:.1f}%")
            logger.info(f"Operations/min: {summary['operations_per_minute']:.1f}")
            logger.info(f"Active Operations: {summary['active_operations']}")
            
            for op_name, stats in summary['operation_stats'].items():
                logger.info(f"  {op_name}: {stats['total']} ops, "
                          f"{stats['success_rate']:.1f}% success, "
                          f"{stats['avg_duration_ms']:.1f}ms avg")
            
            self._last_report = time.time()
            
        except Exception as e:
            logger.error(f"Error generating performance report: {e}")
    
    def save_metrics(self, filepath: Path):
        """Save metrics to a JSON file.
        
        Args:
            filepath: Path to save the metrics file
        """
        try:
            with self._lock:
                data = {
                    'summary': self.get_performance_summary(),
                    'metrics': [
                        {
                            'name': m.name,
                            'start_time': m.start_time,
                            'end_time': m.end_time,
                            'duration': m.duration,
                            'success': m.success,
                            'error': m.error,
                            'metadata': m.metadata
                        }
                        for m in list(self._metrics)
                    ]
                }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.info(f"Performance metrics saved to {filepath}")
            
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
    
    def reset_stats(self):
        """Reset all performance statistics."""
        with self._lock:
            self._metrics.clear()
            self._stats.clear()
            self._active_metrics.clear()
            self._start_time = time.time()
            self._last_report = time.time()
        
        logger.info("Performance statistics reset")

# Global performance monitor instance
_performance_monitor: Optional[PerformanceMonitor] = None

def get_performance_monitor() -> PerformanceMonitor:
    """Get or create the global performance monitor."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor

def start_operation(operation_name: str, metadata: Dict[str, Any] = None) -> str:
    """Start tracking a performance operation (convenience function)."""
    return get_performance_monitor().start_operation(operation_name, metadata)

def finish_operation(operation_id: str, success: bool = True, error: Optional[str] = None):
    """Finish tracking a performance operation (convenience function)."""
    get_performance_monitor().finish_operation(operation_id, success, error)

def record_operation(operation_name: str, duration: float, success: bool = True, 
                    error: Optional[str] = None, metadata: Dict[str, Any] = None):
    """Record a completed operation (convenience function)."""
    get_performance_monitor().record_operation(operation_name, duration, success, error, metadata)

def get_performance_summary() -> Dict[str, Any]:
    """Get performance summary (convenience function)."""
    return get_performance_monitor().get_performance_summary()

class performance_timer:
    """Context manager for timing operations."""
    
    def __init__(self, operation_name: str, metadata: Dict[str, Any] = None):
        self.operation_name = operation_name
        self.metadata = metadata
        self.operation_id = None
    
    def __enter__(self):
        self.operation_id = start_operation(self.operation_name, self.metadata)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        success = exc_type is None
        error = str(exc_val) if exc_val else None
        finish_operation(self.operation_id, success, error)

# Decorator for timing functions
def monitor_performance(operation_name: str = None, include_args: bool = False):
    """Decorator to monitor function performance.
    
    Args:
        operation_name: Custom operation name (defaults to function name)
        include_args: Whether to include function arguments in metadata
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            metadata = {}
            
            if include_args:
                metadata['args_count'] = len(args)
                metadata['kwargs_count'] = len(kwargs)
            
            with performance_timer(op_name, metadata):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator