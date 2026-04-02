"""
Plugin registry for managing download plugins.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.plugins.base import BasePlugin


class PluginRegistry:
    """
    Registry for managing download plugins.

    Stores plugins in registration order and provides methods to retrieve
    and find plugins based on message classification.
    """

    def __init__(self) -> None:
        self._plugins: list["BasePlugin"] = []

    def register(self, plugin: "BasePlugin") -> None:
        """
        Register a plugin in the registry.

        :param plugin: A BasePlugin instance to register
        """
        self._plugins.append(plugin)
        logging.info(f"Plugin registered: {plugin.name}")

    def get_all(self) -> list["BasePlugin"]:
        """
        Return all registered plugins in registration order.

        :return: A list of all registered BasePlugin instances
        """
        return list(self._plugins)

    def find_plugin(self, message) -> "BasePlugin | None":
        """
        Find the first plugin that can handle the given message.

        Iterates through registered plugins in order and returns the first
        one whose can_handle() method returns True.

        :param message: The message to classify
        :return: The first matching plugin, or None if no plugin matches
        """
        for plugin in self._plugins:
            if plugin.can_handle(message):
                return plugin
        return None
