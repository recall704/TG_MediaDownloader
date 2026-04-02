"""
Command plugin for handling bot commands (/start, /help, /about, /abort, /status, /usage, etc.).

Handles all text-based bot commands that don't involve media downloads.
"""

import logging

from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from modules.plugins.base import BasePlugin
from modules.ConfigManager import ConfigManager

GITHUB_LINK: str = "https://github.com/LightDestory/TG_MediaDownloader"
DONATION_LINK: str = "https://ko-fi.com/lightdestory"

SUPPORTED_COMMANDS = [
    "/start",
    "/help",
    "/about",
    "/abort",
    "/status",
    "/usage",
    "/set_download_dir",
    "/set_max_parallel_dl",
    "/listen_forward",
    "/stop_listen",
    "/forward_status",
]


class CommandPlugin(BasePlugin):
    """
    Plugin for handling bot commands.

    Handles /start, /help, /about, /abort, /status, /usage, and configuration commands.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        safe_edit,
        abort_callback,
        forward_listener_module=None,
    ) -> None:
        """
        Initialize the CommandPlugin.

        :param config_manager: The ConfigManager instance for accessing config
        :param safe_edit: The safe_edit_message function for status updates
        :param abort_callback: The abort() function to cancel pending downloads
        :param forward_listener_module: The forward_listener module for forward commands
        """
        self._config_manager = config_manager
        self._safe_edit = safe_edit
        self._abort_callback = abort_callback
        self._forward_listener = forward_listener_module

    @property
    def name(self) -> str:
        return "command"

    def can_handle(self, message: Message) -> bool:
        """
        Check if this plugin can handle the given message.

        Returns True for text messages that start with a supported command.

        :param message: The incoming Telegram message
        :return: True if this plugin can handle the message, False otherwise
        """
        if message.text is None:
            return False

        text = message.text.strip().lower()
        return any(text.startswith(cmd) for cmd in SUPPORTED_COMMANDS)

    async def execute(self, message: Message, reply: Message) -> None:
        """
        Execute the appropriate command handler.

        :param message: The original Telegram message containing the command
        :param reply: The reply message object for status updates
        """
        text = message.text.strip()
        command = text.split()[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []

        logging.info(f"Executing command: {command} with args: {args}")

        try:
            handler = getattr(self, f"_handle_{command[1:]}", None)
            if handler:
                await handler(message, reply, args)
            else:
                await message.reply_text(f"Unknown command: {command}", quote=True)
        except Exception as e:
            logging.error(f"Error executing command {command}: {e}")
            await message.reply_text(f"Error executing command: {str(e)}", quote=True)

    async def _handle_start(self, message: Message, reply: Message, args: list) -> None:
        """Handle /start command."""
        text = (
            "👋 **Welcome!**\n\n"
            "I'm a Telegram Media Downloader Bot. Send me any media file and I'll download it for you!\n\n"
            "Use /help to see all available commands."
        )
        await message.reply_text(text, quote=True)

    async def _handle_help(self, message: Message, reply: Message, args: list) -> None:
        """Handle /help command."""
        text = (
            "**Available Commands:**\n\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/about - About the project\n"
            "/abort - Cancel all pending downloads\n"
            "/status - Show current configuration\n"
            "/usage - Usage instructions\n"
            "/set_download_dir <path> - Set download directory\n"
            "/set_max_parallel_dl <n> - Set max parallel downloads\n"
            "/listen_forward <source> <target> - Start listening to a channel\n"
            "/stop_listen <source> - Stop listening to a channel\n"
            "/forward_status - Show active forward listeners"
        )
        await message.reply_text(text, quote=True)

    async def _handle_about(self, message: Message, reply: Message, args: list) -> None:
        """Handle /about command."""
        text = (
            "**TG Media Downloader Bot**\n\n"
            "A Telegram bot based on Pyrogram that downloads media files (>10MB) to local storage.\n"
            f"📦 GitHub: {GITHUB_LINK}\n"
            f"☕ Donate: {DONATION_LINK}"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("GitHub", url=GITHUB_LINK),
                    InlineKeyboardButton("Donate", url=DONATION_LINK),
                ]
            ]
        )
        await message.reply_text(text, quote=True, reply_markup=keyboard)

    async def _handle_abort(self, message: Message, reply: Message, args: list) -> None:
        """Handle /abort command."""
        await self._abort_callback()
        await message.reply_text(
            "✅ All pending downloads have been aborted.", quote=True
        )

    async def _handle_status(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /status command."""
        config = self._config_manager.get_config()
        text = (
            "**Current Configuration:**\n\n"
            f"📁 Download Path: `{config.TG_DOWNLOAD_PATH}`\n"
            f"🔄 Max Parallel Downloads: `{config.TG_MAX_PARALLEL}`\n"
            f"⏱️ Download Timeout: `{config.TG_DL_TIMEOUT}s`"
        )
        await message.reply_text(text, quote=True)

    async def _handle_usage(self, message: Message, reply: Message, args: list) -> None:
        """Handle /usage command."""
        text = (
            "**Usage Instructions:**\n\n"
            "1. Send me any media file (photo, video, document, audio, etc.)\n"
            "2. I'll download it to the configured directory\n"
            "3. Use /status to check current settings\n"
            "4. Use /set_download_dir to change download location\n"
            "5. Use /abort to cancel pending downloads\n\n"
            "**Forward Listening:**\n"
            "Use /listen_forward to forward messages from one channel to another."
        )
        await message.reply_text(text, quote=True)

    async def _handle_set_download_dir(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /set_download_dir command."""
        if not args:
            config = self._config_manager.get_config()
            await message.reply_text(
                f"Current download directory: `{config.TG_DOWNLOAD_PATH}`\n\n"
                "Usage: `/set_download_dir /path/to/dir`",
                quote=True,
            )
            return

        new_path = args[0]
        config = self._config_manager.get_config()
        config.TG_DOWNLOAD_PATH = new_path
        self._config_manager.load_config(config)
        self._config_manager.save_config_to_file()

        await message.reply_text(
            f"✅ Download directory set to: `{new_path}`", quote=True
        )

    async def _handle_set_max_parallel_dl(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /set_max_parallel_dl command."""
        if not args:
            config = self._config_manager.get_config()
            await message.reply_text(
                f"Current max parallel downloads: `{config.TG_MAX_PARALLEL}`\n\n"
                "Usage: `/set_max_parallel_dl <number>`",
                quote=True,
            )
            return

        try:
            new_value = int(args[0])
            if new_value < 1:
                raise ValueError("Must be at least 1")

            config = self._config_manager.get_config()
            config.TG_MAX_PARALLEL = new_value
            self._config_manager.load_config(config)
            self._config_manager.save_config_to_file()

            await message.reply_text(
                f"✅ Max parallel downloads set to: `{new_value}`", quote=True
            )
        except ValueError as e:
            await message.reply_text(f"❌ Invalid value: {str(e)}", quote=True)

    async def _handle_listen_forward(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /listen_forward command."""
        if not self._forward_listener:
            await message.reply_text(
                "❌ Forward listener module not available.", quote=True
            )
            return

        if len(args) < 2:
            await message.reply_text(
                "Usage: `/listen_forward <source_link> <target_link>`\n\n"
                "Example: `/listen_forward https://t.me/channel1 https://t.me/channel2`",
                quote=True,
            )
            return

        source_link = args[0]
        target_link = args[1]

        try:
            from modules import forward_listener

            listen_chat = forward_listener.listen_forward_chat
            key = f"{source_link} {target_link}"

            if key in listen_chat:
                await message.reply_text(
                    f"ℹ️ Already listening to: `{source_link}`\n"
                    f"Forwarding to: `{target_link}`\n\n"
                    f"Send the command again to stop.",
                    quote=True,
                )
            else:
                listen_chat[key] = {"source": source_link, "target": target_link}
                await message.reply_text(
                    f"✅ Now listening to: `{source_link}`\n"
                    f"Forwarding to: `{target_link}`",
                    quote=True,
                )
        except Exception as e:
            logging.error(f"Error setting up forward listener: {e}")
            await message.reply_text(f"❌ Error: {str(e)}", quote=True)

    async def _handle_stop_listen(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /stop_listen command."""
        if not self._forward_listener:
            await message.reply_text(
                "❌ Forward listener module not available.", quote=True
            )
            return

        if not args:
            await message.reply_text("Usage: `/stop_listen <source_link>`", quote=True)
            return

        source_link = args[0]

        try:
            from modules import forward_listener

            listen_chat = forward_listener.listen_forward_chat
            keys_to_remove = [k for k in listen_chat if k.startswith(source_link)]

            for key in keys_to_remove:
                del listen_chat[key]

            if keys_to_remove:
                await message.reply_text(
                    f"✅ Stopped listening to: `{source_link}`", quote=True
                )
            else:
                await message.reply_text(
                    f"No active listener found for: `{source_link}`", quote=True
                )
        except Exception as e:
            logging.error(f"Error stopping listener: {e}")
            await message.reply_text(f"❌ Error: {str(e)}", quote=True)

    async def _handle_forward_status(
        self, message: Message, reply: Message, args: list
    ) -> None:
        """Handle /forward_status command."""
        if not self._forward_listener:
            await message.reply_text(
                "❌ Forward listener module not available.", quote=True
            )
            return

        try:
            from modules import forward_listener

            listen_chat = forward_listener.listen_forward_chat

            if not listen_chat:
                await message.reply_text("No active forward listeners.", quote=True)
                return

            text = "**Active Forward Listeners:**\n\n"
            for key, value in listen_chat.items():
                parts = key.split(" ", 1)
                source = parts[0] if len(parts) > 0 else key
                target = parts[1] if len(parts) > 1 else "unknown"
                text += f"📡 `{source}` → `{target}`\n"

            await message.reply_text(text, quote=True)
        except Exception as e:
            logging.error(f"Error getting forward status: {e}")
            await message.reply_text(f"❌ Error: {str(e)}", quote=True)
