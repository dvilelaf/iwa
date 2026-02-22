"""Tests for subgraph Pydantic models."""

from datetime import datetime

from iwa.plugins.olas.subgraph.models import (
    SubgraphDailyActivity,
    SubgraphMultisig,
    SubgraphProtocolGlobal,
    SubgraphProtocolService,
    SubgraphRewardClaim,
    SubgraphService,
    SubgraphServiceEvents,
    SubgraphStakedService,
    SubgraphStakingContract,
    SubgraphStakingGlobal,
)


class TestSubgraphService:
    def test_from_subgraph_full(self):
        data = {
            "id": "42",
            "multisig": "0xec58bedb8dcdf77ca2baf8b2d8d31204dd3d12ce",
            "agentIds": [25],
            "creationTimestamp": "1700000000",
            "configHash": "0xabcdef",
            "creator": {"id": "0xeb2a22b27c7ad5eee424fd90b376c745e60f914e"},
        }
        svc = SubgraphService.from_subgraph(data, chain="gnosis")

        assert svc.service_id == 42
        assert svc.multisig == "0xec58bedb8dcdf77ca2baf8b2d8d31204dd3d12ce"
        assert svc.agent_ids == [25]
        assert svc.chain == "gnosis"
        assert svc.creator == "0xeb2a22b27c7ad5eee424fd90b376c745e60f914e"
        assert isinstance(svc.creation_timestamp, datetime)

    def test_from_subgraph_minimal(self):
        data = {"id": "1", "agentIds": []}
        svc = SubgraphService.from_subgraph(data)
        assert svc.service_id == 1
        assert svc.multisig is None
        assert svc.agent_ids == []
        assert svc.chain == ""

    def test_from_subgraph_string_creator(self):
        data = {
            "id": "10",
            "creator": "0xabc",
            "agentIds": [25],
        }
        svc = SubgraphService.from_subgraph(data)
        assert svc.creator == "0xabc"


class TestSubgraphMultisig:
    def test_from_subgraph(self):
        data = {
            "id": "0xmultisig",
            "serviceId": 42,
            "creator": "0xcreator",
            "agentIds": [25],
            "creationTimestamp": "1700000000",
        }
        ms = SubgraphMultisig.from_subgraph(data)
        assert ms.address == "0xmultisig"
        assert ms.service_id == 42
        assert ms.creator == "0xcreator"


class TestSubgraphDailyActivity:
    def test_from_subgraph(self):
        data = {
            "dayTimestamp": "1700000000",
            "agentId": 25,
            "txCount": 150,
            "activeMultisigCount": 42,
        }
        da = SubgraphDailyActivity.from_subgraph(data)
        assert da.agent_id == 25
        assert da.tx_count == 150
        assert da.active_multisig_count == 42
        assert isinstance(da.day_timestamp, datetime)


class TestSubgraphStakingContract:
    def test_from_subgraph(self):
        data = {
            "id": "0xcontract_bytes",
            "instance": "0xcontract",
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
        sc = SubgraphStakingContract.from_subgraph(data, chain="gnosis")
        assert sc.address == "0xcontract"
        assert sc.max_num_services == 50
        assert sc.rewards_per_second == 1000000000
        assert sc.agent_ids == [25]
        assert sc.chain == "gnosis"

    def test_from_subgraph_no_instance(self):
        data = {
            "id": "0xfallback",
            "maxNumServices": "10",
            "agentIds": [],
        }
        sc = SubgraphStakingContract.from_subgraph(data)
        assert sc.address == "0xfallback"


class TestSubgraphStakedService:
    def test_from_subgraph(self):
        data = {
            "id": "42",
            "currentOlasStaked": "20000000000000000000000",
            "olasRewardsEarned": "5000000000000000000",
            "blockNumber": "12345",
            "blockTimestamp": "1700000000",
        }
        ss = SubgraphStakedService.from_subgraph(data)
        assert ss.service_id == 42
        assert ss.current_olas_staked == 20000000000000000000000
        assert ss.olas_rewards_earned == 5000000000000000000
        assert ss.block_number == 12345
        assert isinstance(ss.block_timestamp, datetime)


class TestSubgraphRewardClaim:
    def test_from_subgraph(self):
        data = {
            "epoch": "50",
            "serviceId": "42",
            "owner": "0xowner",
            "multisig": "0xmultisig",
            "reward": "1000000000000000000",
            "blockNumber": "12345",
            "blockTimestamp": "1700000100",
            "transactionHash": "0xtxhash",
        }
        rc = SubgraphRewardClaim.from_subgraph(data)
        assert rc.epoch == 50
        assert rc.service_id == 42
        assert rc.reward == 1000000000000000000
        assert rc.owner == "0xowner"
        assert isinstance(rc.block_timestamp, datetime)


class TestSubgraphServiceEvents:
    def test_default(self):
        e = SubgraphServiceEvents(service_id=42)
        assert e.staked == []
        assert e.unstaked == []
        assert e.inactivity_warnings == []
        assert e.evictions == []


class TestSubgraphStakingGlobal:
    def test_defaults(self):
        g = SubgraphStakingGlobal()
        assert g.cumulative_olas_staked == 0
        assert g.current_olas_staked == 0
        assert g.total_rewards == 0


class TestSubgraphProtocolService:
    def test_from_subgraph(self):
        data = {
            "serviceId": "10",
            "publicId": "valory/trader",
            "state": "4",
            "agentIds": ["25"],
            "threshold": "1",
            "multisig": "0xmultisig",
            "instances": ["0xinstance1"],
            "owner": "0xowner",
            "description": "A trader service",
        }
        ps = SubgraphProtocolService.from_subgraph(data)
        assert ps.service_id == 10
        assert ps.public_id == "valory/trader"
        assert ps.state == 4
        assert ps.agent_ids == [25]
        assert ps.owner == "0xowner"


class TestSubgraphProtocolGlobal:
    def test_defaults(self):
        g = SubgraphProtocolGlobal()
        assert g.total_builders == 0
        assert g.total_agents == 0
        assert g.total_components == 0
        assert g.total_services == 0
