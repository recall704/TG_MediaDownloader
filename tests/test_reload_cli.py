"""
Tests for the --reload CLI argument parsing.
"""

import sys
from unittest.mock import patch

from tg_downloader import parse_args


class TestParseArgs:
    def test_reload_flag_defaults_to_false(self):
        with patch.object(sys, "argv", ["tg_downloader.py"]):
            args = parse_args()
            assert args.reload is False

    def test_reload_flag_true_when_passed(self):
        with patch.object(sys, "argv", ["tg_downloader.py", "--reload"]):
            args = parse_args()
            assert args.reload is True

    def test_help_does_not_raise(self, capsys):
        with patch.object(sys, "argv", ["tg_downloader.py", "--help"]):
            try:
                parse_args()
            except SystemExit as e:
                assert e.code == 0
        captured = capsys.readouterr()
        assert "--reload" in captured.out
        assert "auto-restart" in captured.out.lower()
