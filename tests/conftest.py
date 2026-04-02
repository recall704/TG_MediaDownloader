"""
Pytest fixtures for TG Media Downloader tests.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.enums import MessageMediaType


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager with test configuration."""
    config_manager = MagicMock()
    config = MagicMock()
    config.TG_API_ID = 12345
    config.TG_API_HASH = "test_hash"
    config.TG_BOT_TOKEN = "test_token"
    config.TG_AUTHORIZED_USER_ID = [123456789]
    config.TG_DOWNLOAD_PATH = "/tmp/test_downloads"
    config.TG_SESSION = "test_session"
    config.TG_MAX_PARALLEL = 1
    config.TG_DL_TIMEOUT = 300
    config_manager.get_config.return_value = config
    config_manager.load_config_from_file.return_value = True
    config_manager.validate_config.return_value = True
    return config_manager


@pytest.fixture
def mock_client():
    """Create a mock Pyrogram Client."""
    client = AsyncMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.send_message = AsyncMock()
    client.get_chat = AsyncMock()
    client.get_messages = AsyncMock()
    client.listen = AsyncMock()
    return client


@pytest.fixture
def mock_message_video():
    """Create a mock Message with video media."""
    message = MagicMock()
    message.media = MessageMediaType.VIDEO
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 1
    message.text = None

    video = MagicMock()
    video.file_name = "test_video.mp4"
    video.file_unique_id = "abc123"
    video.mime_type = "video/mp4"
    video.file_size = 1024 * 1024 * 10  # 10MB
    video.duration = 120

    message.video = video
    message.photo = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.download = AsyncMock()
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_photo():
    """Create a mock Message with photo media."""
    message = MagicMock()
    message.media = MessageMediaType.PHOTO
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 2
    message.text = None

    photo = MagicMock()
    photo.file_unique_id = "photo123"
    photo.mime_type = None

    message.photo = photo
    message.video = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.download = AsyncMock()
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_document():
    """Create a mock Message with document media."""
    message = MagicMock()
    message.media = MessageMediaType.DOCUMENT
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 3
    message.text = None

    document = MagicMock()
    document.file_name = "test_document.pdf"
    document.file_unique_id = "doc123"
    document.mime_type = "application/pdf"
    document.file_size = 5 * 1024 * 1024  # 5MB

    message.document = document
    message.video = None
    message.photo = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.download = AsyncMock()
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_text_with_url():
    """Create a mock Message with text containing a URL."""
    message = MagicMock()
    message.media = None
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 4
    message.text = "Check out this video: https://youtube.com/watch?v=abc123"
    message.video = None
    message.photo = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_text_with_telegram_link():
    """Create a mock Message with text containing a Telegram link."""
    message = MagicMock()
    message.media = None
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 5
    message.text = "https://t.me/somechannel/123"
    message.video = None
    message.photo = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_text_plain():
    """Create a mock Message with plain text (no URL)."""
    message = MagicMock()
    message.media = None
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 6
    message.text = "Hello, this is plain text"
    message.video = None
    message.photo = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_message_sticker():
    """Create a mock Message with sticker media."""
    message = MagicMock()
    message.media = MessageMediaType.STICKER
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.id = 7
    message.text = None

    message.sticker = MagicMock()
    message.video = None
    message.photo = None
    message.document = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.reply_text = AsyncMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_reply_message():
    """Create a mock reply Message."""
    reply = MagicMock()
    reply.chat = MagicMock()
    reply.chat.id = 123456789
    reply.id = 100
    reply.text = "In queue"
    reply.edit = AsyncMock(return_value=reply)
    return reply


@pytest.fixture
def temp_download_dir():
    """Create a temporary download directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
