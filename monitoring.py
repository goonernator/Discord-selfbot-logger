"""Monitoring and metrics collection for Discord Selfbot Logger.

This module provides Prometheus-compatible metrics collection, alerting,
and performance monitoring capabilities.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("prometheus_client not available, metrics will be collected but not exposed")

logger = logging.getLogger(__name__)

class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class Alert:
    """Represents an alert."""
    alert_id: str
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime
    metadata: Dict[str, Any]
    resolved: bool = False
    resolved_at: Optional[datetime] = None

class MetricsCollector:
    """Collects and stores application metrics."""
    
    def __init__(self):
        """Initialize metrics collector."""
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = defaultdict(list)
        self.start_time = time.time()
        self._lock = threading.RLock()
        
        # Prometheus metrics (if available)
        if PROMETHEUS_AVAILABLE:
            self.prom_counters = {}
            self.prom_gauges = {}
            self.prom_histograms = {}
    
    def increment(self, metric_name: str, value: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric.
        
        Args:
            metric_name: Name of the metric
            value: Value to increment by
            labels: Optional labels for Prometheus
        """
        with self._lock:
            self.counters[metric_name] += value
            
            if PROMETHEUS_AVAILABLE:
                if metric_name not in self.prom_counters:
                    self.prom_counters[metric_name] = Counter(
                        metric_name.replace('.', '_'),
                        f'Counter for {metric_name}',
                        list(labels.keys()) if labels else []
                    )
                self.prom_counters[metric_name].labels(**labels).inc(value) if labels else self.prom_counters[metric_name].inc(value)
    
    def set_gauge(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric.
        
        Args:
            metric_name: Name of the metric
            value: Gauge value
            labels: Optional labels for Prometheus
        """
        with self._lock:
            self.gauges[metric_name] = value
            
            if PROMETHEUS_AVAILABLE:
                if metric_name not in self.prom_gauges:
                    self.prom_gauges[metric_name] = Gauge(
                        metric_name.replace('.', '_'),
                        f'Gauge for {metric_name}',
                        list(labels.keys()) if labels else []
                    )
                if labels:
                    self.prom_gauges[metric_name].labels(**labels).set(value)
                else:
                    self.prom_gauges[metric_name].set(value)
    
    def record_histogram(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a histogram value.
        
        Args:
            metric_name: Name of the metric
            value: Value to record
            labels: Optional labels for Prometheus
        """
        with self._lock:
            self.histograms[metric_name].append(value)
            # Keep only last 1000 values
            if len(self.histograms[metric_name]) > 1000:
                self.histograms[metric_name] = self.histograms[metric_name][-1000:]
            
            if PROMETHEUS_AVAILABLE:
                if metric_name not in self.prom_histograms:
                    self.prom_histograms[metric_name] = Histogram(
                        metric_name.replace('.', '_'),
                        f'Histogram for {metric_name}',
                        list(labels.keys()) if labels else []
                    )
                if labels:
                    self.prom_histograms[metric_name].labels(**labels).observe(value)
                else:
                    self.prom_histograms[metric_name].observe(value)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all collected metrics.
        
        Returns:
            Dictionary with all metrics
        """
        with self._lock:
            histograms_summary = {}
            for name, values in self.histograms.items():
                if values:
                    histograms_summary[name] = {
                        'count': len(values),
                        'min': min(values),
                        'max': max(values),
                        'avg': sum(values) / len(values),
                        'p50': sorted(values)[len(values) // 2] if values else 0,
                        'p95': sorted(values)[int(len(values) * 0.95)] if values else 0,
                        'p99': sorted(values)[int(len(values) * 0.99)] if values else 0
                    }
            
            return {
                'counters': dict(self.counters),
                'gauges': dict(self.gauges),
                'histograms': histograms_summary,
                'uptime_seconds': time.time() - self.start_time
            }

class AlertManager:
    """Manages alerts and notifications."""
    
    def __init__(self, max_alerts: int = 1000):
        """Initialize alert manager.
        
        Args:
            max_alerts: Maximum number of alerts to keep in memory
        """
        self.alerts: deque = deque(maxlen=max_alerts)
        self.active_alerts: Dict[str, Alert] = {}
        self._lock = threading.RLock()
    
    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        alert_id: Optional[str] = None
    ) -> Alert:
        """Create a new alert.
        
        Args:
            level: Alert level
            title: Alert title
            message: Alert message
            metadata: Optional metadata
            alert_id: Optional alert ID (auto-generated if not provided)
            
        Returns:
            Created alert
        """
        if alert_id is None:
            alert_id = f"{level.value}_{int(time.time())}_{len(self.alerts)}"
        
        alert = Alert(
            alert_id=alert_id,
            level=level,
            title=title,
            message=message,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        
        with self._lock:
            self.alerts.append(alert)
            self.active_alerts[alert_id] = alert
        
        log_level = getattr(logging, level.value.upper(), logging.INFO)
        logger.log(log_level, f"ALERT [{level.value.upper()}]: {title} - {message}")
        
        return alert
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert.
        
        Args:
            alert_id: Alert ID to resolve
            
        Returns:
            True if alert was resolved
        """
        with self._lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                alert.resolved = True
                alert.resolved_at = datetime.now()
                del self.active_alerts[alert_id]
                logger.info(f"Alert resolved: {alert_id}")
                return True
            return False
    
    def get_active_alerts(self, level: Optional[AlertLevel] = None) -> List[Alert]:
        """Get active alerts.
        
        Args:
            level: Optional filter by level
            
        Returns:
            List of active alerts
        """
        with self._lock:
            alerts = list(self.active_alerts.values())
            if level:
                alerts = [a for a in alerts if a.level == level]
            return alerts
    
    def get_recent_alerts(self, limit: int = 100, level: Optional[AlertLevel] = None) -> List[Dict[str, Any]]:
        """Get recent alerts.
        
        Args:
            limit: Maximum alerts to return
            level: Optional filter by level
            
        Returns:
            List of alert dictionaries
        """
        with self._lock:
            alerts = list(self.alerts)
            if level:
                alerts = [a for a in alerts if a.level == level]
            alerts = alerts[-limit:]
            return [asdict(a) for a in alerts]

class HealthChecker:
    """Checks system health and status."""
    
    def __init__(self):
        """Initialize health checker."""
        self.checks: Dict[str, Callable] = {}
        self.last_check_time: Dict[str, datetime] = {}
        self.check_results: Dict[str, Dict[str, Any]] = {}
    
    def register_check(self, name: str, check_func: Callable[[], Dict[str, Any]]):
        """Register a health check.
        
        Args:
            name: Check name
            check_func: Function that returns {'status': 'ok'|'degraded'|'down', 'message': str}
        """
        self.checks[name] = check_func
    
    def run_check(self, name: str) -> Dict[str, Any]:
        """Run a specific health check.
        
        Args:
            name: Check name
            
        Returns:
            Check result dictionary
        """
        if name not in self.checks:
            return {'status': 'unknown', 'message': f'Check {name} not found'}
        
        try:
            result = self.checks[name]()
            self.last_check_time[name] = datetime.now()
            self.check_results[name] = result
            return result
        except Exception as e:
            logger.error(f"Health check {name} failed: {e}")
            return {'status': 'down', 'message': str(e)}
    
    def run_all_checks(self) -> Dict[str, Dict[str, Any]]:
        """Run all registered health checks.
        
        Returns:
            Dictionary of check results
        """
        results = {}
        for name in self.checks:
            results[name] = self.run_check(name)
        return results
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status.
        
        Returns:
            Overall health dictionary
        """
        results = self.run_all_checks()
        
        statuses = [r.get('status', 'unknown') for r in results.values()]
        
        if 'down' in statuses:
            overall_status = 'down'
        elif 'degraded' in statuses:
            overall_status = 'degraded'
        else:
            overall_status = 'ok'
        
        return {
            'status': overall_status,
            'checks': results,
            'timestamp': datetime.now().isoformat()
        }

class MonitoringSystem:
    """Main monitoring system that combines metrics, alerts, and health checks."""
    
    def __init__(self, prometheus_port: Optional[int] = None):
        """Initialize monitoring system.
        
        Args:
            prometheus_port: Optional port for Prometheus metrics endpoint
        """
        self.metrics = MetricsCollector()
        self.alerts = AlertManager()
        self.health = HealthChecker()
        self.prometheus_port = prometheus_port
        self.prometheus_server_started = False
        
        # Register default health checks
        self._register_default_checks()
        
        # Start Prometheus server if requested
        if prometheus_port and PROMETHEUS_AVAILABLE:
            try:
                start_http_server(prometheus_port)
                self.prometheus_server_started = True
                logger.info(f"Prometheus metrics server started on port {prometheus_port}")
            except Exception as e:
                logger.error(f"Failed to start Prometheus server: {e}")
    
    def _register_default_checks(self):
        """Register default health checks."""
        def check_uptime():
            uptime = time.time() - self.metrics.start_time
            return {
                'status': 'ok' if uptime > 0 else 'down',
                'message': f'Uptime: {uptime:.0f} seconds',
                'uptime_seconds': uptime
            }
        
        self.health.register_check('uptime', check_uptime)
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete monitoring status.
        
        Returns:
            Complete status dictionary
        """
        return {
            'metrics': self.metrics.get_metrics(),
            'health': self.health.get_overall_health(),
            'active_alerts': len(self.alerts.active_alerts),
            'recent_alerts': self.alerts.get_recent_alerts(limit=10),
            'prometheus_enabled': self.prometheus_server_started
        }

# Global monitoring instance
_monitoring_system: Optional[MonitoringSystem] = None

def get_monitoring_system(prometheus_port: Optional[int] = None) -> MonitoringSystem:
    """Get global monitoring system instance.
    
    Args:
        prometheus_port: Optional port for Prometheus metrics
        
    Returns:
        MonitoringSystem instance
    """
    global _monitoring_system
    if _monitoring_system is None:
        _monitoring_system = MonitoringSystem(prometheus_port)
    return _monitoring_system

