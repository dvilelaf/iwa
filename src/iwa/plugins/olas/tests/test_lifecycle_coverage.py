"""Additional tests for lifecycle.py to improve coverage beyond 86%.

Targets uncovered lines identified by coverage report:
114-119, 225-227, 230-231, 315-316, 329, 368-369, 393-395, 433-434,
465-466, 473-475, 494-495, 503-517, 606-607, 652-657, 673, 701-702,
713-714, 733-735, 811-812, 869-870, 886-901, 1045, 1064, 1079-1080,
1111-1112, 1119-1121, 1149, 1171, 1174-1175, 1199-1202
"""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.constants import ZERO_ADDRESS
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager

# Valid Ethereum addresses for test constants
ADDR_OWNER = "0x1111111111111111111111111111111111111111"
ADDR_AGENT = "0x2222222222222222222222222222222222222222"
ADDR_TOKEN = "0x3333333333333333333333333333333333333333"
ADDR_UTILITY = "0x4444444444444444444444444444444444444444"
ADDR_MULTISIG = "0x5555555555555555555555555555555555555555"
ADDR_MASTER = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"


@pytest.fixture
def mock_wallet():
    """Mock wallet with master account."""
    w = MagicMock()
    w.master_account.address = ADDR_MASTER
    return w


@pytest.fixture
def sm(mock_wallet):
    """ServiceManager fixture with mocked dependencies."""
    with (
        patch("iwa.core.models.Config"),
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci,
    ):
        mock_ci.get_instance.return_value.get.return_value.chain.get_token_address.side_effect = (
            lambda x: x
        )
        mgr = ServiceManager(mock_wallet)
        return mgr


def _make_service(**overrides):
    """Helper to create a Service with sensible defaults."""
    defaults = dict(
        service_name="test_svc",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[25],
        service_owner_eoa_address=ADDR_OWNER,
        token_address=ADDR_TOKEN,
    )
    defaults.update(overrides)
    return Service(**defaults)


# ============================================================================
# _get_label  (lines 114-119)
# ============================================================================


class TestGetLabel:
    """Tests for _get_label method."""

    def test_get_label_empty_address(self, sm):
        """Line 106: returns 'None' for empty address."""
        assert sm._get_label("") == "None"

    def test_get_label_returns_tag(self, sm):
        """Line 110-111: returns tag when account_service has a tag."""
        sm.wallet.account_service.get_tag_by_address.return_value = "my_wallet"
        assert sm._get_label(ADDR_OWNER) == "my_wallet"

    def test_get_label_returns_token_name(self, sm):
        """Lines 114-117: returns token_name when tag is None."""
        sm.wallet.account_service.get_tag_by_address.return_value = None
        with patch("iwa.plugins.olas.service_manager.lifecycle.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value.chain.get_token_name.return_value = "OLAS"
            result = sm._get_label(ADDR_TOKEN)
        assert result == "OLAS"

    def test_get_label_returns_address_as_fallback(self, sm):
        """Lines 118-119: returns raw address when no tag and no token name."""
        sm.wallet.account_service.get_tag_by_address.return_value = None
        with patch("iwa.plugins.olas.service_manager.lifecycle.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value.chain.get_token_name.return_value = None
            result = sm._get_label(ADDR_OWNER)
        assert result == ADDR_OWNER


# ============================================================================
# _send_create_transaction  (lines 225-227, 230-231)
# ============================================================================


class TestSendCreateTransaction:
    """Tests for _send_create_transaction exception and None paths."""

    def test_prepare_create_tx_raises_exception(self, sm):
        """Lines 225-227: prepare_create_tx raises exception."""
        sm.manager = MagicMock()
        sm.manager.prepare_create_tx.side_effect = Exception("RPC down")
        account = MagicMock()
        account.address = ADDR_OWNER
        result = sm._send_create_transaction(
            service_owner_account=account,
            token_address=ADDR_TOKEN,
            agent_id_values=[25],
            agent_params=[{"slots": 1, "bond": 1}],
            chain_name="gnosis",
        )
        assert result is None

    def test_prepare_create_tx_returns_none(self, sm):
        """Lines 230-231: prepare_create_tx returns None."""
        sm.manager = MagicMock()
        sm.manager.prepare_create_tx.return_value = None
        account = MagicMock()
        account.address = ADDR_OWNER
        result = sm._send_create_transaction(
            service_owner_account=account,
            token_address=ADDR_TOKEN,
            agent_id_values=[25],
            agent_params=[{"slots": 1, "bond": 1}],
            chain_name="gnosis",
        )
        assert result is None


# ============================================================================
# _approve_token_if_needed  (lines 315-316, 329)
# ============================================================================


class TestApproveTokenIfNeeded:
    """Tests for _approve_token_if_needed edge cases."""

    def test_utility_not_found_for_chain(self, sm):
        """Lines 315-316: utility address not found in OLAS_CONTRACTS."""
        account = MagicMock()
        account.address = ADDR_OWNER
        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS", {"gnosis": {}}
        ):
            sm._approve_token_if_needed(
                token_address=ADDR_TOKEN,
                chain_name="gnosis",
                service_owner_account=account,
                bond_amount_wei=1000,
            )
        # Should log error but not raise

    def test_approve_erc20_fails(self, sm):
        """Line 329: approve_erc20 returns False."""
        account = MagicMock()
        account.address = ADDR_OWNER
        sm.transfer_service.approve_erc20.return_value = False
        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
            {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
        ):
            sm._approve_token_if_needed(
                token_address=ADDR_TOKEN,
                chain_name="gnosis",
                service_owner_account=account,
                bond_amount_wei=1000,
            )
        # Should log error but not raise


# ============================================================================
# activate_registration / _ensure_token_approval_for_activation
# (lines 368-369, 433-434, 465-466, 473-475)
# ============================================================================


class TestActivateRegistration:
    """Tests for activate_registration and token approval edge cases."""

    def test_token_approval_returns_false(self, sm):
        """Lines 368-369: _ensure_token_approval_for_activation returns False."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 5000,
        }
        with patch.object(sm, "_ensure_token_approval_for_activation", return_value=False):
            result = sm.activate_registration()
        assert result is False

    def test_balance_less_than_bond(self, sm):
        """Lines 433-434: owner balance < required bond."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.wallet.balance_service.get_erc20_balance_wei.return_value = 100  # Too low

        with patch.object(sm, "_get_agent_bond_from_token_utility", return_value=5000):
            with patch(
                "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
                {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
            ):
                result = sm._ensure_token_approval_for_activation(
                    token_address=ADDR_TOKEN, security_deposit=5000
                )
        assert result is False

    def test_approve_erc20_fails_during_activation(self, sm):
        """Lines 465-466: approve_erc20 fails in activation token approval."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.wallet.balance_service.get_erc20_balance_wei.return_value = 10000
        sm.wallet.transfer_service.get_erc20_allowance.return_value = 0  # Need approval
        sm.wallet.transfer_service.approve_erc20.return_value = False

        with patch.object(sm, "_get_agent_bond_from_token_utility", return_value=5000):
            with patch(
                "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
                {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
            ):
                result = sm._ensure_token_approval_for_activation(
                    token_address=ADDR_TOKEN, security_deposit=5000
                )
        assert result is False

    def test_ensure_token_approval_exception(self, sm):
        """Lines 473-475: exception in _ensure_token_approval_for_activation."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"

        with patch.object(
            sm, "_get_agent_bond_from_token_utility", side_effect=Exception("boom")
        ):
            result = sm._ensure_token_approval_for_activation(
                token_address=ADDR_TOKEN, security_deposit=5000
            )
        assert result is False


# ============================================================================
# _get_service_token  (lines 393-395)
# ============================================================================


class TestGetServiceToken:
    """Tests for _get_service_token edge cases."""

    def test_token_address_none_and_registry_fails(self, sm):
        """Lines 393-395: service has no token, registry.get_token raises."""
        sm.service = _make_service(token_address=None)
        sm.registry = MagicMock()
        sm.registry.get_token.side_effect = Exception("contract call failed")

        result = sm._get_service_token(1)
        assert result == ZERO_ADDRESS


# ============================================================================
# _get_agent_bond_from_token_utility  (lines 494-495, 503-517)
# ============================================================================


class TestGetAgentBondFromTokenUtility:
    """Tests for _get_agent_bond_from_token_utility."""

    def test_utility_address_not_found(self, sm):
        """Lines 494-495: Token Utility address not found for chain."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS", {"gnosis": {}}
        ):
            result = sm._get_agent_bond_from_token_utility()
        assert result is None

    def test_no_agent_ids_in_service(self, sm):
        """Lines 500-502: no agent_ids in service info."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {"agent_ids": []}

        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
            {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
        ):
            result = sm._get_agent_bond_from_token_utility()
        assert result is None

    def test_successful_bond_retrieval(self, sm):
        """Lines 503-517: successful path through get_agent_bond."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {"agent_ids": [25]}

        mock_utility = MagicMock()
        mock_utility.get_agent_bond.return_value = 5000

        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
            {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
        ):
            with patch(
                "iwa.plugins.olas.service_manager.lifecycle.ContractCache"
            ) as mock_cache:
                mock_cache.return_value.get_contract.return_value = mock_utility
                result = sm._get_agent_bond_from_token_utility()

        assert result == 5000
        mock_utility.get_agent_bond.assert_called_once_with(1, 25)


# ============================================================================
# register_agent / _ensure_agent_token_approval
# (lines 606-607, 652-657, 673, 701-702, 713-714)
# ============================================================================


class TestRegisterAgent:
    """Tests for register_agent edge cases."""

    def test_token_approval_fails(self, sm):
        """Lines 606-607: _ensure_agent_token_approval returns False."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}

        with patch.object(sm, "_ensure_agent_token_approval", return_value=False):
            result = sm.register_agent(agent_address=ADDR_AGENT)
        assert result is False

    def test_get_or_create_agent_account_existing(self, sm):
        """Lines 652-657: ValueError when account already exists."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}

        existing_account = MagicMock()
        existing_account.address = ADDR_AGENT
        sm.wallet.key_storage.generate_new_account.side_effect = ValueError("exists")
        sm.wallet.key_storage.get_account.return_value = existing_account

        result = sm._get_or_create_agent_account(agent_address=None)
        assert result == ADDR_AGENT

    def test_ensure_agent_token_approval_native(self, sm):
        """Line 673: native token returns True immediately."""
        sm.service = _make_service(token_address=str(ZERO_ADDRESS))
        sm.registry = MagicMock()
        sm.registry.get_token.return_value = ZERO_ADDRESS

        result = sm._ensure_agent_token_approval(ADDR_AGENT, bond_amount_wei=1000)
        assert result is True

    def test_ensure_agent_token_sufficient_allowance(self, sm):
        """Lines 701-702: sufficient allowance, no approval needed."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.wallet.transfer_service.get_erc20_allowance.return_value = 10000  # Sufficient

        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
            {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
        ):
            result = sm._ensure_agent_token_approval(ADDR_AGENT, bond_amount_wei=5000)
        assert result is True

    def test_ensure_agent_token_approval_fails(self, sm):
        """Lines 713-714: approve_erc20 fails for agent registration."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.wallet.transfer_service.get_erc20_allowance.return_value = 0  # Need approval
        sm.wallet.transfer_service.approve_erc20.return_value = False

        with patch(
            "iwa.plugins.olas.service_manager.lifecycle.OLAS_CONTRACTS",
            {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
        ):
            result = sm._ensure_agent_token_approval(ADDR_AGENT, bond_amount_wei=5000)
        assert result is False


# ============================================================================
# _send_register_agent_transaction  (lines 733-735)
# ============================================================================


class TestSendRegisterAgentTransaction:
    """Tests for _send_register_agent_transaction native token path."""

    def test_native_token_computes_value_from_security_deposit(self, sm):
        """Lines 733-735: native service uses security_deposit * num_agents."""
        sm.service = _make_service(token_address=str(ZERO_ADDRESS), agent_ids=[25])
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {"security_deposit": 10000}
        sm.registry.get_token.return_value = ZERO_ADDRESS
        sm.registry.extract_events.return_value = [
            {"name": "RegisterInstance", "args": {}}
        ]
        sm.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xabc"},
        )

        with patch.object(sm, "_update_and_save_service_state"):
            result = sm._send_register_agent_transaction(ADDR_AGENT)
        assert result is True

        # Verify value was security_deposit * len(agent_ids) = 10000 * 1
        call_args = sm.manager.prepare_register_agents_tx.call_args
        assert call_args.kwargs.get("value", call_args[1].get("value")) == 10000


# ============================================================================
# deploy  (lines 811-812, 869-870, 886-901)
# ============================================================================


class TestDeploy:
    """Tests for deploy edge cases."""

    def test_deploy_tx_returns_none(self, sm):
        """Lines 811-812: deploy_tx is None."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {"state": ServiceState.FINISHED_REGISTRATION}
        sm.manager.prepare_deploy_tx.return_value = None

        result = sm.deploy()
        assert result is None

    def test_deploy_archive_rename_exception(self, sm):
        """Lines 869-870: rename_account raises during archive logic."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {
            "state": ServiceState.FINISHED_REGISTRATION,
            "threshold": 1,
        }
        sm.registry.extract_events.return_value = [
            {"name": "DeployService", "args": {}},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": ADDR_MULTISIG}},
        ]
        sm.registry.call.return_value = (1, [ADDR_AGENT])
        sm.manager.prepare_deploy_tx.return_value = {"to": ADDR_OWNER}
        sm.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xabc"},
        )
        # Existing multisig with different address triggers archive
        existing_account = MagicMock()
        existing_account.address = ADDR_OWNER  # Different from ADDR_MULTISIG
        sm.wallet.key_storage.find_stored_account.return_value = existing_account
        sm.wallet.key_storage.rename_account.side_effect = Exception("rename failed")

        with patch.object(sm, "_update_and_save_service_state"):
            with patch("iwa.plugins.olas.service_manager.lifecycle.response_cache"):
                result = sm.deploy()
        assert result == ADDR_MULTISIG

    def test_deploy_fund_multisig_success(self, sm):
        """Lines 886-897: fund_multisig=True success path."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {
            "state": ServiceState.FINISHED_REGISTRATION,
            "threshold": 1,
        }
        sm.registry.extract_events.return_value = [
            {"name": "DeployService", "args": {}},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": ADDR_MULTISIG}},
        ]
        sm.registry.call.return_value = (1, [ADDR_AGENT])
        sm.manager.prepare_deploy_tx.return_value = {"to": ADDR_OWNER}
        sm.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xabc"},
        )
        sm.wallet.key_storage.find_stored_account.return_value = None
        sm.wallet.send.return_value = "0xfund_hash"

        with patch.object(sm, "_update_and_save_service_state"):
            with patch("iwa.plugins.olas.service_manager.lifecycle.response_cache"):
                result = sm.deploy(fund_multisig=True)
        assert result == ADDR_MULTISIG
        sm.wallet.send.assert_called_once()

    def test_deploy_fund_multisig_send_fails(self, sm):
        """Lines 898-899: fund_multisig=True but send returns None."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {
            "state": ServiceState.FINISHED_REGISTRATION,
            "threshold": 1,
        }
        sm.registry.extract_events.return_value = [
            {"name": "DeployService", "args": {}},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": ADDR_MULTISIG}},
        ]
        sm.registry.call.return_value = (1, [ADDR_AGENT])
        sm.manager.prepare_deploy_tx.return_value = {"to": ADDR_OWNER}
        sm.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xabc"},
        )
        sm.wallet.key_storage.find_stored_account.return_value = None
        sm.wallet.send.return_value = None  # Funding fails

        with patch.object(sm, "_update_and_save_service_state"):
            with patch("iwa.plugins.olas.service_manager.lifecycle.response_cache"):
                result = sm.deploy(fund_multisig=True)
        assert result == ADDR_MULTISIG  # Deploy still succeeds

    def test_deploy_fund_multisig_exception(self, sm):
        """Lines 900-901: fund_multisig=True but send raises exception."""
        sm.service = _make_service()
        sm.chain_name = "gnosis"
        sm.registry = MagicMock()
        sm.manager = MagicMock()
        sm.registry.get_service.return_value = {
            "state": ServiceState.FINISHED_REGISTRATION,
            "threshold": 1,
        }
        sm.registry.extract_events.return_value = [
            {"name": "DeployService", "args": {}},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": ADDR_MULTISIG}},
        ]
        sm.registry.call.return_value = (1, [ADDR_AGENT])
        sm.manager.prepare_deploy_tx.return_value = {"to": ADDR_OWNER}
        sm.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xabc"},
        )
        sm.wallet.key_storage.find_stored_account.return_value = None
        sm.wallet.send.side_effect = Exception("RPC error")

        with patch.object(sm, "_update_and_save_service_state"):
            with patch("iwa.plugins.olas.service_manager.lifecycle.response_cache"):
                result = sm.deploy(fund_multisig=True)
        assert result == ADDR_MULTISIG  # Deploy still succeeds despite fund failure


# ============================================================================
# spin_up  (lines 1045, 1064, 1079-1080, 1111-1112)
# ============================================================================


class TestSpinUp:
    """Tests for spin_up edge cases."""

    def test_get_service_state_returns_none_initially(self, sm):
        """Line 1045: _get_service_state_safe returns None at start."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.side_effect = Exception("network error")

        result = sm.spin_up()
        assert result is False

    def test_get_service_state_returns_none_after_step(self, sm):
        """Line 1064: _get_service_state_safe returns None after a step."""
        sm.service = _make_service()
        sm.registry = MagicMock()

        # First call returns PRE_REGISTRATION, then action succeeds,
        # then second call to _get_service_state_safe fails
        call_count = [0]

        def get_service_side_effect(sid):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"state": ServiceState.PRE_REGISTRATION}
            raise Exception("network error")

        sm.registry.get_service.side_effect = get_service_side_effect

        with patch.object(sm, "activate_registration", return_value=True):
            result = sm.spin_up()
        assert result is False

    def test_staking_fails(self, sm):
        """Lines 1079-1080: staking fails after deploy."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}

        mock_staking = MagicMock()
        mock_staking.address = ADDR_UTILITY

        with patch.object(sm, "stake", return_value=False):
            result = sm.spin_up(staking_contract=mock_staking)
        assert result is False

    def test_process_spin_up_invalid_state(self, sm):
        """Lines 1111-1112: invalid state in _process_spin_up_state."""
        result = sm._process_spin_up_state(
            current_state=ServiceState.NON_EXISTENT,
            agent_address=None,
            bond_amount_wei=None,
        )
        assert result is False


# ============================================================================
# _get_service_state_safe  (lines 1119-1121)
# ============================================================================


class TestGetServiceStateSafe:
    """Tests for _get_service_state_safe exception handling."""

    def test_exception_returns_none(self, sm):
        """Lines 1119-1121: exception returns None."""
        sm.registry = MagicMock()
        sm.registry.get_service.side_effect = Exception("network failure")
        result = sm._get_service_state_safe(42)
        assert result is None


# ============================================================================
# wind_down  (lines 1149, 1171, 1174-1175, 1199-1202)
# ============================================================================


class TestWindDown:
    """Tests for wind_down edge cases."""

    def test_state_check_returns_none(self, sm):
        """Line 1149: _get_service_state_safe returns None initially."""
        sm.service = _make_service()
        sm.registry = MagicMock()
        sm.registry.get_service.side_effect = Exception("error")

        result = sm.wind_down()
        assert result is False

    def test_state_returns_none_after_action(self, sm):
        """Line 1171: _get_service_state_safe returns None after action."""
        sm.service = _make_service(staking_contract_address=None)
        sm.registry = MagicMock()

        call_count = [0]

        def get_service_side_effect(sid):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"state": ServiceState.DEPLOYED}
            raise Exception("network error")

        sm.registry.get_service.side_effect = get_service_side_effect

        with patch.object(sm, "terminate", return_value=True):
            result = sm.wind_down()
        assert result is False

    def test_state_stuck_after_action(self, sm):
        """Lines 1174-1175: state doesn't change after action."""
        sm.service = _make_service(staking_contract_address=None)
        sm.registry = MagicMock()
        # State never changes
        sm.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}

        with patch.object(sm, "terminate", return_value=True):
            result = sm.wind_down()
        assert result is False

    def test_process_wind_down_unexpected_state(self, sm):
        """Lines 1199-1202: unexpected state in _process_wind_down_state."""
        result = sm._process_wind_down_state(ServiceState.NON_EXISTENT)
        assert result is False
