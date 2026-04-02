import argparse
import asyncio
import logging
import os
import sys
import time
import traceback
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

from pyrogram.methods.utilities.idle import idle
from pyrogram.raw.functions.bots import SetBotCommands
from pyrogram.raw.types import BotCommand, BotCommandScopeDefault

from modules.ConfigManager import ConfigManager
from modules.helpers import get_config_from_user_or_env
from modules.models.ConfigFile import ConfigFile
from modules.utils import extract
from modules import forward_listener
from modules.plugins.base import BasePlugin
from modules.plugins.registry import PluginRegistry
from modules.plugins.router import PluginRouter
from modules.plugins.media_plugin import MediaPlugin
from modules.plugins.greenvideo_plugin import GreenVideoPlugin
from modules.plugins.telegram_post_plugin import TelegramPostVideoPlugin

GITHUB_LINK: str = "https://github.com/LightDestory/TG_MediaDownloader"
DONATION_LINK: str = "https://ko-fi.com/lightdestory"

config_manager: ConfigManager = ConfigManager(
    Path(os.environ.get("CONFIG_PATH", "./config.json"))
)
forward_listener.set_config_manager(config_manager)

queue: Queue = asyncio.Queue(maxsize=1)
tasks: list[Task] = []
workers: list[Task] = []

plugin_registry: PluginRegistry = PluginRegistry()
plugin_router: PluginRouter = PluginRouter()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
    handlers=[
        logging.FileHandler("tg_downloader.log", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)

_message_edit_locks: dict[int, float] = {}
_MIN_EDIT_INTERVAL: float = 1.0


async def safe_edit_message(
    message: Message,
    text: str,
    max_retries: int = 3,
) -> Message | None:
    """
    Safely edit a message with FloodWait handling and retry mechanism.

    Args:
        message: The message to edit
        text: New text content
        max_retries: Maximum retry attempts

    Returns:
        The edited message, or None on failure
    """
    chat_id = message.chat.id
    msg_id = message.id
    current_time = time.time()

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


def init() -> Client | None:
    """
    Initialize the Pyrogram client and wire up the plugin system.
    :return: A Pyrogram client instance
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

    client = Client(
        config.TG_SESSION,
        config.TG_API_ID,
        config.TG_API_HASH,
        bot_token=config.TG_BOT_TOKEN,
        parse_mode=ParseMode.DEFAULT,
    )

    media_plugin = MediaPlugin(
        config_manager=config_manager,
        safe_edit=safe_edit_message,
    )
    greenvideo_plugin = GreenVideoPlugin(
        config_manager=config_manager,
        safe_edit=safe_edit_message,
    )
    telegram_post_plugin = TelegramPostVideoPlugin(
        config_manager=config_manager,
        client=client,
        safe_edit=safe_edit_message,
    )

    plugin_registry.register(media_plugin)
    plugin_registry.register(telegram_post_plugin)
    plugin_registry.register(greenvideo_plugin)

    plugin_router.register_plugin(media_plugin)
    plugin_router.register_plugin(telegram_post_plugin)
    plugin_router.register_plugin(greenvideo_plugin)

    generate_workers()

    return client


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
        for plugin in plugin_registry.get_all():
            await plugin.cleanup()


def generate_workers() -> None:
    """
    Create a single worker task for the global queue.
    Queue size is 1, so only one worker is needed.
    """
    loop = asyncio.get_event_loop_policy().get_event_loop()
    workers.append(loop.create_task(worker()))


async def enqueue_job(message: Message, reply: Message, plugin: BasePlugin) -> None:
    """
    Enqueue a download job with the matched plugin.

    :param message: The original incoming message
    :param reply: The reply message object for status updates
    :param plugin: The plugin instance that will handle this job
    """
    logging.info(f"Enqueueing job for plugin: {plugin.name}")
    await queue.put({"message": message, "reply": reply, "plugin": plugin})


async def worker() -> None:
    """
    Single worker loop that processes jobs from the global queue.
    Each job is executed by its associated plugin with timeout handling.
    """
    while True:
        job = None
        try:
            job = await queue.get()

            message: Message = job["message"]
            reply: Message = job["reply"]
            plugin: BasePlugin = job["plugin"]

            logging.info(f"Worker processing job with plugin: {plugin.name}")

            task = asyncio.get_event_loop().create_task(plugin.execute(message, reply))
            tasks.append(task)

            await asyncio.wait_for(
                task, timeout=config_manager.get_config().TG_DL_TIMEOUT
            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"Error in worker: {e}, {traceback.format_exc()}")
            if job and job.get("reply"):
                try:
                    await safe_edit_message(job["reply"], f"下载失败: {str(e)}")
                except Exception:
                    pass
        finally:
            if job is not None:
                queue.task_done()


async def abort(kill_workers: bool = False) -> None:
    """
    Abort all pending jobs and optionally kill workers.

    :param kill_workers: If True, cancel all worker tasks
    """
    if tasks or not queue.empty():
        logging.info("Aborting all the pending jobs")
        for t in tasks:
            t.cancel()
        while not queue.empty():
            try:
                job = queue.get_nowait()
                reply: Message = job.get("reply")
                if reply:
                    await safe_edit_message(reply, "Aborted")
                queue.task_done()
            except asyncio.QueueEmpty:
                break

    if kill_workers:
        logging.info("Killing all the workers")
        for w in workers:
            w.cancel()


app = init()


def run_bot() -> None:
    """
    Start the bot's event loop.
    Called directly or via watchfiles.run_process() when --reload is enabled.
    """
    app.run(main())


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    :return: Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(description="TG Media Downloader Bot")
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-restart on file changes (development mode)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.reload:
        try:
            from watchfiles import run_process, PythonFilter
        except ImportError:
            logging.error(
                "watchfiles is not installed. Install it with: uv sync --group dev"
            )
            sys.exit(1)

        project_root = Path(__file__).resolve().parent
        logging.info("Starting in reload mode, watching for file changes...")
        run_process(
            project_root,
            target="tg_downloader:run_bot",
            watch_filter=PythonFilter(),
            recursive=True,
        )
    else:
        run_bot()
