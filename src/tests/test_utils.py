from unittest.mock import patch

import pytest

from iwa.core.utils import get_safe_master_copy_address, singleton


def test_get_safe_master_copy_address_found():
    mock_master_copies = {
        "mainnet": [
            ("0xAddress1", "L2", "1.3.0"),
            ("0xAddress2", "L2", "1.4.1"),
        ]
    }

    with (
        patch("iwa.core.utils.MASTER_COPIES", mock_master_copies),
        patch("iwa.core.utils.EthereumNetwork") as mock_network,
    ):
        mock_network.MAINNET = "mainnet"

        address = get_safe_master_copy_address("1.4.1")
        assert address == "0xAddress2"


def test_get_safe_master_copy_address_not_found():
    mock_master_copies = {
        "mainnet": [
            ("0xAddress1", "L2", "1.3.0"),
        ]
    }

    with (
        patch("iwa.core.utils.MASTER_COPIES", mock_master_copies),
        patch("iwa.core.utils.EthereumNetwork") as mock_network,
    ):
        mock_network.MAINNET = "mainnet"

        with pytest.raises(ValueError, match="Did not find master copy"):
            get_safe_master_copy_address("1.0.0")


def test_singleton():
    @singleton
    class MyClass:
        def __init__(self, val):
            self.val = val

    obj1 = MyClass(1)
    obj2 = MyClass(2)

    assert obj1 is obj2
    assert obj1.val == 1
