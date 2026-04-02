"""
Plugin router for classifying incoming messages and dispatching to the correct plugin.
"""

import logging
from typing import TYPE_CHECKING

from pyrogram.types import Message

if TYPE_CHECKING:
    from modules.plugins.base import BasePlugin


class PluginRouter:
    """
    Router that classifies incoming messages and dispatches to the correct plugin.

    Maintains a list of registered plugins and iterates through them to find
    the first plugin whose can_handle() method returns True for a given message.
    """

    def __init__(self) -> None:
        self._plugins: list["BasePlugin"] = []

    def register_plugin(self, plugin: "BasePlugin") -> None:
        """
        Register a plugin with the router.

        Plugins are checked in registration order. The first plugin whose
        can_handle() returns True will handle the message.

        :param plugin: A BasePlugin instance to register
        """
        self._plugins.append(plugin)
        logging.info(f"Router registered plugin: {plugin.name}")

    def classify(self, message: Message) -> "BasePlugin | None":
        """
        Classify a message and return the matching plugin.

        Iterates through registered plugins in order and returns the first
        one whose can_handle() method returns True.

        :param message: The incoming Telegram message to classify
        :return: The matching plugin, or None if no plugin matches
        """
        for plugin in self._plugins:
            if plugin.can_handle(message):
                return plugin
        return None
