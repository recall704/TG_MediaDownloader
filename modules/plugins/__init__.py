"""
Plugin system for TG Media Downloader.
"""

from modules.plugins.base import BasePlugin
from modules.plugins.registry import PluginRegistry

__all__ = ["BasePlugin", "PluginRegistry"]
