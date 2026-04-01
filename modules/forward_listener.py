import asyncio
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import pyrogram
from pyrogram import Client, filters
from pyrogram.errors import (
    PeerIdInvalid,
    ChatForwardsRestricted,
    ChatWriteForbidden,
    UsernameNotOccupied,
)
from pyrogram.types import Message
from pyrogram.enums import MessageMediaType

listen_forward_chat: dict[str, object] = {}
handle_media_groups: dict[int, set] = {}

_config_manager = None


def set_config_manager(config_manager) -> None:
    global _config_manager
    _config_manager = config_manager


def get_extension(
    media_type: MessageMediaType,
    media,
) -> str:
    if media_type == MessageMediaType.PHOTO:
        return "jpg"
    else:
        default = "unknown"
        if media_type in [MessageMediaType.VOICE, MessageMediaType.AUDIO]:
            default = "mp3"
        elif media_type in [MessageMediaType.ANIMATION, MessageMediaType.VIDEO]:
            default = "mp4"
        return default if not media.mime_type else media.mime_type.split("/")[1]


async def parse_link(client: Client, link: str) -> dict:
    """
    Parse a Telegram link to extract chat_id, topic_id, and message_id

    Supports formats:
    - https://t.me/c/1234567890/123
    - https://t.me/c/1234567890/123/456
    - https://t.me/username/123
    - https://t.me/username/123/456

    :param client: Pyrogram client instance
    :param link: Telegram message link
    :return: dict with chat_id, topic_id (optional), message_id (optional)
    """
    result = {}

    try:
        parsed = urlparse(link)
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) < 2:
            raise ValueError(f"Invalid link format: {link}")

        if path_parts[0] == "c":
            chat_id = int(f"-100{path_parts[1]}")
            result["chat_id"] = chat_id

            if len(path_parts) >= 3:
                result["message_id"] = int(path_parts[2])

            if len(path_parts) >= 4:
                result["topic_id"] = int(path_parts[3])
        else:
            username = path_parts[0]
            chat = await client.get_chat(username)
            result["chat_id"] = chat.id

            if len(path_parts) >= 2:
                result["message_id"] = int(path_parts[1])

            if len(path_parts) >= 3:
                result["topic_id"] = int(path_parts[2])

    except (ValueError, IndexError, PeerIdInvalid, UsernameNotOccupied) as e:
        logging.error(f"Failed to parse link {link}: {e}")
        raise

    return result


def check_type(message: Message) -> bool:
    for dtype, is_forward in _get_forward_type().items():
        if is_forward:
            result = getattr(message, dtype, None)
            if result:
                return True
    return False


def _get_forward_type() -> dict:
    global _config_manager
    if _config_manager:
        return _config_manager.get_config().FORWARD_TYPE
    return {
        "video": True,
        "photo": True,
        "audio": True,
        "voice": True,
        "animation": True,
        "document": True,
        "text": True,
        "video_note": True,
    }


def _get_download_upload() -> bool:
    global _config_manager
    if _config_manager:
        return _config_manager.get_config().DOWNLOAD_UPLOAD
    return True


def _get_upload_delete() -> bool:
    global _config_manager
    if _config_manager:
        return _config_manager.get_config().UPLOAD_DELETE
    return False


def _get_download_path() -> str:
    global _config_manager
    if _config_manager:
        return _config_manager.get_config().TG_DOWNLOAD_PATH
    return "./temp"


async def add_listen_chat(
    link: str,
    listen_chat: dict,
    callback: Callable,
    user_client: Client,
    bot_client: Client,
) -> bool:
    """
    Add a message listener for a specified channel

    :param link: Source channel link
    :param listen_chat: Dictionary storing listener configurations
    :param callback: Callback function for message handling
    :param user_client: User client (for listening)
    :param bot_client: Bot client (for fallback parsing)
    :return: True if listener added successfully
    """
    if link not in listen_chat:
        try:
            chat = await user_client.get_chat(link)
            if getattr(chat, "is_forum", False):
                raise PeerIdInvalid

            handler = pyrogram.handlers.MessageHandler(
                callback, filters=filters.chat(chat.id)
            )
            listen_chat[link] = handler
            user_client.add_handler(handler)
            return True

        except PeerIdInvalid:
            link_meta = link.split()
            meta = await parse_link(bot_client, link=link_meta[0])
            topic_id = meta.get("topic_id")
            chat_id = meta.get("chat_id")

            if topic_id:
                f = filters.chat(chat_id) & filters.topic(topic_id)
            else:
                f = filters.chat(chat_id)

            handler = pyrogram.handlers.MessageHandler(callback, filters=f)
            listen_chat[link] = handler
            user_client.add_handler(handler)
            return True
    else:
        await cancel_listen(link, listen_chat, user_client)
        return False


async def cancel_listen(
    link: str,
    listen_chat: dict,
    user_client: Client,
) -> None:
    """
    Cancel a listening session for a channel

    :param link: Channel link to stop listening
    :param listen_chat: Dictionary storing listener configurations
    :param user_client: User client
    """
    if link in listen_chat:
        handler = listen_chat.pop(link)
        try:
            user_client.remove_handler(handler)
            logging.info(f"Stopped listening to: {link}")
        except Exception as e:
            logging.error(f"Error removing handler for {link}: {e}")


async def listen_forward(
    client: pyrogram.Client,
    message: pyrogram.types.Message,
    app_client: pyrogram.Client = None,
) -> None:
    """
    Core message callback logic for forward listening

    :param client: User client that received the message
    :param message: Received message
    :param app_client: Bot client for operations
    """
    try:
        link = message.link
        meta = await parse_link(app_client, link=link)
        listen_chat_id = meta.get("chat_id")

        for m in listen_forward_chat:
            listen_link, target_link = m.split()
            _listen_meta = await parse_link(app_client, link=listen_link)
            _target_meta = await parse_link(app_client, link=target_link)
            _listen_chat_id = _listen_meta.get("chat_id")
            _target_chat_id = _target_meta.get("chat_id")

            if listen_chat_id == _listen_chat_id:
                try:
                    media_group_ids = await message.get_media_group()
                    if not media_group_ids:
                        raise ValueError

                    if not _get_forward_type().get(
                        "video"
                    ) or not _get_forward_type().get("photo"):
                        logging.warning(
                            "Filtered out photos/videos, not sending as media group"
                        )
                        raise ValueError

                    is_admin = getattr(message.chat, "is_creator", False) or getattr(
                        message.chat, "is_admin", False
                    )
                    is_self = getattr(message.from_user, "id", -1) == getattr(
                        client.me, "id", None
                    )

                    has_protected = (
                        getattr(message.chat, "has_protected_content", False)
                        or getattr(message.sender_chat, "has_protected_content", False)
                        or getattr(message, "has_protected_content", False)
                    )

                    if is_admin and is_self:
                        pass
                    elif has_protected:
                        raise ValueError

                    if listen_chat_id not in handle_media_groups:
                        handle_media_groups[listen_chat_id] = set()

                    if message.id not in handle_media_groups.get(listen_chat_id):
                        ids = set()
                        for peer_message in media_group_ids:
                            ids.add(peer_message.id)

                        if ids:
                            old_ids = handle_media_groups.get(listen_chat_id)
                            if old_ids:
                                old_ids.update(ids)
                            else:
                                handle_media_groups[listen_chat_id] = ids

                        await forward(
                            client=client,
                            message=message,
                            message_id=message.id,
                            origin_chat_id=_listen_chat_id,
                            target_chat_id=_target_chat_id,
                            target_link=target_link,
                            download_upload=False,
                            media_group=sorted(ids),
                            app_client=app_client,
                        )
                        break

                except ValueError:
                    pass

                await forward(
                    client=client,
                    message=message,
                    message_id=message.id,
                    origin_chat_id=_listen_chat_id,
                    target_chat_id=_target_chat_id,
                    target_link=target_link,
                    download_upload=True,
                    app_client=app_client,
                )

    except (ValueError, KeyError, UsernameNotOccupied, ChatWriteForbidden) as e:
        logging.error(f"Listen forward error: {e}")
    except Exception as e:
        logging.exception(f"Listen forward exception: {e}")


async def forward(
    client,
    message,
    message_id,
    origin_chat_id,
    target_chat_id,
    target_link,
    download_upload=False,
    media_group=None,
    done_notice=True,
    app_client=None,
):
    """
    Execute actual forwarding logic

    :param client: User client
    :param message: Original message
    :param message_id: Message ID to forward
    :param origin_chat_id: Source chat ID
    :param target_chat_id: Target chat ID
    :param target_link: Target channel link
    :param download_upload: Whether to download and re-upload
    :param media_group: Media group IDs if applicable
    :param done_notice: Whether to show completion notice
    :param app_client: Bot client
    """
    try:
        if not check_type(message):
            logging.info(f"Skipped message {message_id} (type filtered)")
            return

        if media_group:
            await app_client.copy_media_group(
                chat_id=target_chat_id,
                from_chat_id=origin_chat_id,
                message_id=message_id,
                disable_notification=True,
            )
        elif getattr(message, "text", False):
            await app_client.send_message(
                chat_id=target_chat_id,
                text=message.text,
                disable_notification=True,
                protect_content=False,
            )
        else:
            await app_client.copy_message(
                chat_id=target_chat_id,
                from_chat_id=origin_chat_id,
                message_id=message_id,
                disable_notification=True,
                protect_content=False,
            )

        logging.info(
            f"Forwarded successfully: {origin_chat_id}/{message_id} -> {target_chat_id}"
        )

    except (ChatForwardsRestricted, Exception) as e:
        if isinstance(e, ChatForwardsRestricted) or "forward" in str(e).lower():
            if not download_upload:
                is_admin = getattr(message.chat, "is_creator", False) or getattr(
                    message.chat, "is_admin", False
                )
                is_self = getattr(message.from_user, "id", -1) == getattr(
                    client.me, "id", None
                )
                if is_admin and is_self:
                    return
                raise

            if not _get_download_upload():
                logging.warning(
                    "Download-upload is disabled. Enable it to forward restricted content."
                )
                return

            await handle_download_upload(
                message=message,
                target_link=target_link,
                app_client=app_client,
            )
        else:
            raise


async def handle_download_upload(
    message: Message,
    target_link: str,
    app_client: Client,
) -> None:
    """
    Handle restricted content by downloading and re-uploading

    :param message: Original message
    :param target_link: Target channel link
    :param app_client: Bot client
    """
    try:
        download_dir = _get_download_path()
        media = message.media.value if message.media else None

        if not media:
            logging.warning("No media found in message for download-upload")
            return

        media_obj = getattr(message, media, None)
        if not media_obj:
            logging.warning("No media object found")
            return

        ext = get_extension(message.media, media_obj)
        file_name = f"{getattr(media_obj, 'file_unique_id', 'unknown')}.{ext}"
        file_path = os.path.join(download_dir, file_name)

        logging.info(f"Download-upload started for: {file_name}")

        await message.download(file_path)

        target_meta = await parse_link(app_client, link=target_link)
        target_chat_id = target_meta.get("chat_id")

        if message.media.value == "video":
            await app_client.send_video(
                chat_id=target_chat_id,
                video=file_path,
                disable_notification=True,
            )
        elif message.media.value == "photo":
            await app_client.send_photo(
                chat_id=target_chat_id,
                photo=file_path,
                disable_notification=True,
            )
        elif message.media.value == "document":
            await app_client.send_document(
                chat_id=target_chat_id,
                document=file_path,
                disable_notification=True,
            )
        elif message.media.value == "audio":
            await app_client.send_audio(
                chat_id=target_chat_id,
                audio=file_path,
                disable_notification=True,
            )
        elif message.media.value == "voice":
            await app_client.send_voice(
                chat_id=target_chat_id,
                voice=file_path,
                disable_notification=True,
            )
        elif message.media.value == "animation":
            await app_client.send_animation(
                chat_id=target_chat_id,
                animation=file_path,
                disable_notification=True,
            )
        else:
            await app_client.send_document(
                chat_id=target_chat_id,
                document=file_path,
                disable_notification=True,
            )

        logging.info(f"Download-upload completed: {file_name}")

        if _get_upload_delete() and os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Deleted uploaded file: {file_name}")

    except Exception as e:
        logging.error(f"Download-upload failed: {e}, {traceback.format_exc()}")
        raise
