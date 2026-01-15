"""
Configuration module for Omni-Visual Accessibility Navigator.

Handles loading and validation of environment variables.
"""

import os
from functools import lru_cache
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigError(Exception):
    """Raised when required configuration is missing."""
    pass


@lru_cache
def get_google_api_key() -> str:
    """
    Get the Google API key for Gemini/ADK access.
    
    Returns:
        The GOOGLE_API_KEY from environment.
        
    Raises:
        ConfigError: If the key is not set.
    """
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ConfigError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Copy .env.example to .env and add your API key."
        )
    return key


@lru_cache
def get_maps_api_key() -> str:
    """
    Get the Google Maps Platform API key.
    
    Returns:
        The MAPS_API_KEY from environment.
        
    Raises:
        ConfigError: If the key is not set.
    """
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("MAPS_API_KEY")
    if not key:
        raise ConfigError(
            "GOOGLE_MAPS_API_KEY environment variable is not set. "
            "Copy .env.example to .env and add your Google Maps API key."
        )
    return key


def get_server_config() -> dict:
    """
    Get server configuration settings.
    
    Returns:
        dict with host, port, and other server settings.
    """
    return {
        "host": os.getenv("SERVER_HOST", "0.0.0.0"),
        "port": int(os.getenv("SERVER_PORT", "8000")),
        "reload": os.getenv("SERVER_RELOAD", "false").lower() == "true",
    }


def validate_config() -> bool:
    """
    Validate that all required configuration is present.
    
    Returns:
        True if all required config is valid.
        
    Raises:
        ConfigError: If any required configuration is missing.
    """
    get_google_api_key()
    get_maps_api_key()
    return True
