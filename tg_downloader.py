import asyncio
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from asyncio import Task, Queue
from pathlib import Path

import pyroaddon
from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.types import (
    Message,
    Photo,
    Voice,
    Video,
    Animation,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Audio,
    Document,
)
from pyrogram.enums import ParseMode, MessageMediaType


# 全局消息编辑锁，防止 FloodWait
_message_edit_locks: dict[int, float] = {}
_MIN_EDIT_INTERVAL: float = 1.0  # 同一消息编辑最小间隔（秒）


async def safe_edit_message(
    message: Message,
    text: str,
    max_retries: int = 3,
) -> Message | None:
    """
    安全地编辑消息，带有 FloodWait 处理和重试机制

    Args:
        message: 要编辑的消息对象
        text: 新的文本内容
        max_retries: 最大重试次数

    Returns:
        编辑后的消息对象，失败返回 None
    """
    chat_id = message.chat.id
    msg_id = message.id
    current_time = time.time()

    # 检查是否需要等待（全局速率限制）
    if chat_id in _message_edit_locks:
        last_edit_time = _message_edit_locks[chat_id]
        wait_time = _MIN_EDIT_INTERVAL - (current_time - last_edit_time)
        if wait_time > 0:
            logging.info(
                f"Rate limiting: waiting {wait_time:.1f}s before editing message {msg_id}"
            )
            await asyncio.sleep(wait_time)

    for attempt in range(max_retries):
        try:
            # 更新最后编辑时间
            _message_edit_locks[chat_id] = time.time()
            result = await message.edit(text)
            return result
        except FloodWait as e:
            wait_seconds = e.value
            logging.warning(
                f"FloodWait detected for message {msg_id}, "
                f"waiting {wait_seconds}s (attempt {attempt + 1}/{max_retries})"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_seconds)
            else:
                logging.error(f"FloodWait: Max retries reached for message {msg_id}")
                return None
        except MessageNotModified:
            return None
        except Exception as e:
            logging.error(f"Error editing message {msg_id}: {e}")
            return None

    return None


from pyrogram.methods.utilities.idle import idle
from pyrogram.raw.functions.bots import SetBotCommands
from pyrogram.raw.types import BotCommand, BotCommandScopeDefault

from modules.ConfigManager import ConfigManager
from modules.helpers import get_config_from_user_or_env
from modules.models.ConfigFile import ConfigFile
from modules.utils import extract
from modules.tools.greenvideo.playwright_downloader import (
    PlaywrightGreenVideoDownloader,
)
from modules import forward_listener

GITHUB_LINK: str = "https://github.com/LightDestory/TG_MediaDownloader"
DONATION_LINK: str = "https://ko-fi.com/lightdestory"

config_manager: ConfigManager = ConfigManager(
    Path(os.environ.get("CONFIG_PATH", "./config.json"))
)
forward_listener.set_config_manager(config_manager)
queue: Queue = asyncio.Queue()
greenvideo_queue: Queue = asyncio.Queue()  # GreenVideo 下载专用队列
greenvideo_worker_task: Task | None = None
tasks: list[Task] = []
workers: list[Task] = []

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
    handlers=[
        logging.FileHandler("tg_downloader.log", mode="w+"),
        logging.StreamHandler(sys.stdout),
    ],
)


def init() -> Client | None:
    """
    This function initializes the Pyrogram client
    :return: A Pyrogram's client instance
    """
    config: ConfigFile
    if not config_manager.load_config_from_file():
        config = get_config_from_user_or_env()
        if config_manager.validate_config(config):
            config_manager.load_config(config)
            if not config_manager.save_config_to_file():
                exit(-1)
        else:
            exit(-1)
    else:
        config = config_manager.get_config()
    generate_workers(config.TG_MAX_PARALLEL)
    return Client(
        config.TG_SESSION,
        config.TG_API_ID,
        config.TG_API_HASH,
        bot_token=config.TG_BOT_TOKEN,
        parse_mode=ParseMode.DEFAULT,
    )


async def main() -> None:
    """
    Entrypoint of the bot runtime
    """
    try:
        logging.info("Bot is starting...")
        await app.start()
        logging.info("Settings Bot commands list...")
        await app.invoke(
            SetBotCommands(
                scope=BotCommandScopeDefault(),
                lang_code="",
                commands=get_command_list(),
            )
        )
        logging.info("Bot is running... =================================")
        await idle()
        logging.info("Bot is stopping...")
        await app.stop()
        logging.info("Bot stopped!")
    except Exception as ex:
        logging.error(f"Unable to start Pyrogram client, error:\n {ex}")
    finally:
        await abort(kill_workers=True)


def generate_workers(quantity: int) -> None:
    global greenvideo_worker_task
    loop = asyncio.get_event_loop_policy().get_event_loop()
    for i in range(quantity):
        workers.append(loop.create_task(worker()))
    # 启动 GreenVideo 专用 worker（串行处理）
    greenvideo_worker_task = loop.create_task(greenvideo_worker())


# GreenVideo 队列相关函数
async def enqueue_greenvideo_job(url: str, download_dir: str, message: Message) -> None:
    """
    将 GreenVideo 下载任务加入队列

    Args:
        url: 视频链接
        download_dir: 下载目录
        message: Telegram 消息对象，用于显示进度
    """
    # 获取队列大小（入队前的任务数）
    queue_size_before = greenvideo_queue.qsize()

    # 发送入队消息
    if queue_size_before == 0:
        reply = await message.reply_text("⏳ 正在等待下载...", quote=False)
    else:
        reply = await message.reply_text(
            f"⏳ 已加入下载队列，前面还有 {queue_size_before} 个任务", quote=False
        )

    # 入队（包含 reply 消息对象）
    await greenvideo_queue.put(
        {
            "url": url,
            "download_dir": download_dir,
            "message": message,
            "reply": reply,
            "enqueue_time": time.time(),
        }
    )

    logging.info(
        f"GreenVideo task enqueued: {url}, queue size: {queue_size_before + 1}"
    )


async def greenvideo_worker() -> None:
    """
    GreenVideo 专用 worker，串行处理下载任务
    """
    while True:
        job = None
        try:
            # 从队列获取任务
            job = await greenvideo_queue.get()

            url = job["url"]
            download_dir = job["download_dir"]
            message = job["message"]
            reply = job["reply"]

            logging.info(f"GreenVideo worker processing: {url}")

            # 调用原有的 download_greenvideo 函数
            await download_greenvideo(url, download_dir, message, reply)

        except asyncio.CancelledError:
            # 任务被取消时重新抛出，让协程正确退出
            raise
        except Exception as e:
            logging.error(f"Error in greenvideo_worker: {e}, {traceback.format_exc()}")
            # 任务失败时通知用户
            if reply:
                try:
                    await safe_edit_message(reply, f"下载失败: {str(e)}")
                except Exception:
                    pass
        finally:
            # 只有在成功获取到任务时才调用 task_done()
            if job is not None:
                greenvideo_queue.task_done()


async def download_greenvideo(
    url: str, download_dir: str, message: Message, reply: Message | None = None
) -> None:
    """
    使用 GreenVideo 下载视频

    Args:
        url: 视频链接
        download_dir: 下载目录
        message: Telegram 消息对象，用于显示进度
        reply: 可选的回复消息对象（队列模式下使用）
    """
    downloader = PlaywrightGreenVideoDownloader()

    try:
        # 发送初始消息（队列模式下使用已存在的 reply）
        if reply is None:
            reply = await message.reply_text(
                f"🔍 正在解析视频链接...{url}", quote=False
            )
        else:
            await safe_edit_message(reply, f"🔍 正在解析视频链接...{url}")

        # 提取视频信息
        result, headers = await downloader.extract_video_with_interception(
            url, headless=True
        )

        if not result or not result.get("downloads"):
            await safe_edit_message(reply, "❌ 无法解析视频链接或没有可下载的视频")
            logging.warning(f"Failed to extract video from URL: {url}")
            return

        # 显示视频信息
        title = result.get("title", "未知标题")
        platform = result.get("host_alias", result.get("host", "未知平台"))
        video_count = len(result["downloads"])

        await safe_edit_message(
            reply,
            f"✅ 找到视频！\n"
            f"标题: {title}\n"
            f"平台: {platform}\n"
            f"数量: {video_count} 个视频\n"
            f"开始下载...",
        )

        # 定义进度回调
        async def progress_callback(current: int, total: int, file_info: dict) -> None:
            await greenvideo_progress_callback(current, total, file_info, reply)

        # 下载视频
        downloaded_files = await downloader.download_video(
            result,
            download_dir,
            download_timeout=config_manager.get_config().TG_DL_TIMEOUT,
            progress_callback=progress_callback,
        )

        # 显示下载结果
        if downloaded_files:
            finish_time = time.strftime("%H:%M", time.localtime())
            result_text = (
                f"✅ 下载完成！\n"
                f"完成时间: {finish_time}\n"
                f"成功下载 {len(downloaded_files)} 个文件:\n"
            )
            for filepath in downloaded_files:
                result_text += f"  • {filepath}\n"

            await safe_edit_message(reply, result_text)
            logging.info(
                f"Successfully downloaded {len(downloaded_files)} files from {url}"
            )
        else:
            await safe_edit_message(reply, "❌ 下载失败")
            logging.error(f"Failed to download video from {url}")

    except asyncio.TimeoutError:
        await safe_edit_message(reply, "❌ 下载超时")
        logging.error(f"Timeout downloading video from {url}")
    except Exception as e:
        await safe_edit_message(reply, f"❌ 下载出错: {str(e)}")
        logging.error(
            f"Error downloading video from {url}: {e}, {traceback.format_exc()}"
        )


def get_command_list() -> list[BotCommand]:
    """
    This function returns the list of the implemented bot commands
    :return: A list of BotCommands
    """
    return [
        BotCommand(
            command="start",
            description="Initial command (invoked by Telegram) when you start the chat with "
            "the bot for the first time.",
        ),
        BotCommand(
            command="help", description="Gives you the available commands list."
        ),
        BotCommand(
            command="about", description="Gives you information about the project."
        ),
        BotCommand(command="abort", description="Cancel all the pending downloads."),
        BotCommand(
            command="status", description="Gives you the current configuration."
        ),
        BotCommand(command="usage", description="Gives you the usage instructions."),
        BotCommand(command="set_download_dir", description="Sets a new download dir"),
        BotCommand(
            command="set_max_parallel_dl",
            description="Sets the number of max parallel downloads",
        ),
        BotCommand(
            command="listen_forward",
            description="Start listening to a channel and forward messages to target",
        ),
        BotCommand(
            command="stop_listen",
            description="Stop listening to a channel",
        ),
        BotCommand(
            command="forward_status",
            description="Show active forward listeners",
        ),
    ]


def format_duration(seconds: float) -> str:
    """
    This function formats a duration in seconds to a human-readable format
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
    This function returns the most probable file extension based on the media type
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


async def abort(kill_workers: bool = False) -> None:
    """
    This function abort all the current tasks, and kills workers if needed
    :param kill_workers: A control flag to kill all the workers
    """
    global greenvideo_worker_task

    if tasks or not queue.empty():
        logging.info("Aborting all the pending jobs")
        for t in tasks:
            t.cancel()
        while not queue.empty():
            try:
                queue_item = queue.get_nowait()
                reply: Message = queue_item[1]
                await safe_edit_message(reply, "Aborted")
                queue.task_done()
            except asyncio.QueueEmpty:
                break

    # 取消 GreenVideo 队列中的任务
    logging.info("Aborting all the pending GreenVideo jobs")
    while not greenvideo_queue.empty():
        try:
            job = greenvideo_queue.get_nowait()
            reply: Message = job.get("reply")
            if reply:
                await safe_edit_message(reply, "Aborted")
            greenvideo_queue.task_done()
        except asyncio.QueueEmpty:
            break

    if kill_workers:
        logging.info("Killing all the workers")
        for w in workers:
            w.cancel()
        # 取消 GreenVideo worker
        if greenvideo_worker_task:
            greenvideo_worker_task.cancel()


# Enqueue a job
async def enqueue_job(message: Message, file_name: str) -> None:
    logging.info(f"Enqueueing media: {message.media} - {file_name}")
    reply = await message.reply_text("In queue", quote=True)
    queue.put_nowait([message, reply, file_name])


# Update download status
async def worker_progress(current, total, reply: list[Message]) -> None:
    status = int(current * 100 / total)
    message = reply[0]
    if status != 0 and status % 5 == 0 and str(status) not in message.text:
        result = await safe_edit_message(message, f"Downloading: {status}%")
        if result:
            reply[0] = result


# Parallel worker to download media files
async def worker() -> None:
    while True:
        queue_item = None
        try:
            # Get a "work item" out of the queue.
            queue_item = await queue.get()
            message: Message = queue_item[0]
            reply: Message = queue_item[1]
            file_name: str = queue_item[2]
            file_path = os.path.join(
                config_manager.get_config().TG_DOWNLOAD_PATH, file_name
            )
            try:
                start_time = time.time()
                logging.info(f"{file_name} - Download started")
                reply = await safe_edit_message(reply, "Downloading:  0%")
                task = asyncio.get_event_loop().create_task(
                    message.download(
                        file_path, progress=worker_progress, progress_args=([reply],)
                    )
                )
                tasks.append(task)
                await asyncio.wait_for(
                    task, timeout=config_manager.get_config().TG_DL_TIMEOUT
                )
                end_time = time.time()
                duration = end_time - start_time
                duration_str = format_duration(duration)
                logging.info(
                    f"{file_name} - Successfully downloaded (duration: {duration_str})"
                )
                # Use configured timezone for finish time display
                finish_time = time.strftime("%H:%M", time.localtime())
                await safe_edit_message(
                    reply, f"Finished at {finish_time}\nDuration: {duration_str}"
                )
            except MessageNotModified:
                pass
            except asyncio.CancelledError:
                logging.warning(f"{file_name} - Aborted")
                await safe_edit_message(reply, "Aborted")
            except asyncio.TimeoutError:
                logging.error(f"{file_name} - TIMEOUT ERROR")
                await safe_edit_message(
                    reply, "**ERROR:** __Timeout reached downloading this file__"
                )
            except Exception as e:
                logging.error(f"{file_name} - {str(e)}")
                await safe_edit_message(
                    reply,
                    f"**ERROR:** Exception {(e.__class__.__name__, str(e))} raised downloading this file: {file_name}",
                )
        except asyncio.CancelledError:
            raise
        finally:
            # Only call task_done() if we actually got a job from the queue
            if queue_item is not None:
                queue.task_done()


app = init()


# On_Message Decorators
@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("start")
)
async def start_command(_, message: Message) -> None:
    logging.info("Executing command /start")
    await message.reply(
        "**Greetings!** 👋\n"
        "You have successfully set up the bot.\n"
        + "I will download any supported media you send to me 😊\n\n"
        + "To get help press /help"
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("help")
)
async def help_command(_, message: Message) -> None:
    logging.info("Executing command /help")
    text: str = "**You can use the following commands:**\n\n"
    for command in get_command_list():
        text = text + f"/{command.command} -> __{command.description}__\n"
    await message.reply_text(text)


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("usage")
)
async def usage_command(_, message: Message) -> None:
    logging.info("Executing command /usage")
    await message.reply_text(
        "**Usage:**\n\n"
        "__Forward to the bot any message containing a supported media file, it will be downloaded on the selected "
        "folder.__\n\n"
        "**Make sure to have TGCRYPTO module installed to get faster downloads!**"
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("about")
)
async def about_command(_, message: Message) -> None:
    logging.info("Executing command /about")
    await message.reply_text(
        "This bot is free, but donations are accepted, and open source.\nIt is developed by "
        "@LightDestory",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("GitHub Repo", url=GITHUB_LINK),
                    InlineKeyboardButton("Make a Donation!", url=DONATION_LINK),
                ]
            ]
        ),
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("set_download_dir")
)
async def set_dl_path_command(_, message: Message) -> None:
    logging.info("Executing command /set_download_dir")
    await message.reply_text(
        "Do you want to change the current download directory?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Yes", callback_data="set_download_dir/yes"),
                    InlineKeyboardButton("No", callback_data="set_download_dir/no"),
                ]
            ]
        ),
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("set_max_parallel_dl")
)
async def set_max_parallel_dl_command(_, message: Message) -> None:
    logging.info("Executing command /set_max_parallel_dl")
    await message.reply_text(
        "To change the max parallel downloads all current tasks must be aborted, do you want to continue?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Yes", callback_data="set_max_parallel_dl/yes"
                    ),
                    InlineKeyboardButton("No", callback_data="set_max_parallel_dl/no"),
                ]
            ]
        ),
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("abort")
)
async def abort_command(_, message: Message) -> None:
    logging.info("Executing command /abort")
    await message.reply_text(
        "Do you want to abort all the pending jobs?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Yes", callback_data="abort/yes"),
                    InlineKeyboardButton("No", callback_data="abort/no"),
                ]
            ]
        ),
    )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("status")
)
async def status_command(_, message: Message) -> None:
    logging.info("Executing command /status")
    await message.reply_text(
        "**Current configuration:**\n\n"
        f"**Download Path:** __{config_manager.get_config().TG_DOWNLOAD_PATH}__\n"
        f"**Concurrent Downloads:** {config_manager.get_config().TG_MAX_PARALLEL}\n"
        f"**Allowed Users:** {config_manager.get_config().TG_AUTHORIZED_USER_ID}\n\n"
    )


async def greenvideo_progress_callback(
    current: int, total: int, file_info: dict, reply_message: Message
) -> None:
    """
    GreenVideo 下载进度回调函数

    Args:
        current: 当前已下载字节数
        total: 文件总字节数
        file_info: 文件信息字典
        reply_message: 用于更新进度的 Telegram 消息
    """
    if total > 0:
        progress = int(current * 100 / total)
        current_file = file_info.get("current_file", 1)
        total_files = file_info.get("total_files", 1)
        filename = file_info.get("filename", "unknown")

        # 获取上次更新时间，默认为 0
        last_update = file_info.get("last_update_time", 0)
        current_time = time.time()

        # 每 10 秒更新一次，或下载完成时强制更新
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
            except MessageNotModified:
                pass


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.text
)
async def text_message(_, message: Message) -> None:
    logging.info(f"Received text message: {message.text}")
    url = extract.extract_url(message.text)
    magnet = extract.extract_magnet(message.text)
    if url:
        if extract.is_telegram_link(url):
            await download_telegram_post_video(app, message, url)
        else:
            download_dir = config_manager.get_config().TG_DOWNLOAD_PATH
            await enqueue_greenvideo_job(url, download_dir, message)
    elif magnet:
        await message.reply_text(magnet, quote=False)
    else:
        await message.reply_text(message.text, quote=True)


async def download_telegram_post_video(
    app: Client, message: Message, link: str
) -> None:
    """
    下载 Telegram 公开频道帖子中的视频

    :param app: Pyrogram 客户端
    :param message: 用户发送的消息对象
    :param link: Telegram 帖子链接
    """
    from urllib.parse import urlparse
    from pyrogram.errors import MessageIdInvalid, ChannelInvalid, UsernameNotOccupied

    reply = await message.reply_text("🔍 正在解析帖子链接...", quote=True)

    try:
        parsed = urlparse(link)
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) < 2 or path_parts[0] == "c":
            await safe_edit_message(
                reply, "❌ 仅支持公开频道链接，私有频道链接无法访问"
            )
            return

        username = path_parts[0]
        message_id = int(path_parts[1])

        chat = await app.get_chat(username)
        logging.info(f"Resolved chat: {chat.title} (id={chat.id})")

        msg = await app.get_messages(chat.id, message_id)
        if not msg:
            await safe_edit_message(reply, "❌ 无法获取消息，链接可能无效")
            return

        if not msg.video:
            await safe_edit_message(reply, "❌ 该消息中没有视频")
            return

        video = msg.video
        file_name = video.file_name or f"{video.file_unique_id}.mp4"
        file_path = os.path.join(
            config_manager.get_config().TG_DOWNLOAD_PATH, file_name
        )

        await safe_edit_message(reply, f"📥 开始下载视频: {file_name}")

        start_time = time.time()
        await msg.download(file_name=file_path)
        end_time = time.time()
        duration = end_time - start_time
        duration_str = format_duration(duration)
        finish_time = time.strftime("%H:%M", time.localtime())

        await safe_edit_message(
            reply,
            f"✅ 下载完成！\n"
            f"文件: {file_name}\n"
            f"大小: {format_size(video.file_size)}\n"
            f"完成时间: {finish_time}\n"
            f"耗时: {duration_str}",
        )
        logging.info(f"Telegram post video downloaded: {file_name}")

    except (ValueError, IndexError):
        await safe_edit_message(
            reply, "❌ 链接格式不正确，请使用 https://t.me/username/post_id 格式"
        )
    except UsernameNotOccupied:
        await safe_edit_message(reply, "❌ 频道不存在或用户名无效")
    except ChannelInvalid:
        await safe_edit_message(reply, "❌ 无法访问该频道，可能已被解散或您无权访问")
    except MessageIdInvalid:
        await safe_edit_message(reply, "❌ 消息不存在或已被删除")
    except Exception as e:
        await safe_edit_message(reply, f"❌ 下载失败: {str(e)}")
        logging.error(
            f"Error downloading telegram post video: {e}, {traceback.format_exc()}"
        )


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小

    :param size_bytes: 文件大小（字节）
    :return: 格式化后的大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@app.on_message(
    filters.private
    & ~filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
)
async def no_auth_message(_, message: Message) -> None:
    logging.warning(f"Received message from unauthorized user ({message.from_user.id})")
    await message.reply_text("User is not allowed to use this bot!")


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.media
)
async def media_message(_, message: Message) -> None:
    unsupported_types = [
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
    if message.media in unsupported_types:
        logging.warning(f"Received invalid media: {message.id} - {message.media}")
        await message.reply_text("This media is not supported!", quote=True)
    else:
        r_text = "This file does not have a file name. Do you want to use a custom file name instead of file_id?"
        r_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Yes", callback_data="media_rename/yes"),
                    InlineKeyboardButton("No", callback_data="media_rename/no"),
                ]
            ]
        )
        if message.media in [MessageMediaType.PHOTO, MessageMediaType.VOICE]:
            await message.reply_text(r_text, quote=True, reply_markup=r_markup)
        elif message.media in [
            MessageMediaType.ANIMATION,
            MessageMediaType.AUDIO,
            MessageMediaType.VIDEO,
            MessageMediaType.DOCUMENT,
        ]:
            media: Video | Animation | Audio | Document = getattr(
                message, message.media.value
            )
            if not media.file_name:
                await message.reply_text(r_text, quote=True, reply_markup=r_markup)
            else:
                await enqueue_job(message, media.file_name)


# On Callback decorators
@app.on_callback_query(
    filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.regex(r"^abort/.+")
)
async def abort_callback(_, callback_query: CallbackQuery) -> None:
    answer: str = callback_query.data.split("/")[1]
    await callback_query.edit_message_reply_markup()
    if answer == "yes":
        reply: str = "There are not jobs pending!"
        if tasks:
            await abort()
            reply = "All pending jobs have been terminated."
        await safe_edit_message(callback_query.message, reply)
    else:
        await safe_edit_message(callback_query.message, "Operation cancelled")


@app.on_callback_query(
    filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.regex(r"^set_download_dir/.+")
)
async def set_dl_path_callback(client: Client, callback_query: CallbackQuery) -> None:
    message = callback_query.message
    answer: str = callback_query.data.split("/")[1]
    await callback_query.edit_message_reply_markup()
    if answer == "no":
        await safe_edit_message(callback_query.message, "Operation cancelled")
    else:
        await safe_edit_message(
            callback_query.message, "Enter the new download path in 60 seconds: "
        )
        try:
            response = await client.listen(message.chat.id, filters.text, timeout=60)
            reply_str: str
            if config_manager.change_download_path(response.text):
                reply_str = "The download dir has been changed successfully, new downloads will be redirected there"
            else:
                reply_str = "An error occurred while changing the download dir, please check logs!"
            await client.send_message(message.chat.id, text=reply_str)
        except asyncio.TimeoutError:
            await safe_edit_message(callback_query.message, "Operation cancelled")


@app.on_callback_query(
    filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.regex(r"^set_max_parallel_dl/.+")
)
async def set_max_parallel_dl_callback(
    client: Client, callback_query: CallbackQuery
) -> None:
    message = callback_query.message
    answer: str = callback_query.data.split("/")[1]
    await callback_query.edit_message_reply_markup()
    if answer == "no":
        await safe_edit_message(callback_query.message, "Operation cancelled")
    else:
        await safe_edit_message(
            callback_query.message,
            "Enter the new max parallel downloads in 30 seconds: ",
        )
        try:
            response = await client.listen(message.chat.id, filters.text, timeout=30)
            if config_manager.change_max_parallel_downloads(response.text):
                await abort(kill_workers=True)
                generate_workers(config_manager.get_config().TG_MAX_PARALLEL)
                reply_str = "The max parallel downloads has been changed successfully"
            else:
                reply_str = "An error occurred while changing the download dir, please check logs!"
            await client.send_message(message.chat.id, text=reply_str)
        except asyncio.TimeoutError:
            await safe_edit_message(callback_query.message, "Operation cancelled")


@app.on_callback_query(
    filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.regex(r"^media_rename/.+")
)
async def media_rename_callback(client: Client, callback_query: CallbackQuery) -> None:
    message = callback_query.message.reply_to_message
    if message:
        answer: str = callback_query.data.split("/")[1]
        media: Photo | Voice | Video | Animation | Audio | Document = getattr(
            message, message.media.value
        )
        ext: str = get_extension(message.media, media)
        if answer == "no":
            file_name = f"{media.file_unique_id}.{ext}"
            await callback_query.message.delete()
            await enqueue_job(message, file_name)
        else:
            await callback_query.edit_message_reply_markup()
            await safe_edit_message(
                callback_query.message,
                "Enter the name in 15 seconds or it will downloading using file_id.",
            )
            try:
                response = await client.listen(
                    message.chat.id, filters.text, timeout=15
                )
                file_name = f"{response.text}.{ext}"
                await callback_query.message.delete()
                await enqueue_job(message, file_name)
            except asyncio.TimeoutError:
                file_name = f"{media.file_unique_id}.{ext}"
                await callback_query.message.delete()
                await enqueue_job(message, file_name)
    else:
        await callback_query.edit_message_reply_markup()
        await safe_edit_message(
            callback_query.message,
            "The media's message is not available anymore (too long since input?",
        )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("listen_forward")
)
async def listen_forward_command(_, message: Message) -> None:
    logging.info("Executing command /listen_forward")
    args = message.text.split()
    if len(args) < 3:
        await message.reply_text(
            "**Usage:** `/listen_forward <source_link> <target_link>`\n\n"
            "Example: `/listen_forward https://t.me/source_channel https://t.me/target_channel`",
            quote=True,
        )
        return

    source_link = args[1]
    target_link = args[2]
    listen_key = f"{source_link} {target_link}"

    async def callback_wrapper(client, msg):
        await forward_listener.listen_forward(client, msg, app)

    success = await forward_listener.add_listen_chat(
        link=listen_key,
        listen_chat=forward_listener.listen_forward_chat,
        callback=callback_wrapper,
        user_client=app,
        bot_client=app,
    )

    if success:
        await message.reply_text(
            f"✅ 开始监听转发!\n\n源频道: {source_link}\n目标频道: {target_link}",
            quote=True,
        )
    else:
        await message.reply_text(
            f"❌ 该监听已存在，已被移除。请重新发送命令添加。",
            quote=True,
        )


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("stop_listen")
)
async def stop_listen_command(_, message: Message) -> None:
    logging.info("Executing command /stop_listen")
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text(
            "**Usage:** `/stop_listen <source_link>`\n\n"
            "Example: `/stop_listen https://t.me/source_channel`",
            quote=True,
        )
        return

    source_link = args[1]
    removed = []

    keys_to_remove = []
    for key in forward_listener.listen_forward_chat:
        if key.startswith(source_link):
            keys_to_remove.append(key)

    for key in keys_to_remove:
        await forward_listener.cancel_listen(
            link=key,
            listen_chat=forward_listener.listen_forward_chat,
            user_client=app,
        )
        removed.append(key)

    if removed:
        text = "✅ 已停止以下监听:\n\n" + "\n".join(f"• {k}" for k in removed)
    else:
        text = "❌ 未找到匹配的监听器"

    await message.reply_text(text, quote=True)


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
    & filters.command("forward_status")
)
async def forward_status_command(_, message: Message) -> None:
    logging.info("Executing command /forward_status")
    listeners = forward_listener.listen_forward_chat

    if not listeners:
        await message.reply_text("📭 当前没有活跃的监听器", quote=True)
        return

    text = "📡 活跃的监听器:\n\n"
    for key in listeners:
        source, target = key.split(" ", 1)
        text += f"• 源: {source}\n  目标: {target}\n\n"

    text += f"总计: {len(listeners)} 个监听器"
    await message.reply_text(text, quote=True)


app.run(main())
