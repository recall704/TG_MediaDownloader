"""
GreenVideo plugin for downloading videos from external URLs.

Handles text messages containing non-Telegram URLs (YouTube, etc.)
by using the GreenVideo API client.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from pyrogram.types import Message

from modules.ConfigManager import ConfigManager
from modules.helpers import format_duration
from modules.plugins.base import BasePlugin
from modules.plugins.greenvideo_plugin.greevideo_client import extract_video
from modules.utils import extract

CHUNK_SIZE = 8192
MAX_FILENAME_BYTES = 255
DEFAULT_EXT = ".mp4"
SUPPORTED_VIDEO_EXTENSIONS = ("mp4", "webm", "mkv", "avi", "mov", "flv", "wmv", "m4v")
SYSTEM_PATH_LIMIT = 4096
DEFAULT_TIMEOUT = 300


def _strip_tags(title: str) -> str:
    parts = title.split("#")
    cleaned = parts[0].strip().strip("。")
    return cleaned if cleaned else title


def _parse_response(data: dict) -> dict:
    """Parse API response data into the internal result format."""
    raw_title = data.get("displayTitle", "").strip()
    title = _strip_tags(raw_title) if raw_title else "video"

    result = {
        "vid": data.get("vid"),
        "host": data.get("host"),
        "host_alias": data.get("hostAlias"),
        "title": title,
        "status": data.get("status"),
        "downloads": [],
    }

    video_items = data.get("videoItemVoList", [])
    total = sum(
        1
        for item in video_items
        if item.get("baseUrl")
        and (
            item["baseUrl"].startswith("http://")
            or item["baseUrl"].startswith("https://")
        )
    )
    multiple = total > 1

    index = 0
    for item in video_items:
        url = item.get("baseUrl")
        file_type = item.get("fileType")
        quality = item.get("quality","")

        is_valid_url = url and (
            url.startswith("http://") or url.startswith("https://")
        )
        if quality == '封面':
            logging.info(f"skip this item {quality}")
            continue

        if is_valid_url:
            index += 1
            ext = _get_file_extension(url)
            filename = f"{title}_{index}{ext}" if multiple else f"{title}{ext}"
            download_info = {
                "url": url,
                "file_type": file_type,
                "size": item.get("size"),
                "filename": filename,
            }
            result["downloads"].append(download_info)

    return result


def _get_file_extension(url: str) -> str:
    """Extract file extension from a URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)

    ext = os.path.splitext(path)[1]
    if ext:
        return ext

    query = parsed.query
    pattern = r"\.(" + "|".join(SUPPORTED_VIDEO_EXTENSIONS) + r")(?:&|$)"
    ext_match = re.search(pattern, query, re.IGNORECASE)
    if ext_match:
        return f".{ext_match.group(1)}"

    return DEFAULT_EXT


def _sanitize_filename(filename: str, max_length: int = MAX_FILENAME_BYTES):
    """Clean filename by removing illegal characters and truncating if needed."""
    filename = re.sub(r'[<>\:"/\\|?*]', "_", filename)
    filename = filename.strip(". ")

    truncated = False
    while len(filename.encode("utf-8")) > max_length:
        filename = filename[:-1]
        truncated = True

    if not filename:
        filename = "video"

    return filename.encode("utf-8"), truncated


def _generate_safe_filename(
    filename: str, download_path: Path
) -> tuple[Path, bool]:
    """Sanitize filename and ensure it fits within file system path limits."""
    name, ext = os.path.splitext(filename)
    dir_path_str = str(download_path)
    dir_bytes = len(dir_path_str.encode("utf-8")) + 1
    max_filename_bytes = min(MAX_FILENAME_BYTES, SYSTEM_PATH_LIMIT - dir_bytes)
    ext_bytes_len = len(ext.encode("utf-8"))
    max_name_bytes = max(10, max_filename_bytes - ext_bytes_len)

    if max_name_bytes < 10:
        ext = ext[: max_filename_bytes - 10]
        max_name_bytes = 10

    safe_name_bytes, truncated = _sanitize_filename(name, max_name_bytes)
    final_filename_bytes = safe_name_bytes + ext.encode("utf-8")

    while (
        len(final_filename_bytes) > max_filename_bytes and len(safe_name_bytes) > 10
    ):
        safe_name_bytes = safe_name_bytes[:-1]
        final_filename_bytes = safe_name_bytes + ext.encode("utf-8")
        truncated = True

    if len(final_filename_bytes) > max_filename_bytes:
        timestamp = str(int(time.time()))
        safe_name_bytes = f"video_{timestamp}".encode()
        final_filename_bytes = safe_name_bytes + ext.encode("utf-8")
        logging.error("文件名过长，使用时间戳代替")

    safe_filename = safe_name_bytes.decode("utf-8")
    final_filename = safe_filename + ext

    if truncated:
        logging.warning(
            f"文件名过长已截断（{len(safe_name_bytes)}字节）: {name[:50]}..."
        )

    return download_path / final_filename, truncated


async def _download_single_file(
    url: str,
    filepath: Path,
    file_info: dict,
    progress_callback=None,
    download_timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = 3,
    retry_delay: int = 2,
) -> bool:
    """Download a single file with retry logic."""
    retry_count = 0

    while retry_count <= max_retries:
        try:
            request_headers = {
                "Referer": url,
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            }

            response = requests.get(
                url,
                headers=request_headers,
                stream=True,
                timeout=download_timeout,
            )
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            downloaded_size = 0

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback:
                            await progress_callback(
                                downloaded_size, total_size, file_info
                            )
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            logging.debug(
                                f"  进度: {progress:.1f}% "
                                f"({downloaded_size}/{total_size} bytes)"
                            )

            logging.info(f"  下载成功: {filepath}")
            return True

        except requests.exceptions.RequestException as e:
            retry_count += 1
            if retry_count <= max_retries:
                logging.warning(
                    f"  下载失败 (第{retry_count}次/{max_retries}重试): {e}"
                )
                await asyncio.sleep(retry_delay)
            else:
                logging.error(f"  下载失败 (已重试{max_retries}次): {e}")

        except OSError as e:
            if e.errno == 36 or "too long" in str(e).lower():
                logging.error(f"  文件名过长: {e}")
                return False
            retry_count += 1
            if retry_count <= max_retries:
                logging.warning(
                    f"  文件系统错误 (第{retry_count}次/{max_retries}重试): {e}"
                )
                await asyncio.sleep(retry_delay)
            else:
                logging.error(
                    f"  文件系统错误 (已重试{max_retries}次): {e}"
                )

        except Exception as e:
            retry_count += 1
            if retry_count <= max_retries:
                logging.warning(
                    f"  下载失败 (第{retry_count}次/{max_retries}重试): {e}"
                )
                await asyncio.sleep(retry_delay)
            else:
                logging.error(f"  下载失败 (已重试{max_retries}次): {e}")

    return False


async def download_video(
    result: dict,
    download_dir: str | Path,
    download_timeout: int = DEFAULT_TIMEOUT,
    progress_callback=None,
    max_retries: int = 3,
    retry_delay: int = 2,
) -> list[str]:
    """Download video files from the parsed result."""
    if not result or not result.get("downloads"):
        logging.warning("没有可下载的视频")
        return []

    vid = result.get("vid", "")
    download_path = Path(download_dir) / vid if vid else Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    downloaded_files: list[str] = []

    for i, download in enumerate(result["downloads"], 1):
        url = download["url"]
        filename = download["filename"]

        logging.info(f"正在下载 {i}/{len(result['downloads'])}")
        logging.info(f"  URL: {url}")

        filepath, _ = _generate_safe_filename(filename, download_path)
        logging.info(f"  保存到: {filepath}")

        file_info = {
            "current_file": i,
            "total_files": len(result["downloads"]),
            "filename": filepath.name,
            "url": url,
            "filepath": str(filepath),
        }

        success = await _download_single_file(
            url, filepath, file_info, progress_callback, download_timeout, max_retries, retry_delay
        )

        if success:
            downloaded_files.append(str(filepath))

    return downloaded_files


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
    Uses GreenVideo API client for video extraction and download.
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

        return not extract.is_telegram_link(url)

    async def execute(self, message: Message, reply: Message) -> None:
        """
        Download video from the URL in the message using GreenVideo.

        :param message: The original Telegram message containing a URL
        :param reply: The reply message object for status updates
        """
        url = extract.extract_url(message.text)
        download_dir = self._config_manager.get_config().TG_DOWNLOAD_PATH

        try:
            await self._safe_edit(reply, f"🔍 正在解析视频链接/图片...{url}")

            api_response = extract_video(url)

            if api_response.get("code") != 200:
                await self._safe_edit(reply, "❌ 无法解析链接或没有可下载的内容")
                logging.warning(f"Failed to extract video from URL: {url}, response: {api_response}")
                return

            result = _parse_response(api_response.get("data", {}))

            if not result or not result.get("downloads"):
                await self._safe_edit(reply, "❌ 无法解析链接或没有可下载的内容")
                logging.warning(f"Failed to parse video data from URL: {url}")
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

            start_time = time.time()

            async def progress_callback(
                current: int, total: int, file_info: dict
            ) -> None:
                await self._progress_callback(current, total, file_info, reply)

            downloaded_files = await download_video(
                result,
                download_dir,
                download_timeout=self._config_manager.get_config().TG_DL_TIMEOUT,
                progress_callback=progress_callback,
            )

            if downloaded_files:
                end_time = time.time()
                duration = end_time - start_time
                duration_str = format_duration(duration)
                finish_time = time.strftime("%H:%M", time.localtime())
                result_text = (
                    f"✅ 下载完成！\n"
                    f"完成时间: {finish_time}\n"
                    f"耗时: {duration_str}\n"
                    f"成功下载 {len(downloaded_files)} 个文件:\n"
                )
                for filepath in downloaded_files:
                    result_text += f"  • {filepath}\n"

                await self._safe_edit(reply, result_text.strip())
                logging.info(
                    f"Successfully downloaded {len(downloaded_files)} files from {url}"
                )
            else:
                await self._safe_edit(reply, "❌ 下载失败")
                logging.error(f"Failed to download video from {url}")

        except TimeoutError:
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
        from modules.helpers import safe_edit_message

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
