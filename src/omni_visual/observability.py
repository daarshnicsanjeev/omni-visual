"""
Observability utilities for Omni-Visual.

Provides:
- Structured logging with correlation IDs
- Metrics collection for API latency and success rates
- Request tracing decorators
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable

# =============================================================================
# Logging Configuration
# =============================================================================

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("omni_visual")


class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records for request tracing."""

    def __init__(self):
        super().__init__()
        self._correlation_id: str | None = None

    def set_correlation_id(self, correlation_id: str | None):
        self._correlation_id = correlation_id

    def get_correlation_id(self) -> str | None:
        return self._correlation_id

    def filter(self, record):
        record.correlation_id = self._correlation_id or "N/A"
        return True


# Global filter instance
correlation_filter = CorrelationIdFilter()


def setup_logging(level: int = logging.INFO):
    """Configure logging with correlation ID support."""
    root_logger = logging.getLogger("omni_visual")
    root_logger.setLevel(level)
    root_logger.addFilter(correlation_filter)

    # Update format to include correlation ID
    for handler in root_logger.handlers:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] %(message)s"
            )
        )


# =============================================================================
# Metrics Collection
# =============================================================================


class Metrics:
    """
    Simple in-memory metrics collection.

    Tracks:
    - Latency distributions (min, max, avg, count)
    - Success/error counts
    - Custom counters
    """

    def __init__(self):
        self._latencies: dict[str, list[float]] = {}
        self._counts: dict[str, int] = {}

    def record_latency(self, name: str, latency_ms: float):
        """Record a latency measurement."""
        if name not in self._latencies:
            self._latencies[name] = []
        self._latencies[name].append(latency_ms)

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        self._counts[name] = self._counts.get(name, 0) + value

    def get_count(self, name: str) -> int:
        """Get current count for a metric."""
        return self._counts.get(name, 0)

    def summary(self) -> dict:
        """
        Get a summary of all collected metrics.

        Returns:
            dict with counts and latency distributions
        """
        result = {"counts": dict(self._counts), "latencies": {}}

        for name, values in self._latencies.items():
            if values:
                sorted_values = sorted(values)
                n = len(values)
                result["latencies"][name] = {
                    "count": n,
                    "avg_ms": round(sum(values) / n, 2),
                    "min_ms": round(min(values), 2),
                    "max_ms": round(max(values), 2),
                    "p50_ms": round(sorted_values[n // 2], 2),
                    "p95_ms": round(sorted_values[int(n * 0.95)] if n >= 20 else max(values), 2),
                }

        return result

    def reset(self):
        """Reset all metrics."""
        self._latencies.clear()
        self._counts.clear()
        logger.info("Metrics reset")


# Global metrics instance
metrics = Metrics()


# =============================================================================
# Decorators
# =============================================================================


def timed(name: str):
    """
    Decorator to measure async function execution time.

    Records latency and success/error counts to global metrics.
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                metrics.increment(f"{name}_success")
                return result
            except Exception as e:
                metrics.increment(f"{name}_error")
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                metrics.record_latency(name, latency_ms)
                logger.debug(f"{name} completed in {latency_ms:.2f}ms")

        return wrapper

    return decorator


def counted(name: str):
    """Decorator to count function invocations."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            metrics.increment(f"{name}_calls")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# Request Tracing
# =============================================================================


@asynccontextmanager
async def traced_request(name: str):
    """
    Context manager for tracing requests with correlation IDs.

    Usage:
        async with traced_request("get_directions") as correlation_id:
            # All logs within this block will include the correlation_id
            result = await some_api_call()
    """
    correlation_id = str(uuid.uuid4())[:8]
    correlation_filter.set_correlation_id(correlation_id)
    logger.info(f"Starting {name}")

    start = time.perf_counter()
    try:
        yield correlation_id
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(f"Completed {name} in {latency_ms:.2f}ms")
        correlation_filter.set_correlation_id(None)


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())[:8]
