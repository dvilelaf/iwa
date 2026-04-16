"""Tests for KeyStorage.export_addresses."""

from unittest.mock import MagicMock

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.models import StoredSafeAccount


def _make_key_storage(accounts: dict) -> KeyStorage:
    ks = MagicMock(spec=KeyStorage)
    ks.accounts = accounts
    ks.export_addresses = KeyStorage.export_addresses.__get__(ks)
    return ks


def test_export_empty():
    ks = _make_key_storage({})
    assert ks.export_addresses() == []


def test_export_eoa_and_safe():
    eoa = MagicMock(spec=EncryptedAccount)
    eoa.tag = "master"
    eoa.address = "0x" + "aa" * 20

    safe = MagicMock(spec=StoredSafeAccount)
    safe.tag = "agent_multisig"
    safe.address = "0x" + "bb" * 20

    ks = _make_key_storage({"0xaa": eoa, "0xbb": safe})
    rows = ks.export_addresses()

    assert len(rows) == 2
    # Sorted by tag: agent_multisig before master
    assert rows[0] == {
        "tag": "agent_multisig",
        "address": "0x" + "bb" * 20,
        "type": "Safe",
    }
    assert rows[1] == {
        "tag": "master",
        "address": "0x" + "aa" * 20,
        "type": "EOA",
    }


def test_export_sorted_by_tag():
    accounts = {}
    for tag in ["zebra", "alpha", "mech"]:
        acc = MagicMock(spec=EncryptedAccount)
        acc.tag = tag
        acc.address = f"0x{tag}"
        accounts[tag] = acc

    ks = _make_key_storage(accounts)
    rows = ks.export_addresses()
    tags = [r["tag"] for r in rows]
    assert tags == ["alpha", "mech", "zebra"]


def test_export_no_private_keys():
    eoa = MagicMock(spec=EncryptedAccount)
    eoa.tag = "master"
    eoa.address = "0x" + "cc" * 20

    ks = _make_key_storage({"0xcc": eoa})
    rows = ks.export_addresses()

    # Only tag, address, type — no ciphertext, no kdf_salt, no private key
    assert set(rows[0].keys()) == {"tag", "address", "type"}
