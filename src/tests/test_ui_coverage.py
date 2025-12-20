"""Unit tests for UI utilities to improve coverage."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.ui import display_mnemonic, prompt_and_store_mnemonic


def test_display_mnemonic():
    """Test display_mnemonic."""
    mnemonic = "one two three four five six seven eight nine ten eleven twelve"
    with patch("iwa.core.ui.Console") as mock_console:
        display_mnemonic(mnemonic)
        assert mock_console.called


def test_prompt_and_store_mnemonic_exists(tmp_path):
    """Test when file exists."""
    manager = MagicMock()
    out_file = str(tmp_path / "exists.json")
    with open(out_file, "w") as f:
        f.write("{}")

    assert prompt_and_store_mnemonic(manager, out_file=out_file) is None
    assert manager.generate_and_store_mnemonic.called is False


def test_prompt_and_store_mnemonic_success(tmp_path):
    """Test successful mnemonic storage."""
    manager = MagicMock()
    out_file = str(tmp_path / "new.json")

    with patch("getpass.getpass", side_effect=["pass", "pass"]):
        assert prompt_and_store_mnemonic(manager, out_file=out_file) is None
        manager.generate_and_store_mnemonic.assert_called_once_with("pass", out_file)


def test_prompt_and_store_mnemonic_mismatch(tmp_path):
    """Test password mismatch then success."""
    manager = MagicMock()
    out_file = str(tmp_path / "mismatch.json")

    with patch("getpass.getpass", side_effect=["p1", "p2", "pass", "pass"]):
        assert prompt_and_store_mnemonic(manager, out_file=out_file) is None
        manager.generate_and_store_mnemonic.assert_called_once_with("pass", out_file)


def test_prompt_and_store_mnemonic_empty(tmp_path):
    """Test empty password then success."""
    manager = MagicMock()
    out_file = str(tmp_path / "empty.json")

    with patch("getpass.getpass", side_effect=["", "pass", "pass"]):
        assert prompt_and_store_mnemonic(manager, out_file=out_file) is None
        manager.generate_and_store_mnemonic.assert_called_once_with("pass", out_file)


def test_prompt_and_store_mnemonic_exhausted(tmp_path):
    """Test exhaustion of attempts."""
    manager = MagicMock()
    out_file = str(tmp_path / "fail.json")

    with patch("getpass.getpass", side_effect=["p1", "p2", "p3", "p4", "p5", "p6"]):
        with pytest.raises(ValueError, match="Maximum password attempts exceeded"):
            prompt_and_store_mnemonic(manager, out_file=out_file)
