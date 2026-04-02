"""
Plugin system for TG Media Downloader.

Provides the abstract base class for plugins and a registry for plugin management.
"""

from abc import ABC, abstractmethod

from pyrogram.types import Message


class BasePlugin(ABC):
    """
    Abstract base class for all download plugins.

    Each plugin must implement the name property, can_handle(), and execute() methods.
    The cleanup() method is optional and should be implemented if the plugin needs
    to release resources on shutdown.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Return the unique identifier for this plugin.

        :return: A string identifying the plugin (e.g., 'media', 'greenvideo')
        """

    @abstractmethod
    def can_handle(self, message: Message) -> bool:
        """
        Determine if this plugin can handle the given message.

        :param message: The incoming Telegram message to classify
        :return: True if this plugin can handle the message, False otherwise
        """

    @abstractmethod
    async def execute(self, message: Message, reply: Message) -> None:
        """
        Execute the download logic for the given message.

        This method is called by the worker after dequeuing a job. It should handle
        all download operations, progress updates, and error handling for the message.

        :param message: The original Telegram message containing media or URL
        :param reply: The reply message object for status updates
        """

    async def cleanup(self) -> None:
        """
        Optional cleanup method called during bot shutdown.

        Override this method if the plugin needs to release resources
        (e.g., close browser instances, cancel pending tasks).
        """
        pass
