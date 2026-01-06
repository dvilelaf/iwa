"""Test TransferService structure after refactoring."""

import inspect

from iwa.core.services.transfer import TransferService


def test_transfer_service_structure():
    """Verify TransferService has all expected methods from mixins."""
    service_methods = dict(inspect.getmembers(TransferService, predicate=inspect.isfunction))

    # Check Base methods
    assert "_resolve_destination" in service_methods
    assert "_calculate_gas_info" in service_methods

    # Check Native methods
    assert "_send_native_via_safe" in service_methods
    assert "wrap_native" in service_methods
    assert "unwrap_native" in service_methods

    # Check ERC20 methods
    assert "_send_erc20_via_safe" in service_methods
    assert "get_erc20_allowance" in service_methods
    assert "approve_erc20" in service_methods
    assert "transfer_from_erc20" in service_methods

    # Check MultiSend/Drain methods
    assert "multi_send" in service_methods
    assert "drain" in service_methods

    # Check Swap methods
    assert "swap" in service_methods

    # Check Main methods
    assert "send" in service_methods

    print("TransferService structure verification passed!")
