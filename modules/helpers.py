import asyncio
import logging
import os
import time
from pathlib import Path

from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import Message

from modules.models.ConfigFile import ConfigFile

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


def get_env(name: str, message: str, is_int: bool = False) -> int | str:
    """
    This function prompts the user to enter an information
    :param name: Corresponding environment variable name
    :param message: The message to shows to the user
    :param is_int: A control flag to cast the entered value as a integer
    :return: A string or integer
    """
    if name in os.environ:
        return os.environ[name]
    while True:
        try:
            user_value: str = input(message)
            if is_int:
                return int(user_value)
            return user_value
        except KeyboardInterrupt:
            print("\n")
            logging.info("Invoked interrupt during input request, closing process...")
            exit(-1)
        except ValueError as e:
            logging.error(e)
            time.sleep(1)


def get_config_from_user_or_env() -> ConfigFile:
    """
    This function check for env vars or ask the user to enter the needed information
    :return: A ConfigFile instance
    """
    logging.info("Retrieving configuration from user/env...")
    config: ConfigFile = ConfigFile()
    config.TG_SESSION = os.environ.get("TG_SESSION", "tg_downloader")
    config.TG_API_ID = get_env("TG_API_ID", "Enter your API ID: ", True)
    config.TG_API_HASH = get_env("TG_API_HASH", "Enter your API hash: ")
    config.TG_BOT_TOKEN = get_env("TG_BOT_TOKEN", "Enter your Telegram BOT token: ")
    config.TG_DOWNLOAD_PATH = get_env(
        "TG_DOWNLOAD_PATH", "Enter full path to downloads directory: "
    ).replace('"', "")
    config.TG_MAX_PARALLEL = int(os.environ.get("TG_MAX_PARALLEL", 4))
    config.TG_DL_TIMEOUT = int(os.environ.get("TG_DL_TIMEOUT", 5400))
    while True:
        authorized_users = get_env(
            "TG_AUTHORIZED_USER_ID",
            "Enter the list authorized users' id (separated by comma, can't be empty): ",
        )
        authorized_users = (
            [int(user_id) for user_id in authorized_users.split(",")]
            if authorized_users
            else []
        )
        if authorized_users:
            config.TG_AUTHORIZED_USER_ID = authorized_users
            break
    return config


def is_json(file: Path) -> bool:
    """
    This function check if the file extension is 'json'
    :param file: A Path to an existing file
    :return: True if the file's extension is json, False otherwise
    """
    return file.name.split(".")[-1] == "json"
