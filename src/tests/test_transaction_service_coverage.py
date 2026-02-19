"""Tests to improve coverage of iwa.core.services.transaction.

Targets the missing lines: 61, 75, 85, 100-102, 133-134, 170-175, 250-264,
287-288, 292-298, 304, 320, 345, 361-362, 373-374, 441-442, 449, 451, 454,
467-541.
"""

from unittest.mock import MagicMock, patch

import pytest
from web3 import exceptions as web3_exceptions

from iwa.core.keys import KeyStorage
from iwa.core.models import StoredSafeAccount
from iwa.core.services.transaction import (
    TRANSFER_EVENT_TOPIC,
    TransactionService,
    TransferLogger,
)

# Valid 42-char Ethereum addresses
ADDR_A = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
ADDR_B = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
ADDR_TOKEN = "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
ADDR_SAFE = "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
ADDR_SIGNER = "0xEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"


# =============================================================================
# Helpers
# =============================================================================

def _make_transfer_logger(
    get_tag_return=None,
    get_token_name_return=None,
    get_token_decimals_return=18,
    native_currency="xDAI",
):
    """Create a TransferLogger with configurable mocks."""
    account_service = MagicMock()
    account_service.get_tag_by_address.return_value = get_tag_return

    chain_interface = MagicMock()
    chain_interface.chain.native_currency = native_currency
    chain_interface.chain.get_token_name.return_value = get_token_name_return
    chain_interface.get_token_decimals.return_value = get_token_decimals_return
    return TransferLogger(account_service, chain_interface)


def _make_eoa_account(address=ADDR_SIGNER, tag="signer_tag"):
    """Create a mock EOA account (non-Safe)."""
    account = MagicMock()
    account.address = address
    account.tag = tag
    # Ensure it is NOT a StoredSafeAccount
    account.__class__ = type("EncryptedAccount", (), {})
    return account


def _make_safe_account(address=ADDR_SAFE, tag="my_safe"):
    """Create a mock StoredSafeAccount."""
    account = MagicMock(spec=StoredSafeAccount)
    account.address = address
    account.tag = tag
    return account


@pytest.fixture
def mock_chain_interfaces():
    """Mock ChainInterfaces for TransactionService tests."""
    with patch("iwa.core.services.transaction.ChainInterfaces") as mock:
        instance = mock.return_value
        chain_if = MagicMock()
        chain_if.chain.chain_id = 100
        chain_if.chain.native_currency = "xDAI"
        chain_if.chain.get_token_name.return_value = None
        chain_if.web3.eth.get_transaction_count.return_value = 5
        chain_if.web3.eth.send_raw_transaction.return_value = b"tx_hash_bytes"
        chain_if.get_suggested_fees.return_value = {"maxFeePerGas": 100}

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        mock_receipt.logs = []
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        instance.get.return_value = chain_if

        # Realistic with_retry: call op up to max_retries+1 times
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

        chain_if.with_retry.side_effect = mock_with_retry
        yield instance


@pytest.fixture
def mock_external_deps():
    """Mock log_transaction and PriceService."""
    with (
        patch("iwa.core.services.transaction.log_transaction") as mock_log,
        patch("iwa.core.pricing.PriceService") as mock_price,
    ):
        mock_price.return_value.get_token_price.return_value = 1.0
        yield {"log": mock_log, "price": mock_price}


# =============================================================================
# TransferLogger: log_transfers native path — lines 61, 75, 85
# =============================================================================


class TestLogTransfersNative:
    """Cover log_transfers: native transfer + log iteration."""

    def test_native_transfer_from_dict_tx(self):
        """Line 85: native transfer is logged when tx has value > 0 (dict-style tx)."""
        tl = _make_transfer_logger()
        mock_tx = {"from": ADDR_A, "to": ADDR_B, "value": 10**18}
        tl.chain_interface.web3.eth.get_transaction.return_value = mock_tx

        receipt = {"transactionHash": "0xabc", "logs": []}
        tl.log_transfers(receipt)

        # _log_native_transfer should have been called → logger.info
        # No exception means it ran through line 85

    def test_native_transfer_from_attributedict_fallback(self):
        """Line 61: from_addr fallback via tx['from'] when getattr returns empty.

        Simulates web3 AttributeDict where getattr(tx, 'from') returns ''
        but tx['from'] returns the actual address (because 'from' is a Python keyword).
        """

        class FakeAttributeDict:
            """Object where getattr('from') returns '' but __getitem__('from') works."""

            def __init__(self, data):
                self._data = data

            def __getattr__(self, name):
                # For 'from', return empty string (simulates the keyword issue)
                if name == "from":
                    return ""
                if name in self._data:
                    return self._data[name]
                raise AttributeError(name)

            def __getitem__(self, key):
                return self._data[key]

        fake_tx = FakeAttributeDict({"from": ADDR_A, "to": ADDR_B, "value": 10**18})

        tl = _make_transfer_logger()
        tl.chain_interface.web3.eth.get_transaction.return_value = fake_tx

        receipt = {"transactionHash": "0xabc", "logs": []}
        tl.log_transfers(receipt)

    def test_log_transfers_iterates_logs(self):
        """Line 75: each log in receipt.logs is processed via _process_log."""
        tl = _make_transfer_logger()
        # No tx hash → skip native check, but process logs
        log_entry = {
            "topics": ["0xdeadbeef" + "0" * 56],
            "data": b"",
            "address": ADDR_TOKEN,
        }
        receipt = {"logs": [log_entry, log_entry]}
        tl.log_transfers(receipt)

    def test_native_transfer_get_tx_exception(self):
        """Line 67: exception when getting tx is caught (debug log)."""
        tl = _make_transfer_logger()
        tl.chain_interface.web3.eth.get_transaction.side_effect = Exception("rpc fail")

        receipt = {"transactionHash": "0xabc", "logs": []}
        tl.log_transfers(receipt)

    def test_native_transfer_obj_style_tx(self):
        """Cover the non-dict branch for native value extraction."""
        tl = _make_transfer_logger()

        class FakeTx:
            value = 10**18
            to = ADDR_B

        # 'from' is a reserved keyword — use setattr
        fake_tx = FakeTx()
        setattr(fake_tx, "from", ADDR_A)
        tl.chain_interface.web3.eth.get_transaction.return_value = fake_tx

        receipt = {"transactionHash": "0xabc", "logs": []}
        tl.log_transfers(receipt)

    def test_receipt_with_attributedict_logs(self):
        """Cover receipt as dict subclass with attributes (like web3 AttributeDict)."""
        tl = _make_transfer_logger()

        class FakeReceipt(dict):
            """Dict subclass mimicking web3 AttributeDict."""
            def __init__(self):
                super().__init__(transactionHash=None, logs=[])
                self.transactionHash = None
                self.logs = []

        tl.log_transfers(FakeReceipt())


# =============================================================================
# TransferLogger._process_log: lines 100-102 (HexBytes-like topic with .hex())
# =============================================================================


class TestProcessLogHexBytesTopic:
    """Cover the hasattr(first_topic, 'hex') branch in _process_log."""

    def test_hexbytes_topic_with_0x_prefix(self):
        """Lines 100-102: topic.hex() returns with 0x prefix."""

        class HexBytesTopic:
            def hex(self):
                return TRANSFER_EVENT_TOPIC

        from_topic = "0x" + "0" * 24 + ADDR_A[2:].lower()
        to_topic = "0x" + "0" * 24 + ADDR_B[2:].lower()

        log = {
            "topics": [HexBytesTopic(), from_topic, to_topic],
            "data": (10**18).to_bytes(32, "big"),
            "address": ADDR_TOKEN,
        }
        tl = _make_transfer_logger()
        tl._process_log(log)

    def test_hexbytes_topic_without_0x_prefix(self):
        """Lines 101-102: topic.hex() returns without 0x prefix → prepend 0x."""

        class HexBytesTopic:
            def hex(self):
                return TRANSFER_EVENT_TOPIC[2:]  # No 0x prefix

        from_topic = "0x" + "0" * 24 + ADDR_A[2:].lower()
        to_topic = "0x" + "0" * 24 + ADDR_B[2:].lower()

        log = {
            "topics": [HexBytesTopic(), from_topic, to_topic],
            "data": (10**18).to_bytes(32, "big"),
            "address": ADDR_TOKEN,
        }
        tl = _make_transfer_logger()
        tl._process_log(log)


# =============================================================================
# TransferLogger._process_log: lines 133-134 (exception in parsing)
# =============================================================================


class TestProcessLogException:
    """Cover the exception handler in _process_log."""

    def test_malformed_data_triggers_except(self):
        """Lines 133-134: exception during parsing is caught and logged."""
        tl = _make_transfer_logger()
        # Valid Transfer topic, but data causes an error
        log = {
            "topics": [TRANSFER_EVENT_TOPIC, "not_valid_hex", "not_valid_hex"],
            "data": b"",
            "address": ADDR_TOKEN,
        }
        # _topic_to_address with "not_valid_hex" will attempt EthereumAddress("0x...")
        # which may or may not fail. Let's force an error by making data cause int overflow
        # Actually, let's patch _topic_to_address to raise
        with patch.object(tl, "_topic_to_address", side_effect=ValueError("bad topic")):
            tl._process_log(log)  # Should not raise


# =============================================================================
# TransferLogger._log_erc20_transfer: lines 170-175 (NFT transfer)
# =============================================================================


class TestNftTransfer:
    """Cover the NFT (ERC721) branch when decimals is None."""

    def test_nft_transfer_with_token_id(self):
        """Lines 170-172: NFT transfer with token_id > 0."""
        tl = _make_transfer_logger(get_token_decimals_return=None)
        tl._log_erc20_transfer(ADDR_TOKEN, ADDR_A, ADDR_B, 42)

    def test_nft_transfer_without_token_id(self):
        """Lines 174-175: NFT transfer with token_id == 0."""
        tl = _make_transfer_logger(get_token_decimals_return=None)
        tl._log_erc20_transfer(ADDR_TOKEN, ADDR_A, ADDR_B, 0)


# =============================================================================
# TransactionService._resolve_label: lines 250-264
# =============================================================================


class TestResolveLabel:
    """Cover the _resolve_label method of TransactionService."""

    def test_resolve_label_empty_address(self):
        """Line 251: empty address returns 'None'."""
        account_service = MagicMock()
        svc = TransactionService(MagicMock(), account_service)
        assert svc._resolve_label("") == "None"

    def test_resolve_label_known_tag(self):
        """Lines 253-255: known tag from account service."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = "my_wallet"
        svc = TransactionService(MagicMock(), account_service)
        assert svc._resolve_label(ADDR_A) == "my_wallet"

    def test_resolve_label_known_token(self):
        """Lines 258-261: fallback to token/contract name."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.services.transaction.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value.chain.get_token_name.return_value = "OLAS"
            svc = TransactionService(MagicMock(), account_service)
            assert svc._resolve_label(ADDR_A) == "OLAS"

    def test_resolve_label_chain_exception(self):
        """Lines 262-263: exception when getting token name → fallback to raw address."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.services.transaction.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.side_effect = Exception("no chain")
            svc = TransactionService(MagicMock(), account_service)
            assert svc._resolve_label(ADDR_A) == ADDR_A

    def test_resolve_label_no_token_name(self):
        """Line 264: no token name → return raw address."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.services.transaction.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value.chain.get_token_name.return_value = None
            svc = TransactionService(MagicMock(), account_service)
            assert svc._resolve_label(ADDR_A) == ADDR_A


# =============================================================================
# TransactionService.sign_and_send: signer not found — lines 287-288
# =============================================================================


class TestSignAndSendSignerNotFound:
    """Cover the case when resolve_account returns None."""

    def test_signer_not_found(self, mock_chain_interfaces):
        """Lines 287-288: resolve_account returns None → (False, {})."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = None

        svc = TransactionService(MagicMock(), account_service)
        success, receipt = svc.sign_and_send({"to": ADDR_B, "value": 0}, "ghost")

        assert success is False
        assert receipt == {}


# =============================================================================
# TransactionService.sign_and_send: Safe transaction path — lines 292-298
# =============================================================================


class TestSignAndSendSafePath:
    """Cover the Safe transaction routing in sign_and_send."""

    def test_safe_no_safe_service(self, mock_chain_interfaces):
        """Lines 292-294: Safe account but no safe_service → (False, {})."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = _make_safe_account()

        svc = TransactionService(MagicMock(), account_service, safe_service=None)
        success, receipt = svc.sign_and_send({"to": ADDR_B, "value": 0}, "my_safe")

        assert success is False
        assert receipt == {}

    def test_safe_prepare_fails(self, mock_chain_interfaces):
        """Lines 296-297: Safe account but _prepare_transaction fails → (False, {})."""
        account_service = MagicMock()
        safe_account = _make_safe_account()
        account_service.resolve_account.return_value = safe_account

        safe_service = MagicMock()
        svc = TransactionService(MagicMock(), account_service, safe_service=safe_service)

        # Make _prepare_transaction fail by making resolve_account return None
        # on second call (within _prepare_transaction)
        account_service.resolve_account.side_effect = [safe_account, None]

        tx = {"to": ADDR_B, "value": 0}  # no nonce → triggers resolve_account again
        success, receipt = svc.sign_and_send(tx, "my_safe")

        assert success is False
        assert receipt == {}

    def test_safe_transaction_success(self, mock_chain_interfaces, mock_external_deps):
        """Lines 296-298: Safe transaction fully succeeds through _execute_via_safe."""
        account_service = MagicMock()
        safe_account = _make_safe_account()
        account_service.resolve_account.return_value = safe_account
        account_service.get_tag_by_address.return_value = "my_safe"

        safe_service = MagicMock()
        safe_service.execute_safe_transaction.return_value = (
            "0xaabbccdd" + "0" * 56
        )

        chain_if = mock_chain_interfaces.get.return_value
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        mock_receipt.logs = []
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        svc = TransactionService(MagicMock(), account_service, safe_service=safe_service)
        tx = {"to": ADDR_B, "value": 100, "nonce": 5, "chainId": 100}

        success, receipt = svc.sign_and_send(tx, "my_safe")
        assert success is True


# =============================================================================
# TransactionService.sign_and_send: _prepare_transaction fail — line 304
# =============================================================================


class TestPrepareTransactionFail:
    """Cover _prepare_transaction returning False within EOA path."""

    def test_eoa_prepare_fails(self, mock_chain_interfaces):
        """Line 304: _prepare_transaction returns False for EOA → (False, {})."""
        account_service = MagicMock()
        eoa = _make_eoa_account()
        # First call for resolve returns eoa, second call (in _prepare_transaction) returns None
        account_service.resolve_account.side_effect = [eoa, None]

        svc = TransactionService(MagicMock(), account_service)
        tx = {"to": ADDR_B, "value": 0}  # no nonce → triggers resolve inside _prepare
        success, receipt = svc.sign_and_send(tx, "signer_tag")

        assert success is False
        assert receipt == {}


# =============================================================================
# sign_and_send: dict receipt with .get("status") — line 320
# =============================================================================


class TestDictReceipt:
    """Cover the dict receipt fallback for status check."""

    def test_dict_receipt_status(self, mock_chain_interfaces, mock_external_deps):
        """Line 320: receipt is a dict without .status attribute."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = _make_eoa_account()
        account_service.get_tag_by_address.return_value = "signer_tag"

        key_storage = MagicMock()
        key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

        chain_if = mock_chain_interfaces.get.return_value
        # Return a plain dict receipt (no .status attribute)
        dict_receipt = {"status": 1, "gasUsed": 21000, "effectiveGasPrice": 10, "logs": []}
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = dict_receipt

        svc = TransactionService(key_storage, account_service)
        tx = {"to": ADDR_B, "value": 100, "nonce": 5, "chainId": 100}

        success, receipt = svc.sign_and_send(tx, "signer_tag")
        assert success is True


# =============================================================================
# sign_and_send: with_retry returns (False, ...) — line 345
# =============================================================================


class TestWithRetryReturnsFalse:
    """Cover the path where with_retry returns but success is False."""

    def test_with_retry_false_result(self, mock_chain_interfaces):
        """Line 345: with_retry returns (False, ...) → return (False, {})."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = _make_eoa_account()

        key_storage = MagicMock()
        key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

        chain_if = mock_chain_interfaces.get.return_value
        # Override with_retry to return a False result directly
        chain_if.with_retry.side_effect = None
        chain_if.with_retry.return_value = (False, {}, b"")

        svc = TransactionService(key_storage, account_service)
        tx = {"to": ADDR_B, "value": 0, "nonce": 5, "chainId": 100}

        success, receipt = svc.sign_and_send(tx, "signer_tag")
        assert success is False
        assert receipt == {}


# =============================================================================
# _prepare_transaction: lines 361-362, 373-374
# =============================================================================


class TestPrepareTransaction:
    """Cover edge cases in _prepare_transaction."""

    def test_signer_not_found_in_prepare(self):
        """Lines 361-362: resolve_account returns None when setting nonce."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = None
        chain_if = MagicMock()

        svc = TransactionService(MagicMock(), account_service)
        tx = {"to": ADDR_B}  # No nonce
        result = svc._prepare_transaction(tx, "unknown_tag", chain_if)
        assert result is False

    def test_fee_autofill_exception(self):
        """Lines 373-374: get_suggested_fees raises → still returns True."""
        account_service = MagicMock()
        mock_acct = MagicMock()
        mock_acct.address = ADDR_SIGNER
        account_service.resolve_account.return_value = mock_acct

        chain_if = MagicMock()
        chain_if.chain.chain_id = 100
        chain_if.web3.eth.get_transaction_count.return_value = 0
        chain_if.get_suggested_fees.side_effect = Exception("fee estimation failed")

        svc = TransactionService(MagicMock(), account_service)
        tx = {"to": ADDR_B}  # No nonce, no gasPrice, no maxFeePerGas
        result = svc._prepare_transaction(tx, "signer_tag", chain_if)
        assert result is True
        # Verify nonce and chainId were still set
        assert tx["nonce"] == 0
        assert tx["chainId"] == 100


# =============================================================================
# _calculate_gas_cost: lines 441-442 (price exception)
# =============================================================================


class TestCalculateGasCost:
    """Cover the price service failure path in _calculate_gas_cost."""

    def test_price_service_exception(self):
        """Lines 441-442: PriceService raises → gas_value_eur is None."""
        account_service = MagicMock()
        svc = TransactionService(MagicMock(), account_service)

        receipt = MagicMock()
        receipt.gasUsed = 21000
        receipt.effectiveGasPrice = 10**9  # 1 gwei
        tx = {}

        with patch("iwa.core.pricing.PriceService") as mock_price:
            mock_price.side_effect = Exception("pricing unavailable")
            gas_cost, gas_value_eur = svc._calculate_gas_cost(receipt, tx, "gnosis")

        assert gas_cost == 21000 * 10**9
        assert gas_value_eur is None

    def test_gas_cost_zero(self):
        """Gas cost 0 → skip pricing entirely."""
        account_service = MagicMock()
        svc = TransactionService(MagicMock(), account_service)

        receipt = MagicMock()
        receipt.gasUsed = 0
        receipt.effectiveGasPrice = 0
        tx = {}

        gas_cost, gas_value_eur = svc._calculate_gas_cost(receipt, tx, "gnosis")
        assert gas_cost == 0
        assert gas_value_eur is None


# =============================================================================
# _determine_tags: lines 449, 451, 454
# =============================================================================


class TestDetermineTags:
    """Cover the _determine_tags method."""

    def test_data_is_bytes(self):
        """Line 449: tx data is bytes → converted to hex string."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"data": b"\x09\x5e\xa7\xb3" + b"\x00" * 28}  # approve selector
        tags = svc._determine_tags(tx, [])
        assert "approve" in tags

    def test_approve_selector_string_with_0x(self):
        """Line 451: data starts with '0x095ea7b3' → 'approve' tag added."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"data": "0x095ea7b3" + "0" * 56}
        tags = svc._determine_tags(tx, [])
        assert "approve" in tags

    def test_approve_selector_string_without_0x(self):
        """Line 450-451: data starts with '095ea7b3' → 'approve' tag added."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"data": "095ea7b3" + "0" * 56}
        tags = svc._determine_tags(tx, [])
        assert "approve" in tags

    def test_olas_in_to_address(self):
        """Line 453-454: 'olas' in tx to address → 'olas' tag added."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"to": "0xolas_contract", "data": ""}
        tags = svc._determine_tags(tx, [])
        assert "olas" in tags

    def test_no_special_tags(self):
        """No approve or olas → tags unchanged."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"to": ADDR_B, "data": "0xdeadbeef"}
        tags = svc._determine_tags(tx, ["existing"])
        assert tags == ["existing"]

    def test_tags_deduplicated(self):
        """Duplicate tags are removed via set."""
        svc = TransactionService(MagicMock(), MagicMock())
        tx = {"to": "0xolas_contract", "data": "0x095ea7b3" + "0" * 56}
        tags = svc._determine_tags(tx, ["olas", "approve"])
        assert len(tags) == len(set(tags))


# =============================================================================
# _execute_via_safe: lines 467-541
# =============================================================================


class TestExecuteViaSafe:
    """Cover the _execute_via_safe method directly."""

    def _make_service(self, account_service=None, safe_service=None):
        """Create a TransactionService with mocked dependencies."""
        as_ = account_service or MagicMock()
        ss = safe_service or MagicMock()
        return TransactionService(MagicMock(), as_, safe_service=ss)

    def test_success_path(self):
        """Lines 467-507: full success through _execute_via_safe."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = "my_safe"

        safe_service = MagicMock()
        tx_hash_str = "0x" + "ab" * 32
        safe_service.execute_safe_transaction.return_value = tx_hash_str

        chain_if = MagicMock()
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        mock_receipt.logs = []
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        svc = self._make_service(account_service, safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.services.transaction.log_transaction"):
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 100, "data": ""},
                safe_account,
                chain_if,
                "gnosis",
                ["tag1"],
            )

        assert success is True
        safe_service.execute_safe_transaction.assert_called_once()

    def test_success_with_bytes_data(self):
        """Line 476-477: tx data is bytes → converted to hex string."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None

        safe_service = MagicMock()
        tx_hash_str = "0x" + "ab" * 32
        safe_service.execute_safe_transaction.return_value = tx_hash_str

        chain_if = MagicMock()
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        mock_receipt.logs = []
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        svc = self._make_service(account_service, safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.services.transaction.log_transaction"):
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 0, "data": b"\xde\xad\xbe\xef"},
                safe_account,
                chain_if,
                "gnosis",
            )

        assert success is True
        call_kwargs = safe_service.execute_safe_transaction.call_args[1]
        assert call_kwargs["data"] == "0xdeadbeef"

    def test_reverted_status_0(self):
        """Lines 508-510: Safe tx mined but status=0 → (False, {})."""
        safe_service = MagicMock()
        tx_hash_str = "0x" + "ab" * 32
        safe_service.execute_safe_transaction.return_value = tx_hash_str

        chain_if = MagicMock()
        mock_receipt = MagicMock()
        mock_receipt.status = 0
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        svc = self._make_service(safe_service=safe_service)
        safe_account = _make_safe_account()

        success, receipt = svc._execute_via_safe(
            {"to": ADDR_B, "value": 0, "data": ""},
            safe_account,
            chain_if,
            "gnosis",
        )

        assert success is False
        assert receipt == {}

    def test_dict_receipt_status(self):
        """Lines 493-494: receipt is a dict without .status attr."""
        safe_service = MagicMock()
        tx_hash_str = "0x" + "ab" * 32
        safe_service.execute_safe_transaction.return_value = tx_hash_str

        chain_if = MagicMock()
        # Return a plain dict receipt
        dict_receipt = {"status": 1, "gasUsed": 21000, "effectiveGasPrice": 10, "logs": []}
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = dict_receipt

        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None

        svc = self._make_service(account_service, safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.services.transaction.log_transaction"):
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 0, "data": ""},
                safe_account,
                chain_if,
                "gnosis",
            )

        assert success is True

    def test_exception_without_hex_data(self):
        """Lines 512-539: execute_safe_transaction raises without hex data."""
        safe_service = MagicMock()
        safe_service.execute_safe_transaction.side_effect = Exception("network timeout")

        chain_if = MagicMock()
        svc = self._make_service(safe_service=safe_service)
        safe_account = _make_safe_account()

        success, receipt = svc._execute_via_safe(
            {"to": ADDR_B, "value": 0, "data": ""},
            safe_account,
            chain_if,
            "gnosis",
        )

        assert success is False
        assert receipt == {}

    def test_exception_with_hex_revert_data(self):
        """Lines 519-534: exception contains hex error data → decoded."""
        safe_service = MagicMock()
        # Include a hex pattern in the error message
        safe_service.execute_safe_transaction.side_effect = Exception(
            "execution reverted: 0x08c379a0"
            "0000000000000000000000000000000000000000000000000000000000000020"
            "0000000000000000000000000000000000000000000000000000000000000005"
            "6572726f72000000000000000000000000000000000000000000000000000000"
        )

        chain_if = MagicMock()
        svc = self._make_service(safe_service=safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.contracts.decoder.ErrorDecoder") as mock_decoder:
            mock_decoder.return_value.decode.return_value = [
                ("Error", "Insufficient balance", "ERC20")
            ]
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 0, "data": ""},
                safe_account,
                chain_if,
                "gnosis",
            )

        assert success is False
        assert receipt == {}

    def test_exception_with_hex_but_decoder_fails(self):
        """Lines 533-534: hex data found but ErrorDecoder raises."""
        safe_service = MagicMock()
        safe_service.execute_safe_transaction.side_effect = Exception(
            "reverted 0x08c379a0aabbccdd"
        )

        chain_if = MagicMock()
        svc = self._make_service(safe_service=safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.contracts.decoder.ErrorDecoder") as mock_decoder:
            mock_decoder.return_value.decode.side_effect = Exception("decode fail")
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 0, "data": ""},
                safe_account,
                chain_if,
                "gnosis",
            )

        assert success is False
        assert receipt == {}

    def test_exception_with_hex_decoder_returns_empty(self):
        """Lines 536-539: hex found, decoder returns empty list → fallback to generic log."""
        safe_service = MagicMock()
        safe_service.execute_safe_transaction.side_effect = Exception(
            "reverted 0x08c379a0aabbccdd"
        )

        chain_if = MagicMock()
        svc = self._make_service(safe_service=safe_service)
        safe_account = _make_safe_account()

        with patch("iwa.core.contracts.decoder.ErrorDecoder") as mock_decoder:
            mock_decoder.return_value.decode.return_value = []  # empty
            success, receipt = svc._execute_via_safe(
                {"to": ADDR_B, "value": 0, "data": ""},
                safe_account,
                chain_if,
                "gnosis",
            )

        assert success is False
        assert receipt == {}


# =============================================================================
# Additional edge cases for full coverage
# =============================================================================


class TestSignAndSendValueErrorNonRevert:
    """Cover the non-revert ValueError path in sign_and_send."""

    def test_value_error_non_revert(self, mock_chain_interfaces):
        """Line 350: ValueError without 'reverted' → still (False, {})."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = _make_eoa_account()

        key_storage = MagicMock()
        key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

        chain_if = mock_chain_interfaces.get.return_value
        # Override with_retry to raise a non-revert ValueError
        chain_if.with_retry.side_effect = ValueError("something else went wrong")

        svc = TransactionService(key_storage, account_service)
        tx = {"to": ADDR_B, "value": 0, "nonce": 5, "chainId": 100}

        success, receipt = svc.sign_and_send(tx, "signer_tag")
        assert success is False
        assert receipt == {}


class TestLogSuccessfulTransactionException:
    """Cover the exception handler in _log_successful_transaction."""

    def test_logging_exception_is_caught(self, mock_chain_interfaces):
        """Line 419: exception during logging doesn't propagate."""
        account_service = MagicMock()
        account_service.resolve_account.return_value = _make_eoa_account()
        account_service.get_tag_by_address.side_effect = Exception("db error")

        key_storage = MagicMock()
        key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

        chain_if = mock_chain_interfaces.get.return_value
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        mock_receipt.logs = []
        chain_if.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        svc = TransactionService(key_storage, account_service)
        tx = {"to": ADDR_B, "value": 100, "nonce": 5, "chainId": 100}

        # Should not raise despite logging failure
        success, receipt = svc.sign_and_send(tx, "signer_tag")
        assert success is True


class TestAddressLockMechanism:
    """Cover per-address lock creation and reuse."""

    def test_same_address_returns_same_lock(self):
        """Lines 242-246: same address returns same lock object."""
        lock1 = TransactionService._get_address_lock(ADDR_A)
        lock2 = TransactionService._get_address_lock(ADDR_A)
        assert lock1 is lock2

    def test_different_address_returns_different_lock(self):
        """Different addresses get different locks."""
        lock_a = TransactionService._get_address_lock(ADDR_A)
        lock_b = TransactionService._get_address_lock(ADDR_B)
        assert lock_a is not lock_b

    def test_case_insensitive(self):
        """Address comparison is case-insensitive."""
        lock1 = TransactionService._get_address_lock("0xAbCdEf")
        lock2 = TransactionService._get_address_lock("0xABCDEF")
        assert lock1 is lock2
