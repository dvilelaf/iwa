"""Tests for the staking contract catalog and query function."""

import unittest

from iwa.plugins.olas.constants import (
    OLAS_TRADER_STAKING_CONTRACTS,
    STAKING_CONTRACTS,
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
        known = {"gnosis", "base", "ethereum"}
        for c in STAKING_CONTRACTS:
            self.assertIn(c.chain, known, f"{c.name}: unknown chain {c.chain}")


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
        traders = get_staking_contracts(agent_id=25)
        self.assertGreater(len(traders), 20)
        for c in traders:
            self.assertEqual(c.agent_id, 25)

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
            agent_id=25,
            marketplace=[MarketplaceType.LEGACY, MarketplaceType.MM_V2],
            status=ContractStatus.ACTIVE,
        )
        self.assertGreater(len(result), 10)
        for c in result:
            self.assertEqual(c.chain, "gnosis")
            self.assertEqual(c.agent_id, 25)
            self.assertIn(
                c.marketplace,
                {MarketplaceType.LEGACY, MarketplaceType.MM_V2},
            )
            self.assertEqual(c.status, ContractStatus.ACTIVE)

    def test_supply_contracts_exist(self):
        supply = get_staking_contracts(marketplace=MarketplaceType.SUPPLY)
        self.assertGreater(len(supply), 0)
        for c in supply:
            self.assertIsNone(c.agent_id)

    def test_base_contracts_exist(self):
        base = get_staking_contracts(chain="base")
        self.assertGreater(len(base), 2)


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
        """Compat shim should only contain agent_id=25 contracts."""
        for _chain, contracts in OLAS_TRADER_STAKING_CONTRACTS.items():
            for name, addr in contracts.items():
                matches = [
                    c for c in STAKING_CONTRACTS
                    if str(c.address).lower() == str(addr).lower()
                ]
                if matches:
                    self.assertEqual(
                        matches[0].agent_id,
                        25,
                        f"{name}: agent_id={matches[0].agent_id}, "
                        f"expected 25",
                    )
