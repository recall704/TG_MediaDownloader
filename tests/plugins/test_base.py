"""
Tests for the plugin base class and registry.
"""

import pytest
from unittest.mock import MagicMock

from modules.plugins.base import BasePlugin
from modules.plugins.registry import PluginRegistry


class TestBasePlugin:
    """Tests for the BasePlugin abstract base class."""

    def test_cannot_instantiate_base_plugin(self):
        """BasePlugin cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BasePlugin()

    def test_incomplete_implementation_raises_type_error(self):
        """A subclass that doesn't implement all abstract methods raises TypeError."""

        class IncompletePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "incomplete"

            def can_handle(self, message) -> bool:
                return True

            # Missing execute() implementation

        with pytest.raises(TypeError):
            IncompletePlugin()

    def test_complete_implementation_works(self):
        """A fully implemented subclass can be instantiated."""

        class CompletePlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "complete"

            def can_handle(self, message) -> bool:
                return True

            async def execute(self, message, reply) -> None:
                pass

        plugin = CompletePlugin()
        assert plugin.name == "complete"
        assert plugin.can_handle(MagicMock()) is True

    def test_cleanup_has_default_implementation(self):
        """The cleanup() method has a default no-op implementation."""

        class MinimalPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "minimal"

            def can_handle(self, message) -> bool:
                return False

            async def execute(self, message, reply) -> None:
                pass

        plugin = MinimalPlugin()
        # Should not raise
        import asyncio

        asyncio.get_event_loop().run_until_complete(plugin.cleanup())


class TestPluginRegistry:
    """Tests for the PluginRegistry class."""

    def test_register_plugin(self):
        """Plugins can be registered in the registry."""
        registry = PluginRegistry()
        plugin = self._make_plugin("test")
        registry.register(plugin)
        assert len(registry.get_all()) == 1

    def test_get_all_returns_plugins_in_order(self):
        """get_all() returns all registered plugins in registration order."""
        registry = PluginRegistry()
        plugin_a = self._make_plugin("a")
        plugin_b = self._make_plugin("b")
        registry.register(plugin_a)
        registry.register(plugin_b)
        plugins = registry.get_all()
        assert len(plugins) == 2
        assert plugins[0].name == "a"
        assert plugins[1].name == "b"

    def test_find_plugin_returns_first_match(self):
        """find_plugin() returns the first plugin whose can_handle() returns True."""
        registry = PluginRegistry()
        plugin_a = self._make_plugin("a", can_handle_result=False)
        plugin_b = self._make_plugin("b", can_handle_result=True)
        plugin_c = self._make_plugin("c", can_handle_result=True)
        registry.register(plugin_a)
        registry.register(plugin_b)
        registry.register(plugin_c)

        message = MagicMock()
        result = registry.find_plugin(message)
        assert result is not None
        assert result.name == "b"

    def test_find_plugin_returns_none_when_no_match(self):
        """find_plugin() returns None when no plugin matches."""
        registry = PluginRegistry()
        plugin = self._make_plugin("test", can_handle_result=False)
        registry.register(plugin)

        message = MagicMock()
        result = registry.find_plugin(message)
        assert result is None

    def test_find_plugin_empty_registry(self):
        """find_plugin() returns None when registry is empty."""
        registry = PluginRegistry()
        result = registry.find_plugin(MagicMock())
        assert result is None

    def test_multiple_plugins_all_false_returns_none(self):
        """find_plugin() returns None when all plugins return False."""
        registry = PluginRegistry()
        for i in range(3):
            registry.register(self._make_plugin(f"plugin_{i}", can_handle_result=False))

        result = registry.find_plugin(MagicMock())
        assert result is None

    @staticmethod
    def _make_plugin(name: str, can_handle_result: bool = True) -> BasePlugin:
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
