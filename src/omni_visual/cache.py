"""
In-memory caching for Google Maps API responses.

Provides TTL-based caching to avoid redundant API calls for repeated queries.
"""

import hashlib
import time
import logging
from typing import Any

logger = logging.getLogger("omni_visual.cache")


class ImageCache:
    """
    Simple TTL-based cache for API responses.
    
    Features:
    - Configurable TTL (time-to-live)
    - Configurable max size with LRU eviction
    - Cache hit/miss statistics
    - Thread-safe for async usage
    """

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 100):
        """
        Initialize the cache.
        
        Args:
            ttl_seconds: Time-to-live for cached entries (default 1 hour)
            max_size: Maximum number of entries before LRU eviction
        """
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._name = "unnamed"

    def set_name(self, name: str) -> "ImageCache":
        """Set a name for this cache (for logging)."""
        self._name = name
        return self

    def _make_key(self, lat: float, lng: float, **params) -> str:
        """Generate cache key from location and parameters."""
        # Round coordinates to 6 decimal places (~10cm precision)
        key_data = f"{lat:.6f}:{lng:.6f}:{sorted(params.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, lat: float, lng: float, **params) -> Any | None:
        """
        Get cached value if exists and not expired.
        
        Args:
            lat: Latitude coordinate
            lng: Longitude coordinate
            **params: Additional parameters that form part of the cache key
            
        Returns:
            Cached value if hit, None if miss or expired
        """
        key = self._make_key(lat, lng, **params)

        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self._ttl:
                self._hits += 1
                logger.debug(f"Cache HIT [{self._name}]: ({lat:.4f}, {lng:.4f})")
                return value
            else:
                # Expired entry
                del self._cache[key]
                logger.debug(f"Cache EXPIRED [{self._name}]: ({lat:.4f}, {lng:.4f})")

        self._misses += 1
        logger.debug(f"Cache MISS [{self._name}]: ({lat:.4f}, {lng:.4f})")
        return None

    def set(self, lat: float, lng: float, value: Any, **params) -> None:
        """
        Cache a value with current timestamp.
        
        Args:
            lat: Latitude coordinate
            lng: Longitude coordinate
            value: Value to cache
            **params: Additional parameters that form part of the cache key
        """
        # Evict oldest if at capacity (LRU-style)
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]
            logger.debug(f"Cache EVICT [{self._name}]: evicted oldest entry")

        key = self._make_key(lat, lng, **params)
        self._cache[key] = (time.time(), value)
        logger.debug(f"Cache SET [{self._name}]: ({lat:.4f}, {lng:.4f})")

    def stats(self) -> dict:
        """
        Return cache statistics.
        
        Returns:
            dict with hits, misses, hit_rate, and current size
        """
        total = self._hits + self._misses
        return {
            "name": self._name,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0,
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
        }

    def clear(self) -> None:
        """Clear all cached entries and reset statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.info(f"Cache CLEARED [{self._name}]")

    def invalidate(self, lat: float, lng: float, **params) -> bool:
        """
        Invalidate a specific cache entry.
        
        Args:
            lat: Latitude coordinate
            lng: Longitude coordinate
            **params: Additional parameters that form part of the cache key
            
        Returns:
            True if entry was found and removed, False otherwise
        """
        key = self._make_key(lat, lng, **params)
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache INVALIDATE [{self._name}]: ({lat:.4f}, {lng:.4f})")
            return True
        return False


# =============================================================================
# Global Cache Instances
# =============================================================================

# Cache for overhead/satellite views (longer TTL - imagery doesn't change often)
overhead_cache = ImageCache(ttl_seconds=3600, max_size=100).set_name("overhead")

# Cache for street view images (shorter TTL - street conditions can change)
streetview_cache = ImageCache(ttl_seconds=1800, max_size=100).set_name("streetview")


def get_all_cache_stats() -> dict:
    """Get statistics for all caches."""
    return {
        "overhead": overhead_cache.stats(),
        "streetview": streetview_cache.stats(),
    }


def clear_all_caches() -> None:
    """Clear all caches."""
    overhead_cache.clear()
    streetview_cache.clear()
