from unittest.mock import MagicMock

from iwa.plugins.olas.service_manager import ServiceManager


def test_service_manager_structure():
    """Verify that ServiceManager has all expected methods from mixins."""
    wallet_mock = MagicMock()
    sm = ServiceManager(wallet=wallet_mock)

    # Check Lifecycle methods
    assert hasattr(sm, "create")
    assert hasattr(sm, "deploy")
    assert hasattr(sm, "spin_up")
    assert hasattr(sm, "wind_down")

    # Check Staking methods
    assert hasattr(sm, "stake")
    assert hasattr(sm, "unstake")
    assert hasattr(sm, "get_staking_status")

    # Check Drain methods
    assert hasattr(sm, "drain_service")
    assert hasattr(sm, "claim_rewards")

    # Check Mech methods
    assert hasattr(sm, "send_mech_request")

    # Check Base methods
    assert hasattr(sm, "get")
    assert hasattr(sm, "_init_contracts")
