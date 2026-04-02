import argparse
import asyncio
import logging
import os
import sys
import traceback
from asyncio import Task, Queue
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from pyrogram.enums import ParseMode
from pyrogram.methods.utilities.idle import idle
from pyrogram.raw.functions.bots import SetBotCommands
from pyrogram.raw.types import BotCommand, BotCommandScopeDefault

from modules.ConfigManager import ConfigManager
from modules.helpers import get_config_from_user_or_env, safe_edit_message
from modules.models.ConfigFile import ConfigFile
from modules import forward_listener
from modules.plugins.base import BasePlugin
from modules.plugins.registry import PluginRegistry
from modules.plugins.router import PluginRouter
from modules.plugins.media_plugin import MediaPlugin
from modules.plugins.greenvideo_plugin import GreenVideoPlugin
from modules.plugins.telegram_post_plugin import TelegramPostVideoPlugin
from modules.plugins.command_plugin.command_plugin import CommandPlugin

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
    command_plugin = CommandPlugin(
        config_manager=config_manager,
        safe_edit=safe_edit_message,
        abort_callback=abort,
        forward_listener_module=forward_listener,
    )

    plugin_registry.register(media_plugin)
    plugin_registry.register(telegram_post_plugin)
    plugin_registry.register(greenvideo_plugin)
    plugin_registry.register(command_plugin)

    plugin_router.register_plugin(command_plugin)
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


@app.on_message(
    filters.private
    & filters.user(users=config_manager.get_config().TG_AUTHORIZED_USER_ID)
)
async def handle_message(client: Client, message: Message) -> None:
    """
    Main message handler that routes incoming messages to the appropriate plugin.
    """
    logging.info(f"Received message from authorized user: {message.from_user.id}")

    plugin = plugin_router.classify(message)
    if plugin:
        logging.info(f"Message routed to plugin: {plugin.name}")
        reply = await message.reply_text(f"Queueing with {plugin.name}...", quote=True)
        await enqueue_job(message, reply, plugin)
    else:
        logging.warning(f"No plugin matched message: {message.media or message.text}")
        await message.reply_text("Unsupported message type.", quote=True)


def get_command_list() -> list[BotCommand]:
    """
    Return the list of implemented bot commands.
    :return: A list of BotCommands
    """
    return [
        BotCommand(
            command="start",
            description="Initial command when you start the chat with the bot for the first time.",
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
            target="tg_downloader.run_bot",
            target_type="function",
            watch_filter=PythonFilter(),
            recursive=True,
        )
    else:
        run_bot()
