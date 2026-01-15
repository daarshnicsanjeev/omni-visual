"""
Vision Tools for Omni-Visual Accessibility Navigator.

Provides dynamic camera control for exploring Google Maps data from
overhead (satellite/roadmap) and street-level (Street View) perspectives.

Optimized with:
- HTTP connection pooling
- Parallel panoramic capture
- Image compression
- Retry logic with exponential backoff
- Observability (logging, metrics)
"""

import asyncio
import base64
import io
import logging
import math
import os
import time
from typing import Literal, Tuple

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# Configure logging
logger = logging.getLogger("omni_visual.vision")


# =============================================================================
# Proximity Math Utilities
# =============================================================================


def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth.
    
    Uses the Haversine formula for accurate short-distance calculations.
    This is useful for determining if two locations are "immediately adjacent"
    without calling the Distance Matrix API.
    
    Args:
        lat1, lon1: First point coordinates (decimal degrees)
        lat2, lon2: Second point coordinates (decimal degrees)
    
    Returns:
        Distance in meters
    """
    R = 6371e3  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the initial bearing (direction) from point 1 to point 2.
    
    Args:
        lat1, lon1: Origin coordinates
        lat2, lon2: Destination coordinates
    
    Returns:
        Bearing in degrees (0-360), where 0=North, 90=East, 180=South, 270=West
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    
    x = math.sin(delta_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    
    bearing = math.atan2(x, y)
    return (math.degrees(bearing) + 360) % 360


def get_relative_direction(user_heading: float, bearing_to_dest: float) -> str:
    """
    Determine the relative direction (left/right/ahead/behind) to a destination.
    
    Args:
        user_heading: User's current facing direction (0-360 degrees)
        bearing_to_dest: Bearing from user to destination (0-360 degrees)
    
    Returns:
        Human-readable direction like "to your RIGHT" or "AHEAD"
    """
    # Calculate relative angle (how far off from straight ahead)
    relative = (bearing_to_dest - user_heading + 360) % 360
    
    if relative <= 22.5 or relative > 337.5:
        return "directly AHEAD"
    elif 22.5 < relative <= 67.5:
        return "AHEAD and to your RIGHT (2 o'clock)"
    elif 67.5 < relative <= 112.5:
        return "to your RIGHT (3 o'clock)"
    elif 112.5 < relative <= 157.5:
        return "BEHIND and to your RIGHT (4 o'clock)"
    elif 157.5 < relative <= 202.5:
        return "directly BEHIND you"
    elif 202.5 < relative <= 247.5:
        return "BEHIND and to your LEFT (8 o'clock)"
    elif 247.5 < relative <= 292.5:
        return "to your LEFT (9 o'clock)"
    else:  # 292.5 < relative <= 337.5
        return "AHEAD and to your LEFT (10 o'clock)"


def is_immediate_vicinity(lat1: float, lon1: float, lat2: float, lon2: float, threshold_meters: float = 50.0) -> bool:
    """
    Check if two points are within immediate walking distance.
    
    Use this BEFORE calling maps_distance_matrix to avoid unnecessary API calls.
    Distance Matrix often returns inflated walking distances due to road routing.
    
    Args:
        lat1, lon1: First point
        lat2, lon2: Second point
        threshold_meters: Distance threshold (default 50m)
    
    Returns:
        True if points are within threshold distance
    """
    distance = calculate_haversine_distance(lat1, lon1, lat2, lon2)
    return distance <= threshold_meters


def get_proximity_info(
    origin_lat: float, origin_lon: float, 
    dest_lat: float, dest_lon: float,
    user_heading: float = 0
) -> dict:
    """
    Get comprehensive proximity information between two points.
    
    This is a convenience function that combines distance, bearing, and
    relative direction calculations.
    
    Args:
        origin_lat, origin_lon: User's position
        dest_lat, dest_lon: Destination position
        user_heading: User's current facing direction (default: North)
    
    Returns:
        Dictionary with distance_meters, bearing, relative_direction, and is_adjacent
    """
    distance = calculate_haversine_distance(origin_lat, origin_lon, dest_lat, dest_lon)
    bearing = calculate_bearing(origin_lat, origin_lon, dest_lat, dest_lon)
    relative = get_relative_direction(user_heading, bearing)
    
    return {
        "distance_meters": round(distance, 1),
        "bearing_degrees": round(bearing, 1),
        "relative_direction": relative,
        "is_adjacent": distance <= 50,
        "human_distance": f"{int(distance)} meters" if distance < 1000 else f"{distance/1000:.1f} km",
    }

# =============================================================================
# HTTP Client Pooling
# =============================================================================

_http_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def close_http_client():
    """Close the shared HTTP client (call on shutdown)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# =============================================================================
# Image Compression
# =============================================================================


def compress_image(
    image_bytes: bytes, quality: int = 60, max_size: int = 400
) -> bytes:
    """
    Compress image to reduce base64 size for faster token processing.

    Args:
        image_bytes: Raw image bytes
        quality: JPEG quality (1-100)
        max_size: Maximum dimension (width or height)

    Returns:
        Compressed image bytes
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))

        # Resize if larger than max_size
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Compress to JPEG
        output = io.BytesIO()
        # Convert to RGB if necessary (for PNG with transparency)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    except ImportError:
        logger.warning("Pillow not installed, skipping image compression")
        return image_bytes
    except Exception as e:
        logger.warning(f"Image compression failed: {e}, using original")
        return image_bytes


# =============================================================================
# API Key Management
# =============================================================================


def get_maps_api_key() -> str:
    """Get the Google Maps Platform API key from environment."""
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("MAPS_API_KEY")
    if not key:
        raise ValueError("GOOGLE_MAPS_API_KEY environment variable is not set")
    return key


# =============================================================================
# Error Handling
# =============================================================================


class APIError(Exception):
    """Base class for API errors."""

    pass


class RateLimitError(APIError):
    """Raised when API rate limit is hit."""

    pass


class QuotaExceededError(APIError):
    """Raised when API quota is exceeded."""

    pass


def categorize_http_error(status_code: int, response_text: str) -> APIError:
    """Categorize HTTP error into specific exception types."""
    if status_code == 429:
        return RateLimitError("Rate limit exceeded. Please wait before retrying.")
    elif status_code == 403 and "quota" in response_text.lower():
        return QuotaExceededError("API quota exceeded. Check your billing.")
    else:
        return APIError(f"HTTP {status_code}: {response_text}")


# =============================================================================
# Retry Logic
# =============================================================================


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    reraise=True,
)
async def _fetch_with_retry(
    client: httpx.AsyncClient, url: str, params: dict
) -> httpx.Response:
    """Fetch URL with automatic retry on transient failures."""
    response = await client.get(url, params=params)
    response.raise_for_status()
    return response


# =============================================================================
# Vision Tools
# =============================================================================


async def get_overhead_view(
    lat: float,
    lng: float,
    zoom: int,
    map_type: Literal["satellite", "roadmap"],
    compress: bool = True,
) -> dict:
    """
    Get an overhead/aerial view of a location using Google Static Maps API.

    The agent must dynamically decide the zoom level based on context:
    - Zoom 10-12: City/region overview ("What city is this?")
    - Zoom 15: Neighborhood level (general area layout)
    - Zoom 18: Street layouts and intersections
    - Zoom 20-21: Detailed features like medians, dividers, crosswalks

    Args:
        lat: Latitude coordinate of the location.
        lng: Longitude coordinate of the location.
        zoom: Zoom level (0-21). Higher = more detail.
        map_type: Type of map view - "satellite" for physical features or "roadmap" for labeled streets.
        compress: Whether to compress the image (reduces quality but faster).

    Returns:
        dict with image_data (base64), description, and success status.
    """
    start_time = time.perf_counter()
    api_key = get_maps_api_key()

    # Validate zoom range
    zoom = max(0, min(21, zoom))

    # Construct Static Maps API URL
    base_url = "https://maps.googleapis.com/maps/api/staticmap"
    params = {
        "center": f"{lat},{lng}",
        "zoom": zoom,
        "size": "400x400",
        "maptype": map_type,
        "key": api_key,
    }

    logger.info(
        f"Fetching overhead view: lat={lat}, lng={lng}, zoom={zoom}, type={map_type}"
    )

    try:
        client = await get_http_client()
        response = await _fetch_with_retry(client, base_url, params)

        image_bytes = response.content
        if compress:
            image_bytes = compress_image(image_bytes)

        image_data = base64.b64encode(image_bytes).decode("utf-8")

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Overhead view fetched in {latency_ms:.2f}ms")

        return {
            "success": True,
            "image_data": image_data,
            "mime_type": "image/png" if not compress else "image/jpeg",
            "description": f"Overhead {map_type} view at ({lat}, {lng}), zoom level {zoom}",
            "parameters": {
                "lat": lat,
                "lng": lng,
                "zoom": zoom,
                "map_type": map_type,
            },
            "latency_ms": latency_ms,
        }
    except httpx.HTTPStatusError as e:
        error = categorize_http_error(e.response.status_code, e.response.text)
        logger.error(f"Overhead view failed: {error}")
        return {
            "success": False,
            "error": str(error),
        }
    except Exception as e:
        logger.error(f"Overhead view failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def get_street_view(
    lat: float,
    lng: float,
    heading: int,
    pitch: int,
    fov: int,
    compress: bool = True,
) -> dict:
    """
    Get a street-level view using Google Street View Static API.

    Args:
        lat: Latitude coordinate of the location.
        lng: Longitude coordinate of the location.
        heading: Compass direction (0-360). 0=North, 90=East, 180=South, 270=West.
        pitch: Vertical camera angle (-90 to 90). 0=horizontal, +30=look up, -30=look down.
        fov: Field of view (20-120). Lower=zoomed in for reading signs, Higher=wide angle.
        compress: Whether to compress the image (reduces quality but faster).

    Returns:
        dict with image_data (base64), description, and success status.
    """
    start_time = time.perf_counter()
    api_key = get_maps_api_key()

    # Normalize parameters
    heading = heading % 360
    pitch = max(-90, min(90, pitch))
    fov = max(20, min(120, fov))

    # Construct Street View Static API URL
    base_url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "location": f"{lat},{lng}",
        "size": "400x400",
        "heading": heading,
        "pitch": pitch,
        "fov": fov,
        "key": api_key,
    }

    # Direction names for description
    direction_names = {
        (0, 45): "North",
        (45, 90): "Northeast",
        (90, 135): "East",
        (135, 180): "Southeast",
        (180, 225): "South",
        (225, 270): "Southwest",
        (270, 315): "West",
        (315, 360): "Northwest",
    }

    facing = "North"
    for (low, high), name in direction_names.items():
        if low <= heading < high:
            facing = name
            break

    pitch_desc = (
        "eye level"
        if -15 <= pitch <= 15
        else ("looking up" if pitch > 15 else "looking down")
    )

    logger.info(
        f"Fetching street view: lat={lat}, lng={lng}, heading={heading}, facing={facing}"
    )

    try:
        client = await get_http_client()
        response = await _fetch_with_retry(client, base_url, params)

        image_bytes = response.content
        if compress:
            image_bytes = compress_image(image_bytes)

        image_data = base64.b64encode(image_bytes).decode("utf-8")

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Street view fetched in {latency_ms:.2f}ms")

        return {
            "success": True,
            "image_data": image_data,
            "mime_type": "image/jpeg",
            "description": f"Street view facing {facing} ({heading}°), {pitch_desc}, FOV {fov}°",
            "parameters": {
                "lat": lat,
                "lng": lng,
                "heading": heading,
                "pitch": pitch,
                "fov": fov,
                "facing": facing,
            },
            "latency_ms": latency_ms,
        }
    except httpx.HTTPStatusError as e:
        error = categorize_http_error(e.response.status_code, e.response.text)
        logger.error(f"Street view failed: {error}")
        return {
            "success": False,
            "error": str(error),
        }
    except Exception as e:
        logger.error(f"Street view failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def explore_panoramic(
    lat: float,
    lng: float,
    pitch: int = 0,
    fov: int = 90,
) -> dict:
    """
    Capture a full 360° panoramic view by taking 4 images at cardinal directions.
    Uses parallel requests for 4x faster execution.

    Use this when the user says "Look around" to systematically explore
    all directions and provide a comprehensive description.

    Args:
        lat: Latitude coordinate of the location.
        lng: Longitude coordinate of the location.
        pitch: Vertical camera angle for all views (-90 to 90).
        fov: Field of view for all captures (20-120).

    Returns:
        dict with views (list of 4 street view results for N, E, S, W) and success status.
    """
    start_time = time.perf_counter()
    headings = [(0, "North"), (90, "East"), (180, "South"), (270, "West")]

    logger.info(f"Starting panoramic capture at ({lat}, {lng})")

    # Create tasks for parallel execution
    tasks = [
        get_street_view(lat=lat, lng=lng, heading=h, pitch=pitch, fov=fov, compress=True)
        for h, _ in headings
    ]

    # Execute all 4 requests in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    views = []
    all_success = True

    for (heading, direction), result in zip(headings, results):
        if isinstance(result, Exception):
            views.append({"success": False, "error": str(result), "direction": direction})
            all_success = False
        else:
            result["direction"] = direction
            views.append(result)
            if not result.get("success", False):
                all_success = False

    latency_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"Panoramic capture completed in {latency_ms:.2f}ms")

    return {
        "success": all_success,
        "views": views,
        "description": f"360° panoramic capture at ({lat}, {lng})",
        "latency_ms": latency_ms,
    }
