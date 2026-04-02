"""
Media plugin for downloading native Telegram media files.

Handles photo, video, document, audio, animation, and voice messages.
"""

import asyncio
import logging
import os
import time

from pyrogram.errors import MessageNotModified
from pyrogram.enums import MessageMediaType
from pyrogram.types import Message, Photo, Voice, Video, Animation, Audio, Document

from modules.plugins.base import BasePlugin
from modules.ConfigManager import ConfigManager


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable format.

    :param seconds: Duration in seconds
    :return: A human-readable string (e.g., "2h 15m 30s", "45s", "5m 20s")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def get_extension(
    media_type: MessageMediaType,
    media: Photo | Voice | Video | Animation | Audio | Document,
) -> str:
    """
    Return the most probable file extension based on the media type.

    :param media_type: The media_type property of a message
    :param media: The media object of a message
    :return: A string corresponding to the file extension
    """
    if media_type == MessageMediaType.PHOTO:
        return "jpg"
    else:
        default = "unknown"
        if media_type in [MessageMediaType.VOICE, MessageMediaType.AUDIO]:
            default = "mp3"
        elif media_type in [MessageMediaType.ANIMATION, MessageMediaType.VIDEO]:
            default = "mp4"
        return default if not media.mime_type else media.mime_type.split("/")[1]


class MediaPlugin(BasePlugin):
    """
    Plugin for downloading native Telegram media files.

    Handles photo, video, document, audio, animation, and voice messages.
    Unsupported types (sticker, contact, location, venue, poll, web_page, dice, game, video_note)
    are rejected by can_handle().
    """

    UNSUPPORTED_TYPES = [
        MessageMediaType.STICKER,
        MessageMediaType.CONTACT,
        MessageMediaType.LOCATION,
        MessageMediaType.VENUE,
        MessageMediaType.POLL,
        MessageMediaType.WEB_PAGE,
        MessageMediaType.DICE,
        MessageMediaType.GAME,
        MessageMediaType.VIDEO_NOTE,
    ]

    def __init__(
        self,
        config_manager: ConfigManager,
        safe_edit,
    ) -> None:
        """
        Initialize the MediaPlugin.

        :param config_manager: The ConfigManager instance for accessing config
        :param safe_edit: The safe_edit_message function for status updates
        """
        self._config_manager = config_manager
        self._safe_edit = safe_edit

    @property
    def name(self) -> str:
        return "media"

    def can_handle(self, message: Message) -> bool:
        """
        Check if this plugin can handle the given message.

        Returns True for media messages that are not in the unsupported types list.
        Also returns False for media without a filename (except photo/voice which
        trigger the rename flow handled by the callback handler).

        :param message: The incoming Telegram message
        :return: True if this plugin can handle the message, False otherwise
        """
        if message.media is None:
            return False

        if message.media in self.UNSUPPORTED_TYPES:
            return False

        return True

    async def execute(self, message: Message, reply: Message) -> None:
        """
        Download the media file from the message.

        This method handles the actual download operation, including progress updates,
        timeout handling, and error reporting.

        :param message: The original Telegram message containing media
        :param reply: The reply message object for status updates
        """
        file_name = self._resolve_file_name(message)
        if not file_name:
            await self._safe_edit(reply, "❌ 无法解析文件名")
            return

        file_path = os.path.join(
            self._config_manager.get_config().TG_DOWNLOAD_PATH, file_name
        )

        try:
            start_time = time.time()
            logging.info(f"{file_name} - Download started")
            await self._safe_edit(reply, "Downloading:  0%")

            task = asyncio.get_event_loop().create_task(
                message.download(
                    file_path,
                    progress=self._progress_callback,
                    progress_args=([reply],),
                )
            )

            await asyncio.wait_for(
                task, timeout=self._config_manager.get_config().TG_DL_TIMEOUT
            )

            end_time = time.time()
            duration = end_time - start_time
            duration_str = format_duration(duration)
            logging.info(
                f"{file_name} - Successfully downloaded (duration: {duration_str})"
            )

            finish_time = time.strftime("%H:%M", time.localtime())
            await self._safe_edit(
                reply, f"Finished at {finish_time}\nDuration: {duration_str}"
            )

        except asyncio.CancelledError:
            logging.warning(f"{file_name} - Aborted")
            await self._safe_edit(reply, "Aborted")
            raise
        except asyncio.TimeoutError:
            logging.error(f"{file_name} - TIMEOUT ERROR")
            await self._safe_edit(
                reply, "**ERROR:** __Timeout reached downloading this file__"
            )
        except MessageNotModified:
            pass
        except Exception as e:
            logging.error(f"{file_name} - {str(e)}")
            await self._safe_edit(
                reply,
                f"**ERROR:** Exception {(e.__class__.__name__, str(e))} raised downloading this file: {file_name}",
            )

    def _resolve_file_name(self, message: Message) -> str | None:
        """
        Resolve the file name from the message media object.

        For media with a file_name attribute (video, document, audio, animation),
        returns the file_name. For photo/voice, returns file_unique_id with extension.

        Note: The rename flow (asking user for custom filename) is handled by the
        callback handler in tg_downloader.py, not here. By the time execute() is
        called, the file_name should already be resolved.

        :param message: The Telegram message containing media
        :return: The resolved file name, or None if cannot be resolved
        """
        media_type = message.media

        if media_type == MessageMediaType.PHOTO:
            media = message.photo
            ext = get_extension(media_type, media)
            return f"{media.file_unique_id}.{ext}"

        if media_type == MessageMediaType.VOICE:
            media = message.voice
            ext = get_extension(media_type, media)
            return f"{media.file_unique_id}.{ext}"

        if media_type in [
            MessageMediaType.VIDEO,
            MessageMediaType.DOCUMENT,
            MessageMediaType.AUDIO,
            MessageMediaType.ANIMATION,
        ]:
            media = getattr(message, media_type.value)
            if media and media.file_name:
                return media.file_name
            elif media:
                ext = get_extension(media_type, media)
                return f"{media.file_unique_id}.{ext}"

        return None

    @staticmethod
    async def _progress_callback(current, total, reply: list[Message]) -> None:
        """
        Update download progress on the reply message.

        :param current: Current bytes downloaded
        :param total: Total bytes to download
        :param reply: List containing the reply message (mutable for updates)
        """
        from tg_downloader import safe_edit_message

        status = int(current * 100 / total)
        message = reply[0]
        if status != 0 and status % 5 == 0 and str(status) not in message.text:
            result = await safe_edit_message(message, f"Downloading: {status}%")
            if result:
                reply[0] = result
