"""Tests for StakingSubgraph."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.subgraph.client import clear_cache
from iwa.plugins.olas.subgraph.staking import StakingSubgraph

CONTRACT_RAW = {
    "id": "0xcontract_bytes",
    "instance": "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
    "implementation": "0ximpl",
    "maxNumServices": "50",
    "rewardsPerSecond": "1000000000",
    "minStakingDeposit": "10000000000000000000000",
    "minStakingDuration": "86400",
    "maxNumInactivityPeriods": "3",
    "livenessPeriod": "3600",
    "timeForEmissions": "2592000",
    "numAgentInstances": "1",
    "agentIds": ["25"],
    "threshold": "1",
    "configHash": "0xhash",
    "activityChecker": "0xchecker",
    "serviceRegistry": "0xregistry",
    "metadataHash": "0xmeta",
}

# The staking subgraph requires an API key for most chains.
# Mode has a free proxy endpoint.
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


def _mock_session_with(responses):
    """Create a mock session factory that returns given responses in order."""
    mock_session = MagicMock()
    mocks = []
    for resp_data in responses:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = resp_data
        mocks.append(mock_resp)
    mock_session.post.side_effect = mocks
    return mock_session


class TestGetAllContracts:
    def test_basic(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {"data": {"stakingContracts": [CONTRACT_RAW]}},
                {"data": {"stakingContracts": []}},
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            contracts = staking.get_all_contracts("gnosis")

        assert len(contracts) == 1
        assert contracts[0].address == "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
        assert contracts[0].max_num_services == 50
        assert contracts[0].agent_ids == [25]

    def test_by_agent_id(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {"data": {"stakingContracts": [CONTRACT_RAW]}},
                {"data": {"stakingContracts": []}},
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            contracts = staking.get_all_contracts("gnosis", agent_id=25)

        assert len(contracts) == 1


class TestGetServiceStakingInfo:
    def test_found(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {
                    "data": {
                        "service": {
                            "id": "42",
                            "currentOlasStaked": "20000000000000000000000",
                            "olasRewardsEarned": "5000000000000000000",
                            "olasRewardsClaimed": "3000000000000000000",
                            "latestStakingContract": "0xcontract",
                            "totalEpochsParticipated": "100",
                        }
                    }
                }
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            info = staking.get_service_staking_info("gnosis", 42)

        assert info is not None
        assert info.service_id == 42
        assert info.total_epochs_participated == 100

    def test_not_found(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {"data": {"service": None}}
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            info = staking.get_service_staking_info("gnosis", 99999)

        assert info is None


class TestGetServiceRewardsHistory:
    def test_basic(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {
                    "data": {
                        "serviceRewardsHistories": [
                            {
                                "id": "42-0xcontract-50",
                                "epoch": "50",
                                "contractAddress": "0xcontract",
                                "rewardAmount": "1000000000000000000",
                                "checkpointedAt": "1700000000",
                                "blockTimestamp": "1700000100",
                            },
                            {
                                "id": "42-0xcontract-49",
                                "epoch": "49",
                                "contractAddress": "0xcontract",
                                "rewardAmount": "0",
                                "checkpointedAt": "1699990000",
                                "blockTimestamp": "1699990100",
                            },
                        ]
                    }
                }
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            history = staking.get_service_rewards_history("gnosis", 42)

        assert len(history) == 2
        assert history[0].epoch == 50
        assert history[0].reward_amount == 1000000000000000000
        assert history[1].reward_amount == 0


class TestGetServiceEvents:
    def test_basic(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {"data": {"serviceStakeds": [{"epoch": "1", "serviceId": "42"}]}},
                {"data": {"serviceUnstakeds": []}},
                {"data": {"serviceInactivityWarnings": []}},
                {"data": {"servicesEvicteds": []}},
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            events = staking.get_service_events("gnosis", 42)

        assert events.service_id == 42
        assert len(events.staked) == 1
        assert len(events.unstaked) == 0


class TestGetActiveServices:
    def test_basic(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {
                    "data": {
                        "activeServiceEpoches": [
                            {
                                "id": "0xcontract-50",
                                "contractAddress": "0xcontract",
                                "epoch": "50",
                                "activeServiceIds": ["42", "43", "44"],
                                "blockTimestamp": "1700000000",
                            }
                        ]
                    }
                }
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            active = staking.get_active_services("gnosis", "0xcontract")

        assert active == [42, 43, 44]


class TestGetGlobalStats:
    def test_basic(self):
        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_factory:
            mock_factory.return_value = _mock_session_with([
                {
                    "data": {
                        "globals": [
                            {
                                "id": "global",
                                "cumulativeOlasStaked": "1000000",
                                "cumulativeOlasUnstaked": "500000",
                                "currentOlasStaked": "500000",
                                "totalRewards": "100000",
                            }
                        ]
                    }
                }
            ])

            staking = StakingSubgraph(api_key=API_KEY)
            stats = staking.get_global_stats("gnosis")

        assert stats is not None
        assert stats.current_olas_staked == 500000
        assert stats.total_rewards == 100000


class TestInvalidChain:
    def test_raises_on_unknown_chain_no_key(self):
        staking = StakingSubgraph()
        with pytest.raises(ValueError, match="No Staking endpoint"):
            staking.get_all_contracts("solana")
