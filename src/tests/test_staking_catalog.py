"""Tests for the staking contract catalog and query function."""

import unittest

from iwa.plugins.olas.constants import (
    OLAS_TRADER_STAKING_CONTRACTS,
    STAKING_CONTRACTS,
    AgentType,
    ContractStatus,
    MarketplaceType,
    StakingContractInfo,
    get_staking_contracts,
)


class TestStakingCatalog(unittest.TestCase):
    """Tests for the STAKING_CONTRACTS registry."""

    def test_registry_not_empty(self):
        self.assertGreater(len(STAKING_CONTRACTS), 30)

    def test_all_entries_are_dataclasses(self):
        for c in STAKING_CONTRACTS:
            self.assertIsInstance(c, StakingContractInfo)

    def test_agent_ids_use_agent_type_enum(self):
        for c in STAKING_CONTRACTS:
            if c.agent_id is not None:
                self.assertIsInstance(c.agent_id, AgentType, c.name)

    def test_no_duplicate_addresses(self):
        seen = set()
        for c in STAKING_CONTRACTS:
            key = (c.chain, str(c.address).lower())
            self.assertNotIn(key, seen, f"Duplicate: {c.name} ({c.address})")
            seen.add(key)

    def test_all_addresses_are_valid(self):
        for c in STAKING_CONTRACTS:
            addr = str(c.address)
            self.assertTrue(addr.startswith("0x"), f"{c.name}: {addr}")
            self.assertEqual(len(addr), 42, f"{c.name}: {addr}")

    def test_chains_are_known(self):
        known = {
            "arbitrum",
            "base",
            "celo",
            "ethereum",
            "gnosis",
            "optimism",
            "polygon",
        }
        for c in STAKING_CONTRACTS:
            self.assertIn(c.chain, known, f"{c.name}: unknown chain {c.chain}")

    def test_new_govern_nominees_are_catalogued(self):
        """Spot-check staking contracts added from Govern nominees."""
        expected = {
            ("gnosis", "0x536d04dbd9a2310152a0d2d8d18dadfca8bb26b0"),
            ("gnosis", "0x12bdd401ac300482f4017c64c6c930ee40424c08"),
            ("gnosis", "0x22fa631064a99c43196ec5f8324b73211ced98f9"),
            ("base", "0xbe6e12364b549622395999db0db53f163994d7af"),
            ("base", "0x51c5f4982b9b0b3c0482678f5847ea6228cc8e54"),
            ("optimism", "0x6891cf116f9a3bdbd1e89413118ef81f69d298c3"),
            ("polygon", "0x8887c2852986e7cbac99b6065ffe53074a6bcc26"),
            ("arbitrum", "0x646ecbe31df12d17a949d65764187408f6bb095d"),
            ("celo", "0x6cc3a0d25e2ac7d8ff119ef92d5523259c6dc821"),
        }
        actual = {(c.chain, str(c.address).lower()) for c in STAKING_CONTRACTS}

        self.assertTrue(expected.issubset(actual), expected - actual)


class TestGetStakingContracts(unittest.TestCase):
    """Tests for the query function."""

    def test_no_filters_returns_all(self):
        result = get_staking_contracts()
        self.assertEqual(len(result), len(STAKING_CONTRACTS))

    def test_filter_by_chain(self):
        gnosis = get_staking_contracts(chain="gnosis")
        base = get_staking_contracts(chain="base")
        self.assertGreater(len(gnosis), 20)
        self.assertGreater(len(base), 0)
        for c in gnosis:
            self.assertEqual(c.chain, "gnosis")
        for c in base:
            self.assertEqual(c.chain, "base")

    def test_filter_by_agent_id(self):
        traders = get_staking_contracts(agent_id=AgentType.TRADER)
        self.assertGreater(len(traders), 20)
        for c in traders:
            self.assertIs(c.agent_id, AgentType.TRADER)

    def test_filter_by_agent_id_accepts_raw_int_for_compatibility(self):
        enum_result = get_staking_contracts(agent_id=AgentType.TRADER)
        int_result = get_staking_contracts(agent_id=25)

        self.assertEqual(int_result, enum_result)

    def test_filter_by_marketplace_single(self):
        legacy = get_staking_contracts(marketplace=MarketplaceType.LEGACY)
        self.assertGreater(len(legacy), 5)
        for c in legacy:
            self.assertEqual(c.marketplace, MarketplaceType.LEGACY)

    def test_filter_by_marketplace_multiple(self):
        result = get_staking_contracts(
            marketplace=[MarketplaceType.LEGACY, MarketplaceType.MM_V2]
        )
        for c in result:
            self.assertIn(
                c.marketplace,
                {MarketplaceType.LEGACY, MarketplaceType.MM_V2},
            )

    def test_filter_by_status(self):
        active = get_staking_contracts(status=ContractStatus.ACTIVE)
        for c in active:
            self.assertEqual(c.status, ContractStatus.ACTIVE)

    def test_combined_filters(self):
        result = get_staking_contracts(
            chain="gnosis",
            agent_id=AgentType.TRADER,
            marketplace=[MarketplaceType.LEGACY, MarketplaceType.MM_V2],
            status=ContractStatus.ACTIVE,
        )
        self.assertGreater(len(result), 10)
        for c in result:
            self.assertEqual(c.chain, "gnosis")
            self.assertIs(c.agent_id, AgentType.TRADER)
            self.assertIn(
                c.marketplace,
                {MarketplaceType.LEGACY, MarketplaceType.MM_V2},
            )
            self.assertEqual(c.status, ContractStatus.ACTIVE)

    def test_supply_contracts_exist(self):
        supply = get_staking_contracts(marketplace=MarketplaceType.SUPPLY)
        self.assertGreaterEqual(len(supply), 7)
        for c in supply:
            self.assertIsNone(c.agent_id)

    def test_base_contracts_exist(self):
        base = get_staking_contracts(chain="base")
        self.assertGreater(len(base), 2)

    def test_new_multichain_contracts_are_queryable(self):
        for chain in ("optimism", "polygon", "arbitrum", "celo"):
            contracts = get_staking_contracts(chain=chain)
            self.assertGreater(len(contracts), 0, chain)
            for contract in contracts:
                self.assertEqual(contract.chain, chain)


class TestBackwardCompat(unittest.TestCase):
    """Tests that OLAS_TRADER_STAKING_CONTRACTS compat shim works."""

    def test_shim_has_gnosis(self):
        self.assertIn("gnosis", OLAS_TRADER_STAKING_CONTRACTS)

    def test_shim_is_dict_of_dicts(self):
        for _chain, contracts in OLAS_TRADER_STAKING_CONTRACTS.items():
            self.assertIsInstance(contracts, dict)
            for name, addr in contracts.items():
                self.assertIsInstance(name, str)
                self.assertTrue(str(addr).startswith("0x"))

    def test_shim_contains_known_contracts(self):
        gnosis = OLAS_TRADER_STAKING_CONTRACTS["gnosis"]
        # Spot-check a few known contracts
        self.assertIn("Hobbyist 1 Legacy (100 OLAS)", gnosis)
        self.assertIn("Expert 8 MM v2 (10k OLAS)", gnosis)
        self.assertIn("Pearl Beta Mech Marketplace V (10k OLAS)", gnosis)
        self.assertIn("Pearl Beta Mech Marketplace VIII (5k OLAS)", gnosis)

    def test_shim_excludes_mm_v1_defunct(self):
        """MM v1 defunct marketplace contracts must not appear in shim.

        The contracts themselves may be ACTIVE/DEPLETED/FULL on-chain,
        but their marketplace (mech 975) was retired so triton can't use them.
        """
        gnosis = OLAS_TRADER_STAKING_CONTRACTS.get("gnosis", {})
        for name in gnosis:
            matches = [
                c for c in STAKING_CONTRACTS
                if c.name == name and c.chain == "gnosis"
            ]
            if matches:
                self.assertNotEqual(
                    matches[0].marketplace,
                    MarketplaceType.MM_V1_DEFUNCT,
                    f"{name} uses defunct MM v1 marketplace "
                    f"but appears in compat shim",
                )

    def test_shim_only_agent_25(self):
        """Compat shim should only contain trader-agent contracts."""
        for _chain, contracts in OLAS_TRADER_STAKING_CONTRACTS.items():
            for name, addr in contracts.items():
                matches = [
                    c for c in STAKING_CONTRACTS
                    if str(c.address).lower() == str(addr).lower()
                ]
                if matches:
                    self.assertEqual(
                        matches[0].agent_id,
                        AgentType.TRADER,
                        f"{name}: agent_id={matches[0].agent_id}, "
                        "expected AgentType.TRADER",
                    )
