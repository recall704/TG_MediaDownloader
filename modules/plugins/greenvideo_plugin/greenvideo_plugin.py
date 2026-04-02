"""
GreenVideo plugin for downloading videos from external URLs.

Handles text messages containing non-Telegram URLs (YouTube, etc.)
by using the PlaywrightGreenVideoDownloader.
"""

import asyncio
import logging
import time

from pyrogram.types import Message

from modules.plugins.base import BasePlugin
from modules.ConfigManager import ConfigManager
from modules.utils import extract
from modules.tools.greenvideo.playwright_downloader import (
    PlaywrightGreenVideoDownloader,
)


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


class GreenVideoPlugin(BasePlugin):
    """
    Plugin for downloading videos from external URLs using GreenVideo.

    Handles text messages containing non-Telegram URLs (YouTube, etc.).
    Uses PlaywrightGreenVideoDownloader for video extraction and download.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        safe_edit,
    ) -> None:
        """
        Initialize the GreenVideoPlugin.

        :param config_manager: The ConfigManager instance for accessing config
        :param safe_edit: The safe_edit_message function for status updates
        """
        self._config_manager = config_manager
        self._safe_edit = safe_edit

    @property
    def name(self) -> str:
        return "greenvideo"

    def can_handle(self, message: Message) -> bool:
        """
        Check if this plugin can handle the given message.

        Returns True for text messages containing a non-Telegram URL.

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

        if extract.is_telegram_link(url):
            return False

        return True

    async def execute(self, message: Message, reply: Message) -> None:
        """
        Download video from the URL in the message using GreenVideo.

        :param message: The original Telegram message containing a URL
        :param reply: The reply message object for status updates
        """
        url = extract.extract_url(message.text)
        download_dir = self._config_manager.get_config().TG_DOWNLOAD_PATH
        downloader = PlaywrightGreenVideoDownloader()

        try:
            await self._safe_edit(reply, f"🔍 正在解析视频链接...{url}")

            result, headers = await downloader.extract_video_with_interception(
                url, headless=True
            )

            if not result or not result.get("downloads"):
                await self._safe_edit(reply, "❌ 无法解析视频链接或没有可下载的视频")
                logging.warning(f"Failed to extract video from URL: {url}")
                return

            title = result.get("title", "未知标题")
            platform = result.get("host_alias", result.get("host", "未知平台"))
            video_count = len(result["downloads"])

            await self._safe_edit(
                reply,
                f"✅ 找到视频！\n"
                f"标题: {title}\n"
                f"平台: {platform}\n"
                f"数量: {video_count} 个视频\n"
                f"开始下载...",
            )

            async def progress_callback(
                current: int, total: int, file_info: dict
            ) -> None:
                await self._progress_callback(current, total, file_info, reply)

            downloaded_files = await downloader.download_video(
                result,
                download_dir,
                download_timeout=self._config_manager.get_config().TG_DL_TIMEOUT,
                progress_callback=progress_callback,
            )

            if downloaded_files:
                finish_time = time.strftime("%H:%M", time.localtime())
                result_text = (
                    f"✅ 下载完成！\n"
                    f"完成时间: {finish_time}\n"
                    f"成功下载 {len(downloaded_files)} 个文件:\n"
                )
                for filepath in downloaded_files:
                    result_text += f"  • {filepath}\n"

                await self._safe_edit(reply, result_text)
                logging.info(
                    f"Successfully downloaded {len(downloaded_files)} files from {url}"
                )
            else:
                await self._safe_edit(reply, "❌ 下载失败")
                logging.error(f"Failed to download video from {url}")

        except asyncio.TimeoutError:
            await self._safe_edit(reply, "❌ 下载超时")
            logging.error(f"Timeout downloading video from {url}")
        except asyncio.CancelledError:
            logging.warning(f"GreenVideo download cancelled: {url}")
            await self._safe_edit(reply, "Aborted")
            raise
        except Exception as e:
            await self._safe_edit(reply, f"❌ 下载出错: {str(e)}")
            import traceback

            logging.error(
                f"Error downloading video from {url}: {e}, {traceback.format_exc()}"
            )

    @staticmethod
    async def _progress_callback(
        current: int, total: int, file_info: dict, reply_message: Message
    ) -> None:
        """
        GreenVideo download progress callback.

        :param current: Current bytes downloaded
        :param total: Total bytes to download
        :param file_info: File information dictionary
        :param reply_message: Reply message for progress updates
        """
        from tg_downloader import safe_edit_message

        if total > 0:
            progress = int(current * 100 / total)
            current_file = file_info.get("current_file", 1)
            total_files = file_info.get("total_files", 1)
            filename = file_info.get("filename", "unknown")

            last_update = file_info.get("last_update_time", 0)
            current_time = time.time()

            if current_time - last_update >= 10 or progress == 100:
                try:
                    update_time_str = time.strftime(
                        "%H:%M:%S", time.localtime(current_time)
                    )
                    await safe_edit_message(
                        reply_message,
                        f"📥 下载中...\n"
                        f"文件: {filename}\n"
                        f"进度: {current_file}/{total_files} - {progress}%\n"
                        f"大小: {current}/{total} bytes\n"
                        f"上次更新: {update_time_str}",
                    )
                    file_info["last_update_time"] = current_time
                except Exception:
                    pass
