"""Tests for MechManagerMixin to cover missing lines in mech.py.

Covers: get_marketplace_config, auto-detect marketplace flow,
_send_legacy_mech_request edge cases, _validate_priority_mech exception paths,
_validate_marketplace_params edge cases, _resolve_marketplace_config,
_send_marketplace_mech_request dispatch, _send_v1_marketplace_request,
_execute_mech_tx edge cases.
"""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.constants import ZERO_ADDRESS
from iwa.plugins.olas.constants import PAYMENT_TYPE_NATIVE
from iwa.plugins.olas.models import OlasConfig, Service
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.service_manager.mech import DEFAULT_PRIORITY_MECH

# Valid Ethereum addresses for testing
ADDR_MULTISIG = "0x0000000000000000000000000000000000000002"
ADDR_STAKING = "0x0000000000000000000000000000000000000099"
ADDR_PRIORITY_MECH = "0x0000000000000000000000000000000000000001"
ADDR_MARKETPLACE_V2 = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
ADDR_MARKETPLACE_V1 = "0x4554fE75c1f5576c1d7F765B2A036c199Adae329"
ADDR_UNKNOWN_MARKETPLACE = "0x0000000000000000000000000000000000000077"
ADDR_FACTORY = "0x0000000000000000000000000000000000000088"


@pytest.fixture
def mock_wallet():
    """Mock wallet fixture."""
    wallet = MagicMock()
    wallet.safe_service = MagicMock()
    wallet.safe_service.execute_safe_transaction.return_value = "0xMockTxHash"
    wallet.account_service = MagicMock()
    wallet.sign_and_send_transaction = MagicMock()
    return wallet


@pytest.fixture
def mock_service():
    """Mock Service model."""
    service = MagicMock(spec=Service)
    service.service_id = 42
    service.chain_name = "gnosis"
    service.multisig_address = ADDR_MULTISIG
    service.staking_contract_address = ADDR_STAKING
    return service


@pytest.fixture
def mock_olas_config(mock_service):
    """Mock OlasConfig."""
    config = MagicMock(spec=OlasConfig)
    config.get_service.return_value = mock_service
    return config


@pytest.fixture
def manager(mock_wallet, mock_olas_config, mock_service):
    """Create ServiceManager with mocks, bypassing full init."""
    with patch("iwa.plugins.olas.service_manager.Config") as mock_config_class:
        mock_config = mock_config_class.return_value
        mock_config.plugins = {"olas": mock_olas_config}

        sm = ServiceManager(mock_wallet, service_key="gnosis:42")
        sm.olas_config = mock_olas_config
        sm.service = mock_service
        sm.registry = MagicMock()
        sm.registry.chain_interface = MagicMock()
        sm.registry.chain_interface.web3 = MagicMock()
        sm.chain_interface = MagicMock()
        sm.chain_interface.chain.name = "gnosis"
        sm.chain_name = "gnosis"
        return sm


# ──────────────────────────────────────────────────────────────────
# Tests for get_marketplace_config (lines 113-155)
# ──────────────────────────────────────────────────────────────────


class TestGetMarketplaceConfig:
    """Tests for get_marketplace_config covering lines 113-155."""

    def test_no_service_returns_false(self, manager):
        """Line 115-116: no service returns (False, None, None)."""
        manager.service = None
        result = manager.get_marketplace_config()
        assert result == (False, None, None)

    def test_no_staking_contract_returns_false(self, manager):
        """Line 115-116: service without staking_contract_address."""
        manager.service.staking_contract_address = None
        result = manager.get_marketplace_config()
        assert result == (False, None, None)

    def test_marketplace_known_address(self, manager):
        """Lines 118-149: marketplace detected with known address in DEFAULT_PRIORITY_MECH."""
        mock_checker = MagicMock()
        mock_checker.mech_marketplace = ADDR_MARKETPLACE_V2

        mock_staking = MagicMock()
        mock_staking.activity_checker = mock_checker

        with patch(
            "iwa.plugins.olas.contracts.staking.StakingContract",
            return_value=mock_staking,
        ):
            result = manager.get_marketplace_config()

        use_mp, mp_addr, priority = result
        assert use_mp is True
        assert str(mp_addr) == ADDR_MARKETPLACE_V2
        # Priority mech should be from DEFAULT_PRIORITY_MECH
        expected_priority = DEFAULT_PRIORITY_MECH[ADDR_MARKETPLACE_V2][0]
        assert priority == expected_priority

    def test_marketplace_unknown_address_fallback(self, manager):
        """Lines 136-143: marketplace not in DEFAULT_PRIORITY_MECH, uses fallback."""
        mock_checker = MagicMock()
        mock_checker.mech_marketplace = ADDR_UNKNOWN_MARKETPLACE

        mock_staking = MagicMock()
        mock_staking.activity_checker = mock_checker

        with patch(
            "iwa.plugins.olas.contracts.staking.StakingContract",
            return_value=mock_staking,
        ):
            result = manager.get_marketplace_config()

        use_mp, mp_addr, priority = result
        assert use_mp is True
        assert str(mp_addr) == ADDR_UNKNOWN_MARKETPLACE
        # Falls back to OLAS_CONTRACTS constant
        from iwa.plugins.olas.constants import OLAS_CONTRACTS

        expected = OLAS_CONTRACTS.get("gnosis", {}).get("OLAS_MECH_MARKETPLACE_PRIORITY")
        assert priority == expected

    def test_marketplace_zero_address(self, manager):
        """Line 129/151: mech_marketplace is zero address -> (False, None, None)."""
        mock_checker = MagicMock()
        mock_checker.mech_marketplace = str(ZERO_ADDRESS)

        mock_staking = MagicMock()
        mock_staking.activity_checker = mock_checker

        with patch(
            "iwa.plugins.olas.contracts.staking.StakingContract",
            return_value=mock_staking,
        ):
            result = manager.get_marketplace_config()

        assert result == (False, None, None)

    def test_marketplace_none_attribute(self, manager):
        """Line 129: mech_marketplace is None (falsy) -> (False, None, None)."""
        mock_checker = MagicMock()
        mock_checker.mech_marketplace = None

        mock_staking = MagicMock()
        mock_staking.activity_checker = mock_checker

        with patch(
            "iwa.plugins.olas.contracts.staking.StakingContract",
            return_value=mock_staking,
        ):
            result = manager.get_marketplace_config()

        assert result == (False, None, None)

    def test_exception_returns_false(self, manager):
        """Lines 153-155: exception in get_marketplace_config returns (False, None, None)."""
        with patch(
            "iwa.plugins.olas.contracts.staking.StakingContract",
            side_effect=Exception("RPC error"),
        ):
            result = manager.get_marketplace_config()

        assert result == (False, None, None)


# ──────────────────────────────────────────────────────────────────
# Tests for send_mech_request auto-detect (lines 203-208)
# ──────────────────────────────────────────────────────────────────


class TestSendMechRequestAutoDetect:
    """Tests for auto-detect marketplace flow in send_mech_request."""

    def test_auto_detect_marketplace_true(self, manager, mock_wallet):
        """Lines 203-208: use_marketplace=None triggers auto-detect, marketplace found."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe

        with (
            patch.object(
                manager,
                "get_marketplace_config",
                return_value=(True, ADDR_MARKETPLACE_V2, ADDR_PRIORITY_MECH),
            ),
            patch.object(manager, "_send_marketplace_mech_request", return_value="0xABC") as mock_mp,
        ):
            result = manager.send_mech_request(data=b"test", use_marketplace=None)

        assert result == "0xABC"
        mock_mp.assert_called_once()
        # Verify detected_marketplace was passed
        call_kwargs = mock_mp.call_args[1]
        assert call_kwargs["marketplace_address"] == ADDR_MARKETPLACE_V2
        assert call_kwargs["priority_mech"] == ADDR_PRIORITY_MECH

    def test_auto_detect_marketplace_false(self, manager, mock_wallet):
        """Lines 203-208: auto-detect returns False, falls through to legacy."""
        with (
            patch.object(
                manager,
                "get_marketplace_config",
                return_value=(False, None, None),
            ),
            patch.object(manager, "_send_legacy_mech_request", return_value="0xDEF") as mock_leg,
        ):
            result = manager.send_mech_request(data=b"test", use_marketplace=None)

        assert result == "0xDEF"
        mock_leg.assert_called_once()

    def test_no_service_returns_none(self, manager):
        """Lines 190-191: no service -> None."""
        manager.service = None
        result = manager.send_mech_request(data=b"test")
        assert result is None

    def test_no_multisig_returns_none(self, manager):
        """Lines 197-198: no multisig address -> None."""
        manager.service.multisig_address = None
        result = manager.send_mech_request(data=b"test")
        assert result is None


# ──────────────────────────────────────────────────────────────────
# Tests for _send_legacy_mech_request edge cases (lines 248-249)
# ──────────────────────────────────────────────────────────────────


class TestSendLegacyMechRequest:
    """Tests for _send_legacy_mech_request edge cases."""

    def test_no_mech_address_for_chain(self, manager):
        """Lines 248-249: mech address not found for chain."""
        manager.chain_name = "unknown_chain"
        result = manager._send_legacy_mech_request(data=b"test")
        assert result is None

    def test_no_service_returns_none(self, manager):
        """Lines 240-241: no service -> None."""
        manager.service = None
        result = manager._send_legacy_mech_request(data=b"test")
        assert result is None

    def test_successful_legacy_request(self, manager, mock_wallet):
        """Lines 251-268: full successful legacy mech request."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe

        with patch(
            "iwa.plugins.olas.service_manager.mech.MechContract"
        ) as mock_mech_class:
            mock_mech = mock_mech_class.return_value
            mock_mech.get_price.return_value = 10**16
            mock_mech.prepare_request_tx.return_value = {
                "data": "0xLegacyData",
                "value": 10**16,
            }
            mock_mech.extract_events.return_value = [
                {"name": "Request"}
            ]

            receipt = {}
            manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = receipt

            result = manager._send_legacy_mech_request(
                data=b"test_data",
            )

        assert result == "0xMockTxHash"

    def test_prepare_tx_returns_none(self, manager):
        """Lines 264-266: prepare_request_tx returns None."""
        with patch(
            "iwa.plugins.olas.service_manager.mech.MechContract"
        ) as mock_mech_class:
            mock_mech = mock_mech_class.return_value
            mock_mech.get_price.return_value = 10**16
            mock_mech.prepare_request_tx.return_value = None

            result = manager._send_legacy_mech_request(
                data=b"test",
            )

        assert result is None


# ──────────────────────────────────────────────────────────────────
# Tests for _validate_priority_mech (lines 288-301, 312-313)
# ──────────────────────────────────────────────────────────────────


class TestValidatePriorityMech:
    """Tests for _validate_priority_mech exception handling."""

    def test_reverted_error_returns_true(self, manager):
        """Lines 288-297: checkMech reverts (v1 marketplace) -> returns True."""
        marketplace = MagicMock()
        marketplace.call.side_effect = Exception("execution reverted: function not found")

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is True

    def test_network_error_returns_false(self, manager):
        """Lines 298-301: real network error -> returns False."""
        marketplace = MagicMock()
        marketplace.call.side_effect = Exception("Connection timeout to RPC")

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is False

    def test_mech_registered_with_factory(self, manager):
        """Lines 303-311: checkMech succeeds, factory lookup succeeds."""
        marketplace = MagicMock()
        marketplace.call.side_effect = [
            ADDR_MULTISIG,    # checkMech returns non-zero
            ADDR_FACTORY,     # mapAgentMechFactories returns factory
        ]

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is True

    def test_mech_registered_factory_zero(self, manager):
        """Lines 306-309: checkMech succeeds, factory is ZERO_ADDRESS -> warning."""
        marketplace = MagicMock()
        marketplace.call.side_effect = [
            ADDR_MULTISIG,    # checkMech returns non-zero
            str(ZERO_ADDRESS),  # mapAgentMechFactories returns zero
        ]

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is True

    def test_factory_fetch_exception(self, manager):
        """Lines 312-313: factory lookup raises exception -> still True (just warns)."""
        marketplace = MagicMock()

        def side_effect(method, *args):
            if method == "checkMech":
                return ADDR_MULTISIG
            raise Exception("factory RPC error")

        marketplace.call.side_effect = side_effect

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is True

    def test_mech_not_registered_zero_address(self, manager):
        """Lines 284-286: checkMech returns ZERO_ADDRESS -> False."""
        marketplace = MagicMock()
        marketplace.call.return_value = str(ZERO_ADDRESS)

        result = manager._validate_priority_mech(marketplace, ADDR_PRIORITY_MECH)
        assert result is False


# ──────────────────────────────────────────────────────────────────
# Tests for _validate_marketplace_params (lines 330-334, 345-349, 357)
# ──────────────────────────────────────────────────────────────────


class TestValidateMarketplaceParams:
    """Tests for _validate_marketplace_params."""

    def test_response_timeout_out_of_bounds(self, manager):
        """Lines 330-333: response_timeout < min or > max -> False."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        # timeout too low
        result = manager._validate_marketplace_params(marketplace, 10, payment_type)
        assert result is False

    def test_response_timeout_above_max(self, manager):
        """Lines 330-333: response_timeout > max -> False."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        # timeout too high
        result = manager._validate_marketplace_params(marketplace, 500, payment_type)
        assert result is False

    def test_no_balance_tracker_returns_false(self, manager):
        """Lines 345-349: payment type has no balance tracker (ZERO_ADDRESS) -> False."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            if method == "mapPaymentTypeBalanceTrackers":
                return str(ZERO_ADDRESS)
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        result = manager._validate_marketplace_params(marketplace, 120, payment_type)
        assert result is False

    def test_payment_type_reverted_v1_proceeds(self, manager):
        """Line 357: mapPaymentTypeBalanceTrackers reverts (v1) -> proceeds with warning."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            if method == "mapPaymentTypeBalanceTrackers":
                raise Exception("execution reverted: function not found")
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        result = manager._validate_marketplace_params(marketplace, 120, payment_type)
        assert result is True

    def test_payment_type_network_error_returns_false(self, manager):
        """Lines 362-364: real network error on payment type check -> False."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            if method == "mapPaymentTypeBalanceTrackers":
                raise Exception("Connection timeout")
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        result = manager._validate_marketplace_params(marketplace, 120, payment_type)
        assert result is False

    def test_all_valid_returns_true(self, manager):
        """Lines 326-366: all validations pass -> True."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                return 60
            if method == "maxResponseTimeout":
                return 300
            if method == "mapPaymentTypeBalanceTrackers":
                return ADDR_FACTORY  # non-zero
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        result = manager._validate_marketplace_params(marketplace, 120, payment_type)
        assert result is True

    def test_timeout_validation_exception_proceeds(self, manager):
        """Lines 337-338: timeout validation raises exception -> proceeds."""
        marketplace = MagicMock()

        def call_side_effect(method, *args):
            if method == "minResponseTimeout":
                raise Exception("no such function")
            if method == "maxResponseTimeout":
                raise Exception("no such function")
            if method == "mapPaymentTypeBalanceTrackers":
                return ADDR_FACTORY
            return MagicMock()

        marketplace.call.side_effect = call_side_effect
        payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        result = manager._validate_marketplace_params(marketplace, 120, payment_type)
        assert result is True


# ──────────────────────────────────────────────────────────────────
# Tests for _resolve_marketplace_config (line 377)
# ──────────────────────────────────────────────────────────────────


class TestResolveMarketplaceConfig:
    """Tests for _resolve_marketplace_config."""

    def test_no_marketplace_found_raises(self, manager):
        """Line 377: no marketplace address for chain -> ValueError."""
        manager.chain_name = "unknown_chain"
        with pytest.raises(ValueError, match="Mech Marketplace address not found"):
            manager._resolve_marketplace_config(None, ADDR_PRIORITY_MECH)

    def test_no_priority_mech_raises(self, manager):
        """Line 380: priority_mech is None -> ValueError."""
        with pytest.raises(ValueError, match="priority_mech is required"):
            manager._resolve_marketplace_config(ADDR_MARKETPLACE_V2, None)

    def test_both_provided(self, manager):
        """Lines 371-382: both addresses provided -> resolved."""
        mp, pm = manager._resolve_marketplace_config(ADDR_MARKETPLACE_V2, ADDR_PRIORITY_MECH)
        assert mp == ADDR_MARKETPLACE_V2
        assert str(pm) == ADDR_PRIORITY_MECH

    def test_marketplace_defaults_to_constant(self, manager):
        """Line 375: marketplace_addr is None -> fallback to OLAS_MECH_MARKETPLACE_V2."""
        mp, pm = manager._resolve_marketplace_config(None, ADDR_PRIORITY_MECH)
        assert mp == str(
            ADDR_MARKETPLACE_V2
        )  # Should be the gnosis OLAS_MECH_MARKETPLACE_V2


# ──────────────────────────────────────────────────────────────────
# Tests for _send_marketplace_mech_request (lines 438, 473-474)
# ──────────────────────────────────────────────────────────────────


class TestSendMarketplaceMechRequest:
    """Tests for _send_marketplace_mech_request."""

    def test_dispatch_to_v1(self, manager):
        """Line 438: marketplace in V1_MARKETPLACES dispatches to _send_v1_marketplace_request."""
        with patch.object(
            manager, "_send_v1_marketplace_request", return_value="0xV1TX"
        ) as mock_v1:
            result = manager._send_marketplace_mech_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V1,
                priority_mech=ADDR_PRIORITY_MECH,
            )

        assert result == "0xV1TX"
        mock_v1.assert_called_once()

    def test_prepare_tx_returns_none(self, manager, mock_wallet):
        """Lines 473-474: prepare_request_tx returns None -> returns None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe

        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
        ) as mock_mp_class:
            mock_mp = mock_mp_class.return_value
            mock_mp.call.return_value = ADDR_MULTISIG  # checkMech passes
            mock_mp.prepare_request_tx.return_value = None

            result = manager._send_marketplace_mech_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V2,
                priority_mech=ADDR_PRIORITY_MECH,
                value=10**16,
            )

        assert result is None

    def test_no_service_returns_none(self, manager):
        """Line 424-426: no service -> returns None."""
        manager.service = None
        result = manager._send_marketplace_mech_request(data=b"test")
        assert result is None

    def test_resolve_fails_returns_none(self, manager):
        """Lines 432-434: _resolve_marketplace_config raises ValueError -> None."""
        result = manager._send_marketplace_mech_request(
            data=b"test",
            marketplace_address=None,
            priority_mech=None,
        )
        assert result is None

    def test_validate_priority_mech_fails(self, manager):
        """Line 450: _validate_priority_mech returns False -> None."""
        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
        ) as mock_mp_class:
            mock_mp = mock_mp_class.return_value
            # checkMech returns ZERO_ADDRESS -> validation fails
            mock_mp.call.return_value = str(ZERO_ADDRESS)

            result = manager._send_marketplace_mech_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V2,
                priority_mech=ADDR_PRIORITY_MECH,
            )

        assert result is None

    def test_validate_marketplace_params_fails(self, manager):
        """Line 458: _validate_marketplace_params returns False -> None."""
        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
        ) as mock_mp_class:
            mock_mp = mock_mp_class.return_value
            # checkMech passes
            mock_mp.call.side_effect = self._marketplace_call_side_effect

            result = manager._send_marketplace_mech_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V2,
                priority_mech=ADDR_PRIORITY_MECH,
                value=10**16,
            )

        assert result is None

    @staticmethod
    def _marketplace_call_side_effect(method, *args):
        """Side effect for marketplace.call that passes priority mech but fails params."""
        if method == "checkMech":
            return ADDR_MULTISIG  # non-zero = registered
        if method == "mapAgentMechFactories":
            return ADDR_FACTORY
        if method == "minResponseTimeout":
            return 60
        if method == "maxResponseTimeout":
            return 300
        if method == "mapPaymentTypeBalanceTrackers":
            return str(ZERO_ADDRESS)  # no balance tracker -> fails
        return MagicMock()


# ──────────────────────────────────────────────────────────────────
# Tests for _send_v1_marketplace_request (lines 496-547)
# ──────────────────────────────────────────────────────────────────


class TestSendV1MarketplaceRequest:
    """Tests for _send_v1_marketplace_request."""

    def test_no_service_returns_none(self, manager):
        """Lines 496-498: no service -> None."""
        manager.service = None
        result = manager._send_v1_marketplace_request(
            data=b"test",
            marketplace_address=ADDR_MARKETPLACE_V1,
            priority_mech=ADDR_PRIORITY_MECH,
        )
        assert result is None

    def test_no_mech_info_returns_none(self, manager):
        """Lines 502-504: marketplace not in DEFAULT_PRIORITY_MECH -> None."""
        result = manager._send_v1_marketplace_request(
            data=b"test",
            marketplace_address=ADDR_UNKNOWN_MARKETPLACE,
            priority_mech=ADDR_PRIORITY_MECH,
        )
        assert result is None

    def test_no_mech_staking_instance_returns_none(self, manager):
        """Lines 508-510: mech staking instance is None -> None."""
        with patch.dict(
            "iwa.plugins.olas.service_manager.mech.DEFAULT_PRIORITY_MECH",
            {ADDR_UNKNOWN_MARKETPLACE: (ADDR_PRIORITY_MECH, 100, None)},
        ):
            result = manager._send_v1_marketplace_request(
                data=b"test",
                marketplace_address=ADDR_UNKNOWN_MARKETPLACE,
                priority_mech=ADDR_PRIORITY_MECH,
            )
        assert result is None

    def test_no_requester_staking_returns_none(self, manager):
        """Lines 516-518: service has no staking_contract_address -> None."""
        manager.service.staking_contract_address = None
        result = manager._send_v1_marketplace_request(
            data=b"test",
            marketplace_address=ADDR_MARKETPLACE_V1,
            priority_mech=ADDR_PRIORITY_MECH,
        )
        assert result is None

    def test_prepare_tx_returns_none(self, manager):
        """Lines 543-545: prepare_request_tx returns None -> None."""
        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceV1Contract"
        ) as mock_v1_class:
            mock_v1 = mock_v1_class.return_value
            mock_v1.prepare_request_tx.return_value = None

            result = manager._send_v1_marketplace_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V1,
                priority_mech=ADDR_PRIORITY_MECH,
            )

        assert result is None

    def test_successful_v1_request(self, manager, mock_wallet):
        """Lines 520-552: full successful v1 request flow."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe

        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceV1Contract"
        ) as mock_v1_class:
            mock_v1 = mock_v1_class.return_value
            mock_v1.prepare_request_tx.return_value = {
                "data": "0xV1Data",
                "value": 10**16,
            }
            mock_v1.extract_events.return_value = [{"name": "MarketplaceRequest"}]

            manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = {}

            result = manager._send_v1_marketplace_request(
                data=b"test",
                marketplace_address=ADDR_MARKETPLACE_V1,
                priority_mech=ADDR_PRIORITY_MECH,
                value=10**16,
            )

        assert result == "0xMockTxHash"


# ──────────────────────────────────────────────────────────────────
# Tests for _execute_mech_tx (lines 563-564, 584-586, 603-604)
# ──────────────────────────────────────────────────────────────────


class TestExecuteMechTx:
    """Tests for _execute_mech_tx."""

    def test_no_service_returns_none(self, manager):
        """Lines 563-564: no service -> None."""
        manager.service = None
        result = manager._execute_mech_tx(
            tx_data={"data": "0x", "value": 0},
            to_address=ADDR_MULTISIG,
            contract_instance=MagicMock(),
            expected_event="Request",
        )
        assert result is None

    def test_safe_transaction_exception(self, manager, mock_wallet):
        """Lines 584-586: Safe transaction raises exception -> None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe
        mock_wallet.safe_service.execute_safe_transaction.side_effect = Exception(
            "Safe exec failed"
        )

        result = manager._execute_mech_tx(
            tx_data={"data": "0xABC", "value": 100},
            to_address=ADDR_PRIORITY_MECH,
            contract_instance=MagicMock(),
            expected_event="Request",
        )
        assert result is None

    def test_eoa_transaction_fails(self, manager, mock_wallet):
        """Lines 603-604: EOA tx fails (success=False) -> tx_hash is None -> None."""
        from iwa.core.models import StoredAccount

        mock_eoa = MagicMock(spec=StoredAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_eoa
        mock_wallet.sign_and_send_transaction.return_value = (False, {})

        result = manager._execute_mech_tx(
            tx_data={"data": "0xABC", "value": 100},
            to_address=ADDR_PRIORITY_MECH,
            contract_instance=MagicMock(),
            expected_event="Request",
        )
        assert result is None

    def test_eoa_transaction_success(self, manager, mock_wallet):
        """EOA tx success path."""
        from iwa.core.models import StoredAccount

        mock_eoa = MagicMock(spec=StoredAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_eoa
        mock_wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": b"\x00" * 32},
        )

        mock_contract = MagicMock()
        mock_contract.extract_events.return_value = [{"name": "Request"}]

        manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = {}

        result = manager._execute_mech_tx(
            tx_data={"data": "0xABC", "value": 100},
            to_address=ADDR_PRIORITY_MECH,
            contract_instance=mock_contract,
            expected_event="Request",
        )
        assert result is not None

    def test_event_not_found(self, manager, mock_wallet):
        """Event not found in transaction logs -> None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe
        mock_wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash"

        mock_contract = MagicMock()
        mock_contract.extract_events.return_value = [{"name": "SomeOtherEvent"}]

        manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = {}

        result = manager._execute_mech_tx(
            tx_data={"data": "0xABC", "value": 100},
            to_address=ADDR_PRIORITY_MECH,
            contract_instance=mock_contract,
            expected_event="Request",
        )
        assert result is None

    def test_event_verification_exception(self, manager, mock_wallet):
        """Event verification raises exception -> None."""
        from iwa.core.models import StoredSafeAccount

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe
        mock_wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash"

        manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.side_effect = (
            Exception("receipt timeout")
        )

        result = manager._execute_mech_tx(
            tx_data={"data": "0xABC", "value": 100},
            to_address=ADDR_PRIORITY_MECH,
            contract_instance=MagicMock(),
            expected_event="Request",
        )
        assert result is None


# ──────────────────────────────────────────────────────────────────
# Tests for _prepare_marketplace_params
# ──────────────────────────────────────────────────────────────────


class TestPrepareMarketplaceParams:
    """Tests for _prepare_marketplace_params."""

    def test_defaults(self, manager):
        """All None -> defaults applied."""
        value, rate, p_type = manager._prepare_marketplace_params(None, None, None)
        assert value == 10_000_000_000_000_000
        assert rate == value
        assert p_type == bytes.fromhex(PAYMENT_TYPE_NATIVE)

    def test_explicit_values(self, manager):
        """Explicit values are used."""
        custom_pt = b"\x01" * 32
        value, rate, p_type = manager._prepare_marketplace_params(999, 555, custom_pt)
        assert value == 999
        assert rate == 555
        assert p_type == custom_pt

    def test_max_delivery_rate_defaults_to_value(self, manager):
        """max_delivery_rate defaults to value when not specified."""
        value, rate, p_type = manager._prepare_marketplace_params(12345, None, None)
        assert rate == 12345
