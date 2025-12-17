from unittest.mock import MagicMock, mock_open, patch

from iwa.plugins.olas.contracts.staking import StakingContract


def test_staking_contract_coverage():
    with (
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_chains,
        patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"),
        patch("builtins.open", mock_open(read_data="[]")),
    ):
        # Setup mocks
        mock_interface = MagicMock()
        mock_chains.return_value.get.return_value = mock_interface

        # Mock contract calls in __init__
        mock_interface.call_contract.side_effect = lambda method, *args: {
            "activityChecker": "0xChecker",
            "availableRewards": 100,
            "balance": 1000,
            "livenessPeriod": 3600,
            "rewardsPerSecond": 1,
            "maxNumServices": 10,
            "minStakingDeposit": 100,
            "minStakingDuration": 86400,
            "stakingToken": "0xToken",
        }.get(method, 0)

        # Instantiate (This covers __init__ logic)
        contract = StakingContract(address="0x123")
        assert contract.address == "0x123"
