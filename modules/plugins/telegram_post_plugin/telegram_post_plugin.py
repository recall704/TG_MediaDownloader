"""
Telegram Post Video plugin for downloading videos from Telegram public channel posts.

Handles text messages containing Telegram post links (t.me/username/post_id).
"""

import asyncio
import logging
import os
import time
from urllib.parse import urlparse

from pyrogram import Client
from pyrogram.errors import (
    MessageIdInvalid,
    ChannelInvalid,
    UsernameNotOccupied,
    MessageNotModified,
    FloodWait,
)
from pyrogram.types import Message

from modules.plugins.base import BasePlugin
from modules.ConfigManager import ConfigManager
from modules.utils import extract


def format_size(size_bytes: int) -> str:
    """
    Format file size in bytes to a human-readable string.

    :param size_bytes: File size in bytes
    :return: Formatted size string (e.g., "10.5 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable format.

    :param seconds: Duration in seconds
    :return: A human-readable string (e.g., "2h 15m 30s")
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


class TelegramPostVideoPlugin(BasePlugin):
    """
    Plugin for downloading videos from Telegram public channel posts.

    Handles text messages containing Telegram post links (t.me/username/post_id).
    Uses the Pyrogram client to resolve the chat and download the video.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        client: Client,
        safe_edit,
    ) -> None:
        """
        Initialize the TelegramPostVideoPlugin.

        :param config_manager: The ConfigManager instance for accessing config
        :param client: The Pyrogram Client instance for resolving chats/messages
        :param safe_edit: The safe_edit_message function for status updates
        """
        self._config_manager = config_manager
        self._client = client
        self._safe_edit = safe_edit

    @property
    def name(self) -> str:
        return "telegram_post_video"

    def can_handle(self, message: Message) -> bool:
        """
        Check if this plugin can handle the given message.

        Returns True for text messages containing a Telegram link.

        :param message: The incoming Telegram message
        :return: True if this plugin can handle the message, False otherwise
        """
        if message.media is not None:
            return False

        if not message.text:
            return False

        url = extract.extract_url(message.text)
        if not url:
            return False

        return extract.is_telegram_link(url)

    async def execute(self, message: Message, reply: Message) -> None:
        """
        Download video from the Telegram post link in the message.

        :param message: The original Telegram message containing a Telegram link
        :param reply: The reply message object for status updates
        """
        url = extract.extract_url(message.text)

        await self._safe_edit(reply, "🔍 正在解析帖子链接...")

        try:
            parsed = urlparse(url)
            path_parts = parsed.path.strip("/").split("/")

            if len(path_parts) < 2 or path_parts[0] == "c":
                await self._safe_edit(
                    reply, "❌ 仅支持公开频道链接，私有频道链接无法访问"
                )
                return

            username = path_parts[0]
            message_id = int(path_parts[1])

            chat = await self._client.get_chat(username)
            logging.info(f"Resolved chat: {chat.title} (id={chat.id})")

            msg = await self._client.get_messages(chat.id, message_id)
            if not msg:
                await self._safe_edit(reply, "❌ 无法获取消息，链接可能无效")
                return

            if not msg.video:
                await self._safe_edit(reply, "❌ 该消息中没有视频")
                return

            video = msg.video
            file_name = video.file_name or f"{video.file_unique_id}.mp4"
            file_path = os.path.join(
                self._config_manager.get_config().TG_DOWNLOAD_PATH, file_name
            )

            await self._safe_edit(
                reply, f"📥 开始下载视频: {file_name}\nDownloading: 0%"
            )

            start_time = time.time()
            progress_state: list[Message | int] = [reply, 0]
            await msg.download(
                file_name=file_path,
                progress=self._progress_callback,
                progress_args=(progress_state,),
            )
            end_time = time.time()
            duration = end_time - start_time
            duration_str = format_duration(duration)
            finish_time = time.strftime("%H:%M", time.localtime())

            await self._safe_edit(
                reply,
                f"✅ 下载完成！\n"
                f"文件: {file_name}\n"
                f"大小: {format_size(video.file_size)}\n"
                f"完成时间: {finish_time}\n"
                f"耗时: {duration_str}",
            )
            logging.info(f"Telegram post video downloaded: {file_name}")

        except asyncio.CancelledError:
            logging.warning("Telegram post video download cancelled")
            await self._safe_edit(reply, "Aborted")
            raise
        except (ValueError, IndexError):
            await self._safe_edit(
                reply, "❌ 链接格式不正确，请使用 https://t.me/username/post_id 格式"
            )
        except UsernameNotOccupied:
            await self._safe_edit(reply, "❌ 频道不存在或用户名无效")
        except ChannelInvalid:
            await self._safe_edit(reply, "❌ 无法访问该频道，可能已被解散或您无权访问")
        except MessageIdInvalid:
            await self._safe_edit(reply, "❌ 消息不存在或已被删除")
        except Exception as e:
            await self._safe_edit(reply, f"❌ 下载失败: {str(e)}")
            import traceback

            logging.error(
                f"Error downloading telegram post video: {e}, {traceback.format_exc()}"
            )

    @staticmethod
    async def _progress_callback(
        current: int, total: int, reply: list[Message | int]
    ) -> None:
        """
        Update download progress on the reply message.

        :param current: Current bytes downloaded
        :param total: Total bytes to download
        :param reply: List containing [message, last_reported_status] (mutable for updates)
        """
        from modules.helpers import safe_edit_message

        if total == 0:
            return

        status = int(current * 100 / total)
        message = reply[0]

        if status == 0 or status % 5 != 0:
            return

        last_reported = reply[1] if len(reply) > 1 else 0
        if status == last_reported:
            return

        if not isinstance(message, Message) or message.text is None:
            return

        try:
            result = await safe_edit_message(message, f"Downloading: {status}%")
            if result:
                reply[0] = result
                if len(reply) > 1:
                    reply[1] = status
                else:
                    reply.append(status)
        except (MessageNotModified, FloodWait):
            pass
        except Exception as e:
            logging.debug(f"Progress edit failed (non-fatal): {e}")
