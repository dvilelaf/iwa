"""Tests for TransactionService and TransferLogger."""

from unittest.mock import MagicMock, patch

import pytest
from web3 import Web3
from web3 import exceptions as web3_exceptions

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.services.transaction import (
    TRANSFER_EVENT_TOPIC,
    TransactionService,
    TransferLogger,
)


@pytest.fixture
def mock_key_storage():
    """Mock key storage."""
    mock = MagicMock(spec=KeyStorage)

    # Mock sign_transaction
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"raw_tx_bytes"
    mock.sign_transaction.return_value = mock_signed_tx

    return mock


@pytest.fixture
def mock_account_service():
    """Mock account service."""
    mock = MagicMock()

    mock_account = MagicMock(spec=EncryptedAccount)
    mock_account.address = "0xSigner"
    mock_account.tag = "signer_tag"

    mock.resolve_account.return_value = mock_account
    return mock


@pytest.fixture
def mock_chain_interfaces():
    """Mock chain interfaces."""
    with patch("iwa.core.services.transaction.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis_interface = MagicMock()
        gnosis_interface.chain.chain_id = 100

        # Web3 mocks
        gnosis_interface.web3.eth.get_transaction_count.return_value = 5
        gnosis_interface.web3.eth.send_raw_transaction.return_value = b"tx_hash_bytes"

        # Receipt valid
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        gnosis_interface.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        instance.get.return_value = gnosis_interface

        # Mock with_retry to simulate retry behavior (up to 6 attempts)
        def mock_with_retry(op, max_retries=6, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return op()
                except Exception as e:
                    last_error = e
                    if attempt >= max_retries:
                        raise
            raise last_error

        gnosis_interface.with_retry.side_effect = mock_with_retry

        yield instance


@pytest.fixture
def mock_external_deps():
    """Mock logger, db, pricing."""
    with (
        patch("iwa.core.services.transaction.log_transaction") as mock_log,
        patch("iwa.core.pricing.PriceService") as mock_price,
    ):
        mock_price.return_value.get_token_price.return_value = 1.0  # 1 EUR per Token
        yield {
            "log": mock_log,
            "price": mock_price,
        }


def test_sign_and_send_success(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test successful sign and send flow."""
    service = TransactionService(mock_key_storage, mock_account_service)

    tx = {"to": "0xDest", "value": 100}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True
    assert receipt.status == 1

    # Check flow
    mock_account_service.resolve_account.assert_called_with("signer")
    mock_chain_interfaces.get.assert_called_with("gnosis")

    # Check nonce filling
    mock_chain_interfaces.get.return_value.web3.eth.get_transaction_count.assert_called()

    # Check signing
    mock_key_storage.sign_transaction.assert_called()

    # Check sending
    mock_chain_interfaces.get.return_value.web3.eth.send_raw_transaction.assert_called_with(
        b"raw_tx_bytes"
    )

    # Check logging
    mock_external_deps["log"].assert_called_once()
    call_args = mock_external_deps["log"].call_args[1]
    assert call_args["tx_hash"] == "74785f686173685f6279746573"  # hex of b'tx_hash_bytes'
    assert call_args["tags"] is None


def test_sign_and_send_low_gas_retry(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test retry logic on low gas error."""
    service = TransactionService(mock_key_storage, mock_account_service)

    web3_mock = mock_chain_interfaces.get.return_value.web3.eth

    # First attempt fails with "intrinsic gas too low", second succeeds
    web3_mock.send_raw_transaction.side_effect = [
        web3_exceptions.Web3RPCError("intrinsic gas too low"),
        b"tx_hash_bytes_success",
    ]

    tx = {"to": "0xDest", "value": 100, "gas": 20000}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True

    # Check retries
    assert web3_mock.send_raw_transaction.call_count == 2

    # Verify gas increase
    # Since 'tx' is mutated in place, both mock calls point to the same dict object which now has 30000
    # We can verify that sign_transaction was called twice, and the final gas is 30000
    assert mock_key_storage.sign_transaction.call_count == 2
    final_tx_arg = mock_key_storage.sign_transaction.call_args[0][0]
    assert final_tx_arg["gas"] == 30000


def test_sign_and_send_rpc_rotation(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test retry on generic error via with_retry.

    RPC rotation is now handled internally by with_retry, so we just verify
    that the operation retries and eventually succeeds.
    """
    service = TransactionService(mock_key_storage, mock_account_service)
    chain_interface = mock_chain_interfaces.get.return_value

    # Side effect: 1. Exception, 2. Success
    chain_interface.web3.eth.send_raw_transaction.side_effect = [
        Exception("Connection reset"),
        b"tx_hash_bytes",
    ]

    tx = {"to": "0xDest", "value": 100}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True
    # Verify retry happened - send_raw_transaction called twice
    assert chain_interface.web3.eth.send_raw_transaction.call_count == 2


# =============================================================================
# TransferLogger tests
# =============================================================================

# Real-world address for tests
_ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
_ADDR_LOWER = _ADDR.lower()
# 32-byte topic with address in last 20 bytes
_TOPIC_BYTES = b"\x00" * 12 + bytes.fromhex(_ADDR_LOWER[2:])
_TOPIC_HEX_STR = "0x" + "0" * 24 + _ADDR_LOWER[2:]


@pytest.fixture
def transfer_logger():
    """Create a TransferLogger with minimal mocks."""
    account_service = MagicMock()
    account_service.get_tag_by_address.return_value = None
    chain_interface = MagicMock()
    chain_interface.chain.native_currency = "xDAI"
    chain_interface.chain.get_token_name.return_value = None
    chain_interface.get_token_decimals.return_value = 18
    return TransferLogger(account_service, chain_interface)


class TestTopicToAddress:
    """Test TransferLogger._topic_to_address with all input types."""

    def test_bytes_topic(self, transfer_logger):
        """32 bytes → last 20 bytes extracted as address."""
        result = transfer_logger._topic_to_address(_TOPIC_BYTES)
        assert result == Web3.to_checksum_address(_ADDR_LOWER)

    def test_hex_string_topic(self, transfer_logger):
        """Hex string with 0x prefix → last 40 chars as address."""
        result = transfer_logger._topic_to_address(_TOPIC_HEX_STR)
        assert result == Web3.to_checksum_address(_ADDR_LOWER)

    def test_hex_string_no_prefix(self, transfer_logger):
        """Hex string without 0x prefix."""
        topic = "0" * 24 + _ADDR_LOWER[2:]
        result = transfer_logger._topic_to_address(topic)
        assert result == Web3.to_checksum_address(_ADDR_LOWER)

    def test_hexbytes_like_topic(self, transfer_logger):
        """Object with .hex() method (like HexBytes)."""

        class FakeHexBytes:
            def hex(self):
                return "0" * 24 + _ADDR_LOWER[2:]

        result = transfer_logger._topic_to_address(FakeHexBytes())
        assert result == Web3.to_checksum_address(_ADDR_LOWER)

    def test_unsupported_type_returns_empty(self, transfer_logger):
        """Non-bytes, non-str, no .hex() → empty string."""
        result = transfer_logger._topic_to_address(12345)
        assert result == ""


class TestProcessLog:
    """Test TransferLogger._process_log with realistic log structures."""

    def _make_transfer_log(self, from_addr, to_addr, amount_wei, token_addr="0xToken"):
        """Build a dict-style Transfer event log."""
        from_topic = "0x" + "0" * 24 + from_addr[2:].lower()
        to_topic = "0x" + "0" * 24 + to_addr[2:].lower()
        data = amount_wei.to_bytes(32, "big")
        return {
            "topics": [TRANSFER_EVENT_TOPIC, from_topic, to_topic],
            "data": data,
            "address": token_addr,
        }

    def test_parses_erc20_transfer(self, transfer_logger):
        """Valid Transfer log is parsed and logged."""
        log = self._make_transfer_log(
            "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            10**18,  # 1 token with 18 decimals
        )
        # Should not raise
        transfer_logger._process_log(log)

    def test_ignores_non_transfer_event(self, transfer_logger):
        """Log with non-Transfer topic is silently skipped."""
        log = {
            "topics": ["0xdeadbeef" + "0" * 56],
            "data": b"",
            "address": "0xToken",
        }
        # Should not raise or log anything
        transfer_logger._process_log(log)

    def test_ignores_log_with_no_topics(self, transfer_logger):
        """Log with empty topics is skipped."""
        transfer_logger._process_log({"topics": [], "data": b""})

    def test_ignores_log_with_insufficient_topics(self, transfer_logger):
        """Transfer event with < 3 topics (missing from/to) is skipped."""
        log = {
            "topics": [TRANSFER_EVENT_TOPIC, "0x" + "0" * 64],
            "data": b"",
            "address": "0xToken",
        }
        transfer_logger._process_log(log)

    def test_handles_bytes_topics(self, transfer_logger):
        """Log with bytes topics (not hex strings)."""
        from_bytes = b"\x00" * 12 + b"\xAA" * 20
        to_bytes = b"\x00" * 12 + b"\xBB" * 20
        event_topic = bytes.fromhex(TRANSFER_EVENT_TOPIC[2:])
        log = {
            "topics": [event_topic, from_bytes, to_bytes],
            "data": (100).to_bytes(32, "big"),
            "address": "0xTokenAddr",
        }
        transfer_logger._process_log(log)

    def test_handles_string_data(self, transfer_logger):
        """Log with hex-encoded data string instead of bytes."""
        log = self._make_transfer_log(
            "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            0,
        )
        log["data"] = "0x" + "0" * 64  # String instead of bytes
        transfer_logger._process_log(log)


class TestResolveLabels:
    """Test address/token label resolution fallbacks."""

    def test_address_label_known_wallet(self, transfer_logger):
        """Known wallet tag is preferred."""
        transfer_logger.account_service.get_tag_by_address.return_value = "my_safe"
        result = transfer_logger._resolve_address_label("0xABC")
        assert result == "my_safe"

    def test_address_label_known_token(self, transfer_logger):
        """Falls back to token contract name."""
        transfer_logger.account_service.get_tag_by_address.return_value = None
        transfer_logger.chain_interface.chain.get_token_name.return_value = "OLAS"
        result = transfer_logger._resolve_address_label("0xOLAS")
        assert result == "OLAS_contract"

    def test_address_label_abbreviated(self, transfer_logger):
        """Falls back to abbreviated address."""
        result = transfer_logger._resolve_address_label("0xABCDEF1234567890ABCDEF")
        assert result.startswith("0xABCD")
        assert result.endswith("CDEF")
        assert "..." in result

    def test_address_label_empty(self, transfer_logger):
        """Empty address returns 'unknown'."""
        assert transfer_logger._resolve_address_label("") == "unknown"

    def test_token_label_known(self, transfer_logger):
        """Known token returns its name."""
        transfer_logger.chain_interface.chain.get_token_name.return_value = "OLAS"
        assert transfer_logger._resolve_token_label("0xOLAS") == "OLAS"

    def test_token_label_unknown(self, transfer_logger):
        """Unknown token returns abbreviated address."""
        result = transfer_logger._resolve_token_label("0xABCDEF1234567890ABCDEF")
        assert "..." in result

    def test_token_label_empty(self, transfer_logger):
        """Empty address returns 'UNKNOWN'."""
        assert transfer_logger._resolve_token_label("") == "UNKNOWN"
