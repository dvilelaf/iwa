from unittest.mock import MagicMock, patch

import pytest

from iwa.core.contracts.cache import ContractCache
from iwa.plugins.olas.contracts.staking import StakingContract


@pytest.fixture
def mock_chain_interface():
    with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_chains:
        mock_interface = MagicMock()
        mock_chains.return_value.get.return_value = mock_interface

        # Mock web3 and contract
        mock_web3_backend = MagicMock()
        mock_interface.web3._web3 = mock_web3_backend

        mock_contract = MagicMock()
        mock_web3_backend.eth.contract.return_value = mock_contract

        # Mock with_retry to execute the function
        mock_interface.with_retry.side_effect = lambda func, **kwargs: func()

        # Yield both interface and contract mock
        yield mock_interface, mock_contract


def test_staking_contract_lazy_loading(mock_chain_interface):
    """Verify StakingContract init does NOT make RPC calls."""
    mock_interface, mock_contract = mock_chain_interface

    # Reset ContractCache
    ContractCache().clear()

    # Instantiate logic
    contract = StakingContract(address="0x123", chain_name="gnosis")

    # Assert NO calls to call yet (since we mock with_retry to execute immediately, 0 calls means 0 executions)
    assert mock_interface.with_retry.call_count == 0

    # Setup return value
    # livenessPeriod is a property that calls "livenessPeriod" on contract
    mock_contract.functions.livenessPeriod.return_value.call.return_value = 3600

    # Access property
    val = contract.liveness_period
    assert val == 3600

    # Assert 1 call
    assert mock_contract.functions.livenessPeriod.return_value.call.call_count == 1

    # Access again
    val = contract.liveness_period

    # Assert still 1 call (cached)
    assert mock_contract.functions.livenessPeriod.return_value.call.call_count == 1


def test_contract_cache_singleton(mock_chain_interface):
    """Verify ContractCache returns same instance and reuses property cache."""
    mock_interface, mock_contract = mock_chain_interface
    ContractCache().clear()

    c1 = ContractCache().get_contract(StakingContract, "0xABC", "gnosis")
    c2 = ContractCache().get_contract(StakingContract, "0xabc", "gnosis")  # Check ignore case

    assert c1 is c2

    # populate cache on c1
    mock_contract.functions.maxNumServices.return_value.call.return_value = 500

    val1 = c1.max_num_services
    assert val1 == 500
    assert mock_contract.functions.maxNumServices.return_value.call.call_count == 1

    # access on c2
    val2 = c2.max_num_services
    assert val2 == 500
    # Call count should NOT increase
    assert mock_contract.functions.maxNumServices.return_value.call.call_count == 1


def test_epoch_aware_caching(mock_chain_interface):
    """Verify ts_checkpoint caching logic."""
    mock_interface, mock_contract = mock_chain_interface
    ContractCache().clear()
    contract = StakingContract(address="0xEpoch", chain_name="gnosis")

    # Mock return values for tsCheckpoint
    # We use side_effect on the call() method to simulate changing return values if needed
    # But here we just want it to return 1000 once
    mock_contract.functions.tsCheckpoint.return_value.call.return_value = 1000

    # Set liveness period in cache to avoid RPC call for it
    contract._contract_params_cache["livenessPeriod"] = 600

    # 1. Fetch ts_checkpoint
    ts = contract.ts_checkpoint()
    assert ts == 1000
    assert mock_contract.functions.tsCheckpoint.return_value.call.call_count == 1

    # 2. Call again - should be cached
    ts2 = contract.ts_checkpoint()
    assert ts2 == 1000
    assert mock_contract.functions.tsCheckpoint.return_value.call.call_count == 1
