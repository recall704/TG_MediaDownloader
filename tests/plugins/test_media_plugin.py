"""
Tests for the MediaPlugin.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from pyrogram.enums import MessageMediaType

from modules.plugins.media_plugin.media_plugin import MediaPlugin


class TestMediaPluginCanHandle:
    """Tests for MediaPlugin.can_handle()."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_config = MagicMock()
        mock_config_manager = MagicMock()
        mock_config_manager.get_config.return_value = mock_config
        self.plugin = MediaPlugin(
            config_manager=mock_config_manager,
            safe_edit=AsyncMock(),
        )

    def test_returns_true_for_video_message(self):
        """can_handle() returns True for video message."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        assert self.plugin.can_handle(message) is True

    def test_returns_true_for_document_message(self):
        """can_handle() returns True for document message."""
        message = MagicMock()
        message.media = MessageMediaType.DOCUMENT
        assert self.plugin.can_handle(message) is True

    def test_returns_true_for_audio_message(self):
        """can_handle() returns True for audio message."""
        message = MagicMock()
        message.media = MessageMediaType.AUDIO
        assert self.plugin.can_handle(message) is True

    def test_returns_true_for_animation_message(self):
        """can_handle() returns True for animation message."""
        message = MagicMock()
        message.media = MessageMediaType.ANIMATION
        assert self.plugin.can_handle(message) is True

    def test_returns_true_for_photo_message(self):
        """can_handle() returns True for photo message."""
        message = MagicMock()
        message.media = MessageMediaType.PHOTO
        assert self.plugin.can_handle(message) is True

    def test_returns_true_for_voice_message(self):
        """can_handle() returns True for voice message."""
        message = MagicMock()
        message.media = MessageMediaType.VOICE
        assert self.plugin.can_handle(message) is True

    def test_returns_false_for_sticker(self):
        """can_handle() returns False for sticker type."""
        message = MagicMock()
        message.media = MessageMediaType.STICKER
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_contact(self):
        """can_handle() returns False for contact type."""
        message = MagicMock()
        message.media = MessageMediaType.CONTACT
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_location(self):
        """can_handle() returns False for location type."""
        message = MagicMock()
        message.media = MessageMediaType.LOCATION
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_venue(self):
        """can_handle() returns False for venue type."""
        message = MagicMock()
        message.media = MessageMediaType.VENUE
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_poll(self):
        """can_handle() returns False for poll type."""
        message = MagicMock()
        message.media = MessageMediaType.POLL
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_web_page(self):
        """can_handle() returns False for web_page type."""
        message = MagicMock()
        message.media = MessageMediaType.WEB_PAGE
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_dice(self):
        """can_handle() returns False for dice type."""
        message = MagicMock()
        message.media = MessageMediaType.DICE
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_game(self):
        """can_handle() returns False for game type."""
        message = MagicMock()
        message.media = MessageMediaType.GAME
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_video_note(self):
        """can_handle() returns False for video_note type."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO_NOTE
        assert self.plugin.can_handle(message) is False

    def test_returns_false_for_none_media(self):
        """can_handle() returns False when media is None (text message)."""
        message = MagicMock()
        message.media = None
        assert self.plugin.can_handle(message) is False


class TestMediaPluginResolveFileName:
    """Tests for MediaPlugin._resolve_file_name()."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_config = MagicMock()
        mock_config_manager = MagicMock()
        mock_config_manager.get_config.return_value = mock_config
        self.plugin = MediaPlugin(
            config_manager=mock_config_manager,
            safe_edit=AsyncMock(),
        )

    def test_resolves_video_file_name(self):
        """Resolves file name from video with file_name."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = "test_video.mp4"
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"

        result = self.plugin._resolve_file_name(message)
        assert result == "test_video.mp4"

    def test_resolves_document_file_name(self):
        """Resolves file name from document with file_name."""
        message = MagicMock()
        message.media = MessageMediaType.DOCUMENT
        message.document.file_name = "test_document.pdf"
        message.document.file_unique_id = "doc123"
        message.document.mime_type = "application/pdf"

        result = self.plugin._resolve_file_name(message)
        assert result == "test_document.pdf"

    def test_resolves_photo_file_name_with_unique_id(self):
        """Resolves file name from photo using file_unique_id."""
        message = MagicMock()
        message.media = MessageMediaType.PHOTO
        message.photo.file_unique_id = "photo123"

        result = self.plugin._resolve_file_name(message)
        assert result == "photo123.jpg"

    def test_resolves_voice_file_name_with_unique_id(self):
        """Resolves file name from voice using file_unique_id."""
        message = MagicMock()
        message.media = MessageMediaType.VOICE
        message.voice.file_unique_id = "voice123"
        message.voice.mime_type = None

        result = self.plugin._resolve_file_name(message)
        assert result == "voice123.mp3"

    def test_resolves_video_without_file_name(self):
        """Resolves file name from video without file_name using unique_id."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = None
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"

        result = self.plugin._resolve_file_name(message)
        assert result == "abc123.mp4"

    def test_resolves_audio_file_name(self):
        """Resolves file name from audio with file_name."""
        message = MagicMock()
        message.media = MessageMediaType.AUDIO
        message.audio.file_name = "song.mp3"
        message.audio.file_unique_id = "audio123"
        message.audio.mime_type = "audio/mpeg"

        result = self.plugin._resolve_file_name(message)
        assert result == "song.mp3"

    def test_resolves_animation_file_name(self):
        """Resolves file name from animation with file_name."""
        message = MagicMock()
        message.media = MessageMediaType.ANIMATION
        message.animation.file_name = "gif.mp4"
        message.animation.file_unique_id = "anim123"
        message.animation.mime_type = "video/mp4"

        result = self.plugin._resolve_file_name(message)
        assert result == "gif.mp4"


class TestMediaPluginExecute:
    """Tests for MediaPlugin.execute()."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_config = MagicMock()
        mock_config.TG_DOWNLOAD_PATH = "/tmp/test_downloads"
        mock_config.TG_DL_TIMEOUT = 300
        mock_config_manager = MagicMock()
        mock_config_manager.get_config.return_value = mock_config
        self.safe_edit = AsyncMock()
        self.plugin = MediaPlugin(
            config_manager=mock_config_manager,
            safe_edit=self.safe_edit,
        )

    def test_download_success(self):
        """Happy path: download completes successfully."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = "test.mp4"
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"
        message.download = AsyncMock()

        reply = MagicMock()
        reply.text = "In queue"

        async def run_test():
            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.return_value = None
                await self.plugin.execute(message, reply)

            message.download.assert_called_once()
            assert self.safe_edit.call_count >= 2

        asyncio.get_event_loop().run_until_complete(run_test())

    def test_download_timeout(self):
        """Error path: download timeout produces error message."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = "test.mp4"
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"
        message.download = AsyncMock()

        reply = MagicMock()
        reply.text = "In queue"

        async def run_test():
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                await self.plugin.execute(message, reply)

            self.safe_edit.assert_any_call(
                reply, "**ERROR:** __Timeout reached downloading this file__"
            )

        asyncio.get_event_loop().run_until_complete(run_test())

    def test_download_cancelled(self):
        """Error path: cancelled download produces abort message."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = "test.mp4"
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"
        message.download = AsyncMock()

        reply = MagicMock()
        reply.text = "In queue"

        async def run_test():
            with patch("asyncio.wait_for", side_effect=asyncio.CancelledError()):
                with pytest.raises(asyncio.CancelledError):
                    await self.plugin.execute(message, reply)

            self.safe_edit.assert_any_call(reply, "Aborted")

        asyncio.get_event_loop().run_until_complete(run_test())

    def test_download_exception(self):
        """Error path: download exception produces error details."""
        message = MagicMock()
        message.media = MessageMediaType.VIDEO
        message.video.file_name = "test.mp4"
        message.video.file_unique_id = "abc123"
        message.video.mime_type = "video/mp4"
        message.download = AsyncMock()

        reply = MagicMock()
        reply.text = "In queue"

        async def run_test():
            with patch("asyncio.wait_for", side_effect=Exception("Test error")):
                await self.plugin.execute(message, reply)

            calls = [call[0] for call in self.safe_edit.call_args_list]
            error_call_found = any(
                "ERROR" in str(call) and "Test error" in str(call) for call in calls
            )
            assert error_call_found

        asyncio.get_event_loop().run_until_complete(run_test())
