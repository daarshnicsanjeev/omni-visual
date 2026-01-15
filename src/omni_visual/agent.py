"""
Omni-Visual Agent Definition.

Uses Google Maps MCP Server + custom vision tools.
Supports both API key and ADC authentication.

Optimized with:
- Multi-agent architecture (coordinator + vision specialist)
- Cache-integrated vision tools
- Enhanced prompts
"""

import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .prompts import AGENT_INSTRUCTION, COORDINATOR_INSTRUCTION
from .tools.vision import (
    get_overhead_view,
    get_street_view,
    explore_panoramic,
    close_http_client,
)
from .cache import overhead_cache, streetview_cache


# =============================================================================
# Cache-Integrated Vision Tools
# =============================================================================


async def cached_get_overhead_view(
    lat: float,
    lng: float,
    zoom: int,
    map_type: str,
) -> dict:
    """
    Get an overhead view with caching.
    
    Checks cache first, fetches from API if miss, caches successful responses.
    """
    # Check cache
    cached = overhead_cache.get(lat, lng, zoom=zoom, map_type=map_type)
    if cached:
        cached["from_cache"] = True
        return cached

    # Fetch from API
    result = await get_overhead_view(lat, lng, zoom, map_type)

    # Cache successful responses
    if result.get("success"):
        overhead_cache.set(lat, lng, result, zoom=zoom, map_type=map_type)

    return result


async def cached_get_street_view(
    lat: float,
    lng: float,
    heading: int,
    pitch: int,
    fov: int,
) -> dict:
    """
    Get a street view with caching.
    
    Checks cache first, fetches from API if miss, caches successful responses.
    """
    # Check cache
    cached = streetview_cache.get(
        lat, lng, heading=heading, pitch=pitch, fov=fov
    )
    if cached:
        cached["from_cache"] = True
        return cached

    # Fetch from API
    result = await get_street_view(lat, lng, heading, pitch, fov)

    # Cache successful responses
    if result.get("success"):
        streetview_cache.set(
            lat, lng, result, heading=heading, pitch=pitch, fov=fov
        )

    return result


# =============================================================================
# MCP Configuration
# =============================================================================


def get_mcp_env() -> dict:
    """Get environment variables for MCP Google Maps server."""
    env = {}

    # Try API key first
    maps_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if maps_key:
        env["GOOGLE_MAPS_API_KEY"] = maps_key

    # Also pass through GCP project for ADC
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        env["GOOGLE_CLOUD_PROJECT"] = project
        env["GCLOUD_PROJECT"] = project

    return env


# Create MCP toolset for Google Maps
maps_mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-google-maps"],
            env=get_mcp_env(),
        ),
    ),
)


# =============================================================================
# Agent Definitions
# =============================================================================

# Determine if multi-agent mode is enabled
MULTI_AGENT_MODE = os.environ.get("OMNI_VISUAL_MULTI_AGENT", "false").lower() == "true"

# Model selection (configurable via environment)
# Available models: gemini-3-pro-preview, gemini-3-flash-preview, gemini-2.5-pro, gemini-2.5-flash
FAST_MODEL = os.environ.get("OMNI_VISUAL_FAST_MODEL", "gemini-3-flash-preview")
VISION_MODEL = os.environ.get("OMNI_VISUAL_VISION_MODEL", "gemini-3-pro-preview")


if MULTI_AGENT_MODE:
    # Multi-agent architecture for cost optimization
    
    # Fast coordinator for routing and simple queries
    coordinator_agent = Agent(
        name="coordinator",
        model=FAST_MODEL,
        description="Routes queries to appropriate specialists and handles simple searches",
        instruction=COORDINATOR_INSTRUCTION,
        tools=[maps_mcp_toolset],
    )

    # Powerful vision specialist
    vision_specialist = Agent(
        name="vision_specialist",
        model=VISION_MODEL,
        description="Handles all visual exploration and image analysis",
        instruction=AGENT_INSTRUCTION,
        tools=[
            cached_get_overhead_view,
            cached_get_street_view,
            explore_panoramic,
        ],
    )

    # Note: For a true multi-agent setup, you would use SequentialAgent or
    # a custom orchestrator. This is a simplified version that exposes
    # both agents - the application layer chooses which to invoke.
    
    # For ADK compatibility, we expose the vision specialist as root
    # The coordinator can be used separately when needed
    root_agent = vision_specialist
    
else:
    # Single unified agent (default)
    root_agent = Agent(
        name="vision_agent",
        model=VISION_MODEL,
        description="Blind accessibility guide with Google Maps and camera control",
        instruction=AGENT_INSTRUCTION,
        tools=[
            maps_mcp_toolset,
            cached_get_overhead_view,
            cached_get_street_view,
            explore_panoramic,
        ],
    )


# =============================================================================
# Cleanup
# =============================================================================


async def cleanup():
    """Cleanup resources on shutdown."""
    await close_http_client()
