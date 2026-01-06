"""Tests for Olas service lifecycle: create, activate, register, deploy."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, OlasServiceImporter
from iwa.plugins.olas.models import OlasConfig, Service
from iwa.plugins.olas.service_manager import ServiceManager


@pytest.fixture
def mock_wallet():
    """Mock wallet with master account."""
    w = MagicMock()
    w.master_account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    return w


@pytest.fixture
def sm(mock_wallet):
    """ServiceManager fixture."""
    with (
        patch("iwa.core.models.Config"),
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci,
    ):
        mock_ci.get_instance.return_value.get.return_value.chain.get_token_address.side_effect = (
            lambda x: x
        )
        return ServiceManager(mock_wallet)


@pytest.fixture
def importer(mock_wallet):
    """OlasServiceImporter fixture."""
    with patch("iwa.core.models.Config"):
        return OlasServiceImporter(mock_wallet)


# --- ServiceManager Edge Cases ---


def test_sm_create_utility_not_found(sm):
    """Target service_manager.py:203 (utility not found)."""
    with patch("iwa.plugins.olas.constants.OLAS_CONTRACTS", {"gnosis": {}}):
        sm.wallet.sign_and_send_transaction.return_value = (True, {"status": 1})
        # Mocking registry.extract_events which is what sm.create now uses
        sm.registry.extract_events = MagicMock(
            return_value=[{"name": "CreateService", "args": {"serviceId": 42}}]
        )

        sid = sm.create("gnosis", "test")
        assert sid == 42


def test_sm_create_approve_fail(sm):
    """Target service_manager.py:217 (approve fail)."""
    sm.wallet.sign_and_send_transaction.return_value = (True, {"status": 1})
    sm.registry.extract_events = MagicMock(
        return_value=[{"name": "CreateService", "args": {"serviceId": 42}}]
    )

    sm.transfer_service.approve_erc20.return_value = False
    sid = sm.create(
        "gnosis", "test", token_address_or_tag="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    )
    assert sid == 42


def test_sm_activate_not_preregistration(sm):
    """Target service_manager.py:228 (state mismatch)."""
    sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)
    sm.registry = MagicMock()
    sm.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    success = sm.activate_registration()
    assert success is False


def test_sm_checkpoint_check_exception(sm):
    """Target service_manager.py:597 (checkpoint check exception)."""
    with patch("iwa.plugins.olas.contracts.staking.StakingContract") as mock_stk_cls:
        mock_stk = mock_stk_cls.return_value
        mock_stk.is_checkpoint_needed.side_effect = Exception("error")
        success = sm.call_checkpoint("gnosis")
        assert success is False


def test_sm_stake_fail(sm):
    """Target service_manager.py:690 (stake fail)."""
    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)
    sm.registry = MagicMock()
    sm.registry.get_service.return_value = {"state": ServiceState.DEPLOYED, "security_deposit": 1}
    sm.transfer_service.approve_erc20.return_value = True
    sm.wallet.sign_and_send_transaction.return_value = (False, None)

    with (
        patch("iwa.plugins.olas.contracts.staking.StakingContract") as mock_stk_cls,
        patch("iwa.plugins.olas.service_manager.staking.ERC20Contract"),
    ):
        mock_stk = mock_stk_cls.return_value
        mock_stk.get_service_info.return_value = {"staking_state": 1}
        mock_stk.staking_token_address = addr
        mock_stk.get_requirements.return_value = {
            "staking_token": addr,
            "min_staking_deposit": 50000000000000000000,
            "num_agent_instances": 1,
            "required_agent_bond": 50000000000000000000,
        }
        success = sm.stake(mock_stk)
        assert success is False


# --- Importer Edge Cases ---


def test_importer_encrypted_no_pwd(importer):
    """Target importer.py:192 (encrypted key without password)."""
    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    key = DiscoveredKey(address=addr, is_encrypted=True, encrypted_keystore={"crypto": {}})
    importer.key_storage.find_stored_account.return_value = None
    success, msg = importer._import_key(key, "service", password=None)
    assert success is False
    assert "password" in msg


def test_importer_safe_duplicate(importer):
    """Target importer.py:308 (duplicate safe)."""
    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    service = DiscoveredService(service_id=1, chain_name="gnosis", safe_address=addr)
    importer.key_storage.find_stored_account.return_value = MagicMock()
    success, msg = importer._import_safe(service)
    assert success is False
    assert msg == "duplicate"


def test_olas_config_remove_not_exists():
    """Target models.py:85-88 (remove service not exists)."""
    config = OlasConfig()
    assert config.remove_service("not:exists") is False


def test_olas_config_get_service_by_multisig():
    """Target models.py:106-110 (get by multisig)."""
    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    s = Service(service_name="t", chain_name="g", service_id=1, multisig_address=addr)
    config = OlasConfig(services={"g:1": s})
    assert config.get_service_by_multisig(addr) == s
    assert config.get_service_by_multisig("0x0000000000000000000000000000000000000000") is None
