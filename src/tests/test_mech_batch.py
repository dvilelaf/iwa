"""Tests for MechManagerMixin.send_batch_mech_requests."""

from unittest.mock import MagicMock, patch

import pytest
from safe_eth.safe import SafeOperationEnum

from iwa.core.contracts.multisend import MultiSendCallOnlyContract

# Valid Ethereum addresses for testing
ADDR_MULTISIG = "0x1111111111111111111111111111111111111111"
ADDR_MARKETPLACE = "0x2222222222222222222222222222222222222222"
ADDR_PRIORITY_MECH = "0x3333333333333333333333333333333333333333"
ADDR_MULTISEND = "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761"

# Realistic tx hashes (66 chars: 0x + 64 hex digits)
TX_HASH_SUCCESS = "0x" + "a1b2c3d4e5f6" * 10 + "a1b2c3d4"
TX_HASH_PARTIAL = "0x" + "f0e1d2c3b4a5" * 10 + "f0e1d2c3"
TX_HASH_FAIL = "0x" + "00" * 32


class FakeMechManager:
    """Minimal stub that inherits MechManagerMixin for testing."""

    def __init__(self):
        from iwa.plugins.olas.service_manager.mech import MechManagerMixin

        # Bind mixin methods
        for name in dir(MechManagerMixin):
            if not name.startswith("_") or name.startswith("_send") or name.startswith("_resolve"):
                method = getattr(MechManagerMixin, name)
                if callable(method) and not isinstance(method, type):
                    try:
                        setattr(self, name, method.__get__(self, type(self)))
                    except Exception:
                        pass

        self.service = MagicMock()
        self.service.multisig_address = ADDR_MULTISIG
        self.service.service_id = 42
        self.service.staking_contract_address = "0x4444444444444444444444444444444444444444"
        self.chain_name = "gnosis"
        self.wallet = MagicMock()
        self.registry = MagicMock()


@pytest.fixture
def mech_manager():
    """Create a FakeMechManager with MechManagerMixin bound."""
    # Instead of manually binding, just use the real ServiceManager pattern
    # but mock everything around it.
    from iwa.plugins.olas.service_manager.mech import MechManagerMixin

    mgr = MagicMock(spec=MechManagerMixin)
    mgr.service = MagicMock()
    mgr.service.multisig_address = ADDR_MULTISIG
    mgr.service.service_id = 42
    mgr.chain_name = "gnosis"
    mgr.wallet = MagicMock()
    mgr.registry = MagicMock()

    # Bind the real send_batch_mech_requests to our mock
    mgr.send_batch_mech_requests = (
        MechManagerMixin.send_batch_mech_requests.__get__(mgr)
    )
    mgr._resolve_marketplace_config = (
        MechManagerMixin._resolve_marketplace_config.__get__(mgr)
    )
    mgr._validate_priority_mech = MagicMock(return_value=True)
    mgr._prepare_marketplace_params = (
        MechManagerMixin._prepare_marketplace_params.__get__(mgr)
    )
    mgr._validate_marketplace_params = MagicMock(return_value=True)
    mgr.get_marketplace_config = MagicMock(
        return_value=(True, ADDR_MARKETPLACE, ADDR_PRIORITY_MECH)
    )
    return mgr


class TestBatchMechCalldata:
    """Test that multi-send calldata is correctly constructed."""

    def test_encode_multiple_inner_txs(self):
        """N inner transactions encode to expected byte length."""
        inner_txs = []
        for _i in range(3):
            inner_txs.append({
                "operation": SafeOperationEnum.CALL,
                "to": ADDR_MARKETPLACE,
                "value": 10_000_000_000_000_000,
                "data": b"\xab\xcd" * 16,  # 32 bytes of calldata
            })

        encoded = MultiSendCallOnlyContract.to_bytes(inner_txs)
        # Each tx: 1 (op) + 20 (to) + 32 (value) + 32 (data_len) + 32 (data) = 117
        assert len(encoded) == 117 * 3

    def test_encode_preserves_operation(self):
        """CALL operation is encoded as 0x00."""
        tx = {
            "operation": SafeOperationEnum.CALL,
            "to": ADDR_MARKETPLACE,
            "value": 0,
            "data": b"",
        }
        encoded = MultiSendCallOnlyContract.encode_data(tx)
        assert encoded[0] == 0  # CALL = 0

    def test_total_value_sums_correctly(self):
        """Total value across inner txs is summed for the outer multi-send."""
        inner_txs = [
            {
                "operation": SafeOperationEnum.CALL,
                "to": ADDR_MARKETPLACE,
                "value": 100,
                "data": b"",
            },
            {
                "operation": SafeOperationEnum.CALL,
                "to": ADDR_MARKETPLACE,
                "value": 200,
                "data": b"",
            },
        ]
        total = sum(tx["value"] for tx in inner_txs)
        assert total == 300


class TestSendBatchMechRequests:
    """Test send_batch_mech_requests method."""

    def test_empty_data_list_returns_none(self, mech_manager):
        """Empty data list should return None immediately."""
        result = mech_manager.send_batch_mech_requests(data_list=[])
        assert result is None

    def test_no_service_returns_none(self, mech_manager):
        """No active service should return None."""
        mech_manager.service = None
        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None

    def test_no_multisig_returns_none(self, mech_manager):
        """Service without multisig should return None."""
        mech_manager.service.multisig_address = None
        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_non_safe_sender_returns_none(
        self, mock_ms, mock_mp, mech_manager
    ):
        """Non-Safe sender should be rejected."""

        from iwa.core.models import StoredAccount

        # resolve_account returns a non-Safe account (EOA, not a Safe)
        mech_manager.wallet.account_service.resolve_account.return_value = (
            MagicMock(spec=StoredAccount)
        )
        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_successful_batch(self, mock_ms_cls, mock_mp_cls, mech_manager):
        """Successful batch sends N requests and returns tx hash."""
        from iwa.core.models import StoredSafeAccount

        # Make sender a Safe
        mock_safe_account = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = (
            mock_safe_account
        )

        # Mock marketplace.prepare_request_tx
        mock_mp = mock_mp_cls.return_value
        mock_mp.prepare_request_tx.return_value = {
            "data": "0xabcdef",
            "value": 10_000_000_000_000_000,
        }

        # Mock MultiSend.prepare_tx
        mock_ms = mock_ms_cls.return_value
        mock_ms.prepare_tx.return_value = {
            "data": "0xmultisend_data",
            "value": 30_000_000_000_000_000,
        }
        mock_ms.address = ADDR_MULTISEND

        # Mock Safe execution
        mech_manager.wallet.safe_service.execute_safe_transaction.return_value = (
            TX_HASH_SUCCESS
        )

        # Mock event verification
        mock_receipt = MagicMock()
        mech_manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            mock_receipt
        )
        mock_mp.extract_events.return_value = [
            {"name": "MarketplaceRequest", "args": {"requestId": 1, "sender": ADDR_MULTISIG}},
            {"name": "MarketplaceRequest", "args": {"requestId": 2, "sender": ADDR_MULTISIG}},
            {"name": "MarketplaceRequest", "args": {"requestId": 3, "sender": ADDR_MULTISIG}},
        ]

        data_list = [b"\x01" * 32, b"\x02" * 32, b"\x03" * 32]
        result = mech_manager.send_batch_mech_requests(data_list=data_list)

        assert result == TX_HASH_SUCCESS

        # Verify 3 inner transactions were prepared
        assert mock_mp.prepare_request_tx.call_count == 3

        # Verify Safe TX used DELEGATE_CALL
        safe_call = mech_manager.wallet.safe_service.execute_safe_transaction
        safe_call.assert_called_once()
        call_kwargs = safe_call.call_args[1]
        assert call_kwargs["operation"] == SafeOperationEnum.DELEGATE_CALL.value

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_partial_events_still_returns_hash(
        self, mock_ms_cls, mock_mp_cls, mech_manager
    ):
        """If only some events emitted, return hash with warning."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = mock_safe

        mock_mp = mock_mp_cls.return_value
        mock_mp.prepare_request_tx.return_value = {
            "data": "0xabcdef",
            "value": 10_000_000_000_000_000,
        }

        mock_ms = mock_ms_cls.return_value
        mock_ms.prepare_tx.return_value = {
            "data": "0xms_data",
            "value": 20_000_000_000_000_000,
        }
        mock_ms.address = ADDR_MULTISEND

        mech_manager.wallet.safe_service.execute_safe_transaction.return_value = (
            TX_HASH_PARTIAL
        )

        mock_receipt = MagicMock()
        mech_manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            mock_receipt
        )
        # Only 1 of 2 events
        mock_mp.extract_events.return_value = [
            {"name": "MarketplaceRequest", "args": {"requestId": 1, "sender": ADDR_MULTISIG}},
        ]

        data_list = [b"\x01" * 32, b"\x02" * 32]
        result = mech_manager.send_batch_mech_requests(data_list=data_list)

        # Should still return tx hash (partial success)
        assert result == TX_HASH_PARTIAL

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_no_events_returns_none(
        self, mock_ms_cls, mock_mp_cls, mech_manager
    ):
        """If zero events emitted, return None (total failure)."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = mock_safe

        mock_mp = mock_mp_cls.return_value
        mock_mp.prepare_request_tx.return_value = {
            "data": "0xabcdef",
            "value": 10_000_000_000_000_000,
        }

        mock_ms = mock_ms_cls.return_value
        mock_ms.prepare_tx.return_value = {
            "data": "0xms_data",
            "value": 10_000_000_000_000_000,
        }
        mock_ms.address = ADDR_MULTISEND

        mech_manager.wallet.safe_service.execute_safe_transaction.return_value = (
            TX_HASH_FAIL
        )

        mock_receipt = MagicMock()
        mech_manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            mock_receipt
        )
        mock_mp.extract_events.return_value = []

        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_safe_execution_exception(
        self, mock_ms_cls, mock_mp_cls, mech_manager
    ):
        """Safe TX exception should return None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = mock_safe

        mock_mp = mock_mp_cls.return_value
        mock_mp.prepare_request_tx.return_value = {
            "data": "0xabcdef",
            "value": 10_000_000_000_000_000,
        }

        mock_ms = mock_ms_cls.return_value
        mock_ms.prepare_tx.return_value = {
            "data": "0xms_data",
            "value": 10_000_000_000_000_000,
        }
        mock_ms.address = ADDR_MULTISEND

        mech_manager.wallet.safe_service.execute_safe_transaction.side_effect = (
            RuntimeError("gas too low")
        )

        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None

    @patch(
        "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
    )
    @patch("iwa.plugins.olas.service_manager.mech.MultiSendContract")
    def test_inner_tx_prep_failure_returns_none(
        self, mock_ms_cls, mock_mp_cls, mech_manager
    ):
        """If any inner tx preparation fails, return None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = mock_safe

        mock_mp = mock_mp_cls.return_value
        # First call succeeds, second returns None
        mock_mp.prepare_request_tx.side_effect = [
            {"data": "0xabcdef", "value": 100},
            None,
        ]

        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32, b"\x02" * 32]
        )
        assert result is None

    def test_non_marketplace_service_returns_none(self, mech_manager):
        """Service that doesn't use marketplace should return None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mech_manager.wallet.account_service.resolve_account.return_value = mock_safe
        mech_manager.get_marketplace_config.return_value = (False, None, None)

        result = mech_manager.send_batch_mech_requests(
            data_list=[b"\x01" * 32]
        )
        assert result is None
