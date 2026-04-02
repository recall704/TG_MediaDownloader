"""
Tests for the PluginRouter.
"""

from unittest.mock import MagicMock

from modules.plugins.base import BasePlugin
from modules.plugins.router import PluginRouter


class TestPluginRouter:
    """Tests for the PluginRouter class."""

    def test_classify_media_message_returns_media_plugin(self):
        """Router classifies media message → returns MediaPlugin."""
        router = PluginRouter()
        media_plugin = _make_plugin("media", can_handle_result=True)
        router.register_plugin(media_plugin)

        message = MagicMock()
        message.media = "video"
        result = router.classify(message)
        assert result is not None
        assert result.name == "media"

    def test_classify_text_with_youtube_url_returns_greenvideo_plugin(self):
        """Router classifies text with YouTube URL → returns GreenVideoPlugin."""
        router = PluginRouter()
        media_plugin = _make_plugin("media", can_handle_result=False)
        greenvideo_plugin = _make_plugin("greenvideo", can_handle_result=True)
        router.register_plugin(media_plugin)
        router.register_plugin(greenvideo_plugin)

        message = MagicMock()
        message.media = None
        message.text = "https://youtube.com/watch?v=abc123"
        result = router.classify(message)
        assert result is not None
        assert result.name == "greenvideo"

    def test_classify_text_with_telegram_link_returns_telegram_post_plugin(self):
        """Router classifies text with Telegram link → returns TelegramPostVideoPlugin."""
        router = PluginRouter()
        media_plugin = _make_plugin("media", can_handle_result=False)
        greenvideo_plugin = _make_plugin("greenvideo", can_handle_result=False)
        telegram_plugin = _make_plugin("telegram_post_video", can_handle_result=True)
        router.register_plugin(media_plugin)
        router.register_plugin(greenvideo_plugin)
        router.register_plugin(telegram_plugin)

        message = MagicMock()
        message.media = None
        message.text = "https://t.me/somechannel/123"
        result = router.classify(message)
        assert result is not None
        assert result.name == "telegram_post_video"

    def test_classify_unsupported_message_returns_none(self):
        """Router returns None for unsupported message (e.g., plain text without URL)."""
        router = PluginRouter()
        media_plugin = _make_plugin("media", can_handle_result=False)
        greenvideo_plugin = _make_plugin("greenvideo", can_handle_result=False)
        telegram_plugin = _make_plugin("telegram_post_video", can_handle_result=False)
        router.register_plugin(media_plugin)
        router.register_plugin(greenvideo_plugin)
        router.register_plugin(telegram_plugin)

        message = MagicMock()
        message.media = None
        message.text = "Hello, this is plain text"
        result = router.classify(message)
        assert result is None

    def test_classify_empty_registry_returns_none(self):
        """Router returns None when no plugins are registered."""
        router = PluginRouter()
        message = MagicMock()
        result = router.classify(message)
        assert result is None

    def test_first_matching_plugin_wins(self):
        """When multiple plugins could match, the first registered one wins."""
        router = PluginRouter()
        plugin_a = _make_plugin("a", can_handle_result=True)
        plugin_b = _make_plugin("b", can_handle_result=True)
        router.register_plugin(plugin_a)
        router.register_plugin(plugin_b)

        message = MagicMock()
        result = router.classify(message)
        assert result is not None
        assert result.name == "a"


def _make_plugin(name: str, can_handle_result: bool) -> BasePlugin:
    """Helper to create a concrete plugin for testing."""

    class TestPlugin(BasePlugin):
        @property
        def name(self) -> str:
            return name

        def can_handle(self, message) -> bool:
            return can_handle_result

        async def execute(self, message, reply) -> None:
            pass

    return TestPlugin()
