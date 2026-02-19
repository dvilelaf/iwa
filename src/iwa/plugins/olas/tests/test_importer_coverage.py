"""Additional tests for Olas service importer to reach 90%+ coverage.

Targets uncovered lines identified by coverage analysis.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account

from iwa.plugins.olas.importer import (
    STAKING_PROGRAM_MAP,
    DiscoveredKey,
    DiscoveredService,
    ImportResult,
    OlasServiceImporter,
)

# Valid 42-char hex Ethereum addresses
ADDR_AGENT = "0x1111111111111111111111111111111111111111"
ADDR_OWNER = "0x2222222222222222222222222222222222222222"
ADDR_SAFE = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_SAFE_2 = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
ADDR_OWNER_SAFE = "0x3333333333333333333333333333333333333333"


@pytest.fixture
def importer():
    """Create OlasServiceImporter with mocked KeyStorage and Config."""
    with patch("iwa.plugins.olas.importer.KeyStorage") as mock_ks_cls:
        ks = mock_ks_cls.return_value
        ks.accounts = {}
        ks._password = "test_password"
        ks.find_stored_account.return_value = None
        with patch("iwa.plugins.olas.importer.Config") as mock_cfg_cls:
            cfg = mock_cfg_cls.return_value
            cfg.plugins = {}
            return OlasServiceImporter(ks)


@pytest.fixture
def importer_with_password():
    """Create OlasServiceImporter with password for decryption tests."""
    with patch("iwa.plugins.olas.importer.KeyStorage") as mock_ks_cls:
        ks = mock_ks_cls.return_value
        ks.accounts = {}
        ks._password = "test_password"
        ks.find_stored_account.return_value = None
        with patch("iwa.plugins.olas.importer.Config") as mock_cfg_cls:
            cfg = mock_cfg_cls.return_value
            cfg.plugins = {}
            return OlasServiceImporter(ks, password="test_pass")


# =============================================================================
# DiscoveredService property tests (lines 92, 98-99, 105, 110-113)
# =============================================================================


class TestDiscoveredServiceProperties:
    """Test DiscoveredService computed properties."""

    def test_service_owner_address_multisig_preferred(self):
        """service_owner_address returns multisig when both set."""
        svc = DiscoveredService(
            service_owner_multisig_address=ADDR_SAFE,
            service_owner_eoa_address=ADDR_OWNER,
        )
        assert svc.service_owner_address == ADDR_SAFE

    def test_service_owner_address_eoa_fallback(self):
        """service_owner_address returns eoa when no multisig."""
        svc = DiscoveredService(service_owner_eoa_address=ADDR_OWNER)
        assert svc.service_owner_address == ADDR_OWNER

    def test_service_owner_address_none(self):
        """service_owner_address returns None when neither set."""
        svc = DiscoveredService()
        assert svc.service_owner_address is None

    def test_agent_key_found(self):
        """agent_key returns the key with role='agent'."""
        agent = DiscoveredKey(address=ADDR_AGENT, role="agent")
        owner = DiscoveredKey(address=ADDR_OWNER, role="owner")
        svc = DiscoveredService(keys=[owner, agent])
        assert svc.agent_key is agent

    def test_agent_key_not_found(self):
        """agent_key returns None when no agent key."""
        owner = DiscoveredKey(address=ADDR_OWNER, role="owner")
        svc = DiscoveredService(keys=[owner])
        assert svc.agent_key is None

    def test_operator_key_delegates_to_owner_key(self):
        """operator_key is an alias for owner_key."""
        owner = DiscoveredKey(address=ADDR_OWNER, role="owner")
        svc = DiscoveredService(keys=[owner])
        assert svc.operator_key is owner

    def test_owner_key_matches_operator_role(self):
        """owner_key also matches role='operator'."""
        op = DiscoveredKey(address=ADDR_OWNER, role="operator")
        svc = DiscoveredService(keys=[op])
        assert svc.owner_key is op

    def test_owner_key_not_found(self):
        """owner_key returns None when no owner/operator key."""
        agent = DiscoveredKey(address=ADDR_AGENT, role="agent")
        svc = DiscoveredService(keys=[agent])
        assert svc.owner_key is None


# =============================================================================
# scan_directory - non-existent path (lines 156-157)
# =============================================================================


class TestScanDirectory:
    """Test scan_directory edge cases."""

    def test_scan_nonexistent_path(self, importer):
        """scan_directory returns empty list for non-existent path."""
        result = importer.scan_directory(Path("/nonexistent/path/12345"))
        assert result == []


# =============================================================================
# _deduplicate_services (lines 185-187, 192)
# =============================================================================


class TestDeduplicateServices:
    """Test service deduplication."""

    def test_dedup_removes_duplicates(self, importer):
        """Duplicate services by chain:service_id are removed."""
        svc1 = DiscoveredService(
            service_id=1, chain_name="gnosis", source_folder=Path("/a")
        )
        svc2 = DiscoveredService(
            service_id=1, chain_name="gnosis", source_folder=Path("/b")
        )
        svc3 = DiscoveredService(
            service_id=2, chain_name="gnosis", source_folder=Path("/c")
        )
        result = importer._deduplicate_services([svc1, svc2, svc3])
        assert len(result) == 2
        assert result[0].source_folder == Path("/a")
        assert result[1].source_folder == Path("/c")

    def test_dedup_no_service_id_kept(self, importer):
        """Services without service_id are never deduplicated."""
        svc1 = DiscoveredService(service_id=None, source_folder=Path("/a"))
        svc2 = DiscoveredService(service_id=None, source_folder=Path("/b"))
        result = importer._deduplicate_services([svc1, svc2])
        assert len(result) == 2


# =============================================================================
# _find_trader_name (line 211)
# =============================================================================


class TestFindTraderName:
    """Test trader name resolution from directory hierarchy."""

    def test_finds_trader_prefix_parent(self, importer, tmp_path):
        """Finds trader_* folder in parent hierarchy."""
        trader_dir = tmp_path / "trader_alpha" / "quickstart"
        trader_dir.mkdir(parents=True)
        assert importer._find_trader_name(trader_dir) == "trader_alpha"

    def test_no_trader_prefix_uses_fallback(self, importer, tmp_path):
        """Falls back to folder name when no trader_* found."""
        some_dir = tmp_path / "myservice" / "subdir"
        some_dir.mkdir(parents=True)
        assert importer._find_trader_name(some_dir) == "subdir"


# =============================================================================
# _parse_trader_runner_format - empty data returns None (lines 246-247)
# =============================================================================


class TestParseTraderRunnerFormat:
    """Test trader_runner format parsing edge cases."""

    def test_empty_folder_returns_none(self, importer, tmp_path):
        """Folder with no valid data returns None."""
        runner_dir = tmp_path / ".trader_runner"
        runner_dir.mkdir()
        # No files at all => no keys, no service_id
        result = importer._parse_trader_runner_format(runner_dir)
        assert result is None


# =============================================================================
# _extract_safe_address - invalid address (lines 268-269)
# =============================================================================


class TestExtractSafeAddress:
    """Test Safe address extraction edge cases."""

    def test_invalid_safe_address(self, importer, tmp_path):
        """Invalid address in file logs warning and returns None."""
        folder = tmp_path / ".trader_runner"
        folder.mkdir()
        (folder / "service_safe_address.txt").write_text("not-an-address")
        result = importer._extract_safe_address(folder)
        assert result is None


# =============================================================================
# _extract_trader_keys - keys.json with dedup (lines 293-298)
# =============================================================================


class TestExtractTraderKeys:
    """Test trader key extraction with dedup logic."""

    def test_keys_json_dedup(self, importer, tmp_path):
        """keys.json entries that duplicate agent_pkey are skipped."""
        folder = tmp_path / ".trader_runner"
        folder.mkdir()

        # agent_pkey.txt
        keystore = {
            "address": "1111111111111111111111111111111111111111",
            "crypto": {"cipher": "aes-128-ctr"},
        }
        (folder / "agent_pkey.txt").write_text(json.dumps(keystore))

        # keys.json with same address (should be deduped) + new address
        keys_json = [
            {
                "address": "1111111111111111111111111111111111111111",
                "crypto": {"cipher": "aes"},
            },
            {
                "address": "2222222222222222222222222222222222222222",
                "crypto": {"cipher": "aes"},
            },
        ]
        (folder / "keys.json").write_text(json.dumps(keys_json))

        keys = importer._extract_trader_keys(folder)
        # agent_pkey + one non-duplicate from keys.json
        assert len(keys) == 2
        addrs = [k.address.lower() for k in keys]
        assert "0x1111111111111111111111111111111111111111" in addrs
        assert "0x2222222222222222222222222222222222222222" in addrs


# =============================================================================
# _extract_staking_from_env (lines 311-324)
# =============================================================================


class TestExtractStakingFromEnv:
    """Test .env staking program extraction."""

    def test_env_in_parent_folder(self, importer, tmp_path):
        """Reads STAKING_PROGRAM from parent .env."""
        runner_dir = tmp_path / "trader" / ".trader_runner"
        runner_dir.mkdir(parents=True)
        env_file = tmp_path / "trader" / ".env"
        env_file.write_text('STAKING_PROGRAM=pearl_alpha\nOTHER=value\n')

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_staking_from_env(svc, runner_dir)
        assert svc.staking_contract_address is not None

    def test_env_inside_folder(self, importer, tmp_path):
        """Reads STAKING_PROGRAM from .env inside the folder."""
        runner_dir = tmp_path / ".trader_runner"
        runner_dir.mkdir()
        env_file = runner_dir / ".env"
        env_file.write_text('STAKING_PROGRAM="pearl_beta"\n')

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_staking_from_env(svc, runner_dir)
        assert svc.staking_contract_address is not None

    def test_env_with_unknown_program(self, importer, tmp_path):
        """Unknown staking program ID results in None."""
        runner_dir = tmp_path / "trader" / ".trader_runner"
        runner_dir.mkdir(parents=True)
        env_file = tmp_path / "trader" / ".env"
        env_file.write_text("STAKING_PROGRAM=unknown_program_xyz\n")

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_staking_from_env(svc, runner_dir)
        assert svc.staking_contract_address is None

    def test_env_empty_program(self, importer, tmp_path):
        """Empty STAKING_PROGRAM value is ignored."""
        runner_dir = tmp_path / "trader" / ".trader_runner"
        runner_dir.mkdir(parents=True)
        env_file = tmp_path / "trader" / ".env"
        env_file.write_text("STAKING_PROGRAM=\n")

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_staking_from_env(svc, runner_dir)
        assert svc.staking_contract_address is None


# =============================================================================
# _discover_standalone_wallet edge cases (lines 392-393, 397)
# =============================================================================


class TestDiscoverStandaloneWallet:
    """Test standalone wallet discovery."""

    def test_invalid_ethereum_json(self, importer, tmp_path):
        """Invalid ethereum.json doesn't crash."""
        wallets = tmp_path / "wallets"
        wallets.mkdir()
        (wallets / "ethereum.txt").write_text(
            json.dumps({"address": ADDR_OWNER, "private_key": "ab" * 32})
        )
        (wallets / "ethereum.json").write_text("not valid json")

        result = importer._discover_standalone_wallet(tmp_path)
        assert result is not None
        # Safe address should not be set due to invalid JSON
        assert result.safe_address is None

    def test_no_keys_returns_none(self, importer, tmp_path):
        """Wallet folder with no parseable keys returns None."""
        wallets = tmp_path / "wallets"
        wallets.mkdir()
        # ethereum.txt with unparseable content
        (wallets / "ethereum.txt").write_text("random garbage")

        result = importer._discover_standalone_wallet(tmp_path)
        assert result is None


# =============================================================================
# _parse_operate_service_config - invalid JSON (lines 403-405)
# =============================================================================


class TestParseOperateServiceConfig:
    """Test operate service config parsing."""

    def test_invalid_json_config(self, importer, tmp_path):
        """Invalid JSON in config.json returns None."""
        config_file = tmp_path / "services" / "uuid" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("not valid json {{{")

        result = importer._parse_operate_service_config(config_file)
        assert result is None


# =============================================================================
# _enrich_service_with_chain_info - invalid multisig, staking (lines 480-482, 488)
# =============================================================================


class TestEnrichServiceWithChainInfo:
    """Test chain info enrichment."""

    def test_invalid_multisig_address(self, importer):
        """Invalid multisig address sets safe_address to None."""
        svc = DiscoveredService()
        data = {
            "chain_configs": {
                "gnosis": {
                    "chain_data": {
                        "token": 42,
                        "multisig": "invalid-address",
                    }
                }
            }
        }
        importer._enrich_service_with_chain_info(svc, data)
        assert svc.service_id == 42
        assert svc.safe_address is None

    def test_staking_program_in_user_params(self, importer):
        """Staking program from user_params is resolved."""
        svc = DiscoveredService()
        data = {
            "chain_configs": {
                "gnosis": {
                    "chain_data": {
                        "token": 42,
                        "multisig": ADDR_SAFE,
                        "user_params": {"staking_program_id": "pearl_alpha"},
                    }
                }
            }
        }
        importer._enrich_service_with_chain_info(svc, data)
        assert svc.staking_contract_address is not None
        expected = STAKING_PROGRAM_MAP["pearl_alpha"]
        assert str(svc.staking_contract_address).lower() == expected.lower()


# =============================================================================
# _resolve_staking_contract (lines 496-502)
# =============================================================================


class TestResolveStakingContract:
    """Test staking contract resolution."""

    def test_known_program(self, importer):
        """Known staking program returns address."""
        result = importer._resolve_staking_contract("pearl_alpha", "gnosis")
        assert result is not None

    def test_unknown_program(self, importer):
        """Unknown staking program returns None."""
        result = importer._resolve_staking_contract("nonexistent_program_xyz", "gnosis")
        assert result is None


# =============================================================================
# _extract_parent_wallet_keys - plaintext fails, fallback to keystore (lines 509-518)
# =============================================================================


class TestExtractParentWalletKeys:
    """Test parent wallet key extraction."""

    def test_fallback_to_keystore(self, importer, tmp_path):
        """When plaintext parsing fails, falls back to keystore parsing."""
        operate_dir = tmp_path / ".operate"
        operate_dir.mkdir()
        wallets = operate_dir / "wallets"
        wallets.mkdir()

        # Write a keystore-format file (not plaintext JSON with private_key)
        keystore = {
            "address": "1111111111111111111111111111111111111111",
            "crypto": {"cipher": "aes-128-ctr"},
        }
        (wallets / "ethereum.txt").write_text(json.dumps(keystore))

        keys = importer._extract_parent_wallet_keys(operate_dir)
        assert len(keys) == 1
        assert keys[0].role == "owner"
        assert keys[0].is_encrypted is True

    def test_no_wallets_folder(self, importer, tmp_path):
        """No wallets folder returns empty list."""
        operate_dir = tmp_path / ".operate"
        operate_dir.mkdir()
        keys = importer._extract_parent_wallet_keys(operate_dir)
        assert keys == []

    def test_no_ethereum_txt(self, importer, tmp_path):
        """Wallets folder without ethereum.txt returns empty list."""
        operate_dir = tmp_path / ".operate"
        operate_dir.mkdir()
        wallets = operate_dir / "wallets"
        wallets.mkdir()
        keys = importer._extract_parent_wallet_keys(operate_dir)
        assert keys == []


# =============================================================================
# _extract_owner_address (lines 544-594)
# =============================================================================


class TestExtractOwnerAddress:
    """Test owner address extraction from ethereum.json."""

    def test_safe_owner_case(self, importer, tmp_path):
        """Extracts Safe owner and EOA signer."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)

        eth_json = {
            "address": ADDR_OWNER,
            "safes": {"gnosis": ADDR_OWNER_SAFE},
        }
        (wallets / "ethereum.json").write_text(json.dumps(eth_json))

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_owner_address(svc, operate_dir)
        assert str(svc.service_owner_multisig_address) == ADDR_OWNER_SAFE
        assert str(svc.service_owner_eoa_address) == ADDR_OWNER

    def test_eoa_owner_case(self, importer, tmp_path):
        """Extracts EOA owner when no safes field."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)

        eth_json = {"address": ADDR_OWNER}
        (wallets / "ethereum.json").write_text(json.dumps(eth_json))

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_owner_address(svc, operate_dir)
        assert str(svc.service_owner_eoa_address) == ADDR_OWNER
        assert svc.service_owner_multisig_address is None

    def test_invalid_safe_owner_address(self, importer, tmp_path):
        """Invalid Safe owner address logs warning."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)

        eth_json = {
            "address": ADDR_OWNER,
            "safes": {"gnosis": "not-valid"},
        }
        (wallets / "ethereum.json").write_text(json.dumps(eth_json))

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_owner_address(svc, operate_dir)
        # Invalid safe address should not be set
        assert svc.service_owner_multisig_address is None

    def test_invalid_eoa_in_safe_case(self, importer, tmp_path):
        """Invalid EOA address in safe owner case logs warning."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)

        eth_json = {
            "address": "bad-eoa",
            "safes": {"gnosis": ADDR_OWNER_SAFE},
        }
        (wallets / "ethereum.json").write_text(json.dumps(eth_json))

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_owner_address(svc, operate_dir)
        assert str(svc.service_owner_multisig_address) == ADDR_OWNER_SAFE
        assert svc.service_owner_eoa_address is None

    def test_invalid_eoa_only(self, importer, tmp_path):
        """Invalid EOA address with no safe logs warning."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)

        eth_json = {"address": "bad-eoa"}
        (wallets / "ethereum.json").write_text(json.dumps(eth_json))

        svc = DiscoveredService(chain_name="gnosis")
        importer._extract_owner_address(svc, operate_dir)
        assert svc.service_owner_eoa_address is None

    def test_no_wallets_folder(self, importer, tmp_path):
        """No wallets folder is a no-op."""
        operate_dir = tmp_path / ".operate"
        operate_dir.mkdir()
        svc = DiscoveredService()
        importer._extract_owner_address(svc, operate_dir)
        assert svc.service_owner_eoa_address is None

    def test_invalid_json_in_ethereum_json(self, importer, tmp_path):
        """Invalid JSON in ethereum.json is handled gracefully."""
        operate_dir = tmp_path / ".operate"
        wallets = operate_dir / "wallets"
        wallets.mkdir(parents=True)
        (wallets / "ethereum.json").write_text("not json {{")

        svc = DiscoveredService()
        importer._extract_owner_address(svc, operate_dir)
        assert svc.service_owner_eoa_address is None


# =============================================================================
# _infer_owner_address (lines 607, 613-615)
# =============================================================================


class TestInferOwnerAddress:
    """Test owner address inference from keys."""

    def test_already_set_skips(self, importer):
        """Does not overwrite existing owner address."""
        svc = DiscoveredService(
            service_owner_eoa_address=ADDR_OWNER,
            keys=[DiscoveredKey(address=ADDR_AGENT, role="owner")],
        )
        importer._infer_owner_address(svc)
        assert str(svc.service_owner_eoa_address) == ADDR_OWNER

    def test_infers_from_owner_key(self, importer):
        """Infers owner address from key with role='owner'."""
        svc = DiscoveredService(
            keys=[DiscoveredKey(address=ADDR_OWNER, role="owner")]
        )
        importer._infer_owner_address(svc)
        assert str(svc.service_owner_eoa_address) == ADDR_OWNER

    def test_invalid_owner_key_address(self, importer):
        """Invalid owner key address is skipped."""
        svc = DiscoveredService(
            keys=[DiscoveredKey(address="bad-address", role="owner")]
        )
        importer._infer_owner_address(svc)
        assert svc.service_owner_eoa_address is None


# =============================================================================
# _parse_keystore_file - nested keystore, decryption (lines 629-634, 638, 654-661)
# =============================================================================


class TestParseKeystoreFile:
    """Test keystore file parsing edge cases."""

    def test_nested_keystore_in_private_key(self, importer, tmp_path):
        """Handles operate format with keystore stringified inside private_key."""
        inner = {
            "address": "1111111111111111111111111111111111111111",
            "crypto": {"cipher": "aes"},
        }
        outer = {"private_key": json.dumps(inner)}
        f = tmp_path / "nested.json"
        f.write_text(json.dumps(outer))

        key = importer._parse_keystore_file(f, role="agent")
        assert key is not None
        assert key.address == "0x1111111111111111111111111111111111111111"

    def test_nested_private_key_not_keystore(self, importer, tmp_path):
        """private_key field that is not a nested keystore falls through."""
        outer = {
            "private_key": "just a hex string, not json",
            "address": "1111111111111111111111111111111111111111",
            "crypto": {"cipher": "aes"},
        }
        f = tmp_path / "not_nested.json"
        f.write_text(json.dumps(outer))

        key = importer._parse_keystore_file(f, role="agent")
        assert key is not None

    def test_missing_crypto_returns_none(self, importer, tmp_path):
        """File without 'crypto' key returns None."""
        f = tmp_path / "no_crypto.json"
        f.write_text(json.dumps({"address": "0x1", "version": 3}))

        key = importer._parse_keystore_file(f, role="agent")
        assert key is None

    def test_io_error_returns_none(self, importer, tmp_path):
        """Non-existent file returns None."""
        f = tmp_path / "nonexistent.json"
        key = importer._parse_keystore_file(f, role="agent")
        assert key is None

    def test_password_decryption_attempt(self, importer_with_password, tmp_path):
        """When password provided, attempts decryption."""
        # Create a real encrypted keystore
        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "test_pass")
        f = tmp_path / "encrypted.json"
        f.write_text(json.dumps(keystore))

        key = importer_with_password._parse_keystore_file(f, role="agent")
        assert key is not None
        assert key.private_key == private_key
        assert key.is_encrypted is False

    def test_password_decryption_wrong_password(self, tmp_path):
        """Wrong password fails decryption gracefully."""
        with patch("iwa.plugins.olas.importer.KeyStorage") as mock_ks_cls:
            ks = mock_ks_cls.return_value
            ks.accounts = {}
            with patch("iwa.plugins.olas.importer.Config"):
                imp = OlasServiceImporter(ks, password="wrong_password")

        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "correct_password")
        f = tmp_path / "encrypted.json"
        f.write_text(json.dumps(keystore))

        key = imp._parse_keystore_file(f, role="agent")
        assert key is not None
        # Decryption failed, key is still encrypted
        assert key.private_key is None
        assert key.is_encrypted is True


# =============================================================================
# _parse_keys_json edge cases (lines 668, 675, 685-687, 690-691)
# =============================================================================


class TestParseKeysJson:
    """Test keys.json parsing edge cases."""

    def test_non_list_content(self, importer, tmp_path):
        """Non-list JSON returns empty list."""
        f = tmp_path / "keys.json"
        f.write_text(json.dumps({"not": "a list"}))
        assert importer._parse_keys_json(f) == []

    def test_address_without_0x(self, importer, tmp_path):
        """Address without 0x prefix gets it prepended."""
        f = tmp_path / "keys.json"
        f.write_text(
            json.dumps(
                [
                    {
                        "address": "1111111111111111111111111111111111111111",
                        "crypto": {"cipher": "aes"},
                    }
                ]
            )
        )
        keys = importer._parse_keys_json(f)
        assert len(keys) == 1
        assert keys[0].address.startswith("0x")

    def test_with_password_decryption(self, tmp_path):
        """When password provided, attempts decryption for keys.json entries."""
        with patch("iwa.plugins.olas.importer.KeyStorage") as mock_ks_cls:
            ks = mock_ks_cls.return_value
            ks.accounts = {}
            with patch("iwa.plugins.olas.importer.Config"):
                imp = OlasServiceImporter(ks, password="test_pass")

        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "test_pass")
        f = tmp_path / "keys.json"
        f.write_text(json.dumps([keystore]))

        keys = imp._parse_keys_json(f)
        assert len(keys) == 1
        assert keys[0].private_key == private_key

    def test_io_error(self, importer, tmp_path):
        """IOError returns empty list."""
        f = tmp_path / "nonexistent_keys.json"
        assert importer._parse_keys_json(f) == []


# =============================================================================
# decrypt_key edge cases (lines 747, 758-760)
# =============================================================================


class TestDecryptKey:
    """Test key decryption edge cases."""

    def test_already_decrypted(self, importer):
        """Already decrypted key returns True immediately."""
        key = DiscoveredKey(address=ADDR_AGENT, private_key="abc123")
        assert importer.decrypt_key(key, "any_pass") is True

    def test_wrong_password(self, importer):
        """Wrong password returns False."""
        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "correct")
        key = DiscoveredKey(
            address=ADDR_AGENT, encrypted_keystore=keystore, is_encrypted=True
        )
        assert importer.decrypt_key(key, "wrong") is False


# =============================================================================
# _import_discovered_keys - duplicate and error branches (lines 794-798)
# =============================================================================


class TestImportDiscoveredKeys:
    """Test _import_discovered_keys branches."""

    def test_duplicate_key_skipped(self, importer):
        """Duplicate key is added to skipped list."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(
            service_name="test",
            keys=[DiscoveredKey(address=ADDR_AGENT, private_key="abc", role="agent")],
        )
        with patch.object(importer, "_import_key", return_value=(False, "duplicate")):
            importer._import_discovered_keys(svc, None, result)
        assert len(result.skipped) == 1
        assert "already exists" in result.skipped[0]

    def test_error_key_reported(self, importer):
        """Failed key import is added to errors list."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(
            service_name="test",
            keys=[DiscoveredKey(address=ADDR_AGENT, private_key="abc", role="agent")],
        )
        with patch.object(
            importer, "_import_key", return_value=(False, "encryption failed")
        ):
            importer._import_discovered_keys(svc, None, result)
        assert len(result.errors) == 1
        assert result.success is False


# =============================================================================
# _import_discovered_safes - duplicate, error, owner safe (lines 812-815, 823-833)
# =============================================================================


class TestImportDiscoveredSafes:
    """Test _import_discovered_safes branches."""

    def test_duplicate_safe_skipped(self, importer):
        """Duplicate safe is added to skipped list."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(
            service_name="test",
            safe_address=ADDR_SAFE,
            keys=[DiscoveredKey(address=ADDR_AGENT, role="agent")],
        )
        with patch.object(importer, "_import_safe", return_value=(False, "duplicate")):
            importer._import_discovered_safes(svc, result)
        assert len(result.skipped) == 1
        assert "already exists" in result.skipped[0]

    def test_error_safe_reported(self, importer):
        """Failed safe import is added to errors list."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(
            service_name="test",
            safe_address=ADDR_SAFE,
            keys=[DiscoveredKey(address=ADDR_AGENT, role="agent")],
        )
        with patch.object(
            importer, "_import_safe", return_value=(False, "some error")
        ):
            importer._import_discovered_safes(svc, result)
        assert len(result.errors) == 1

    def test_owner_safe_imported(self, importer):
        """Owner multisig safe is imported when different from agent safe."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(
            service_name="test",
            safe_address=ADDR_SAFE,
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            keys=[
                DiscoveredKey(address=ADDR_AGENT, role="agent"),
                DiscoveredKey(address=ADDR_OWNER, role="owner"),
            ],
        )
        with patch.object(importer, "_import_safe", return_value=(True, "ok")):
            importer._import_discovered_safes(svc, result)
        # Both agent safe and owner safe imported
        assert len(result.imported_safes) == 2


# =============================================================================
# _get_agent_signers / _get_owner_signers (lines 842, 848-856)
# =============================================================================


class TestGetSigners:
    """Test signer extraction methods."""

    def test_agent_signers_with_0x(self, importer):
        """Agent signer address already has 0x prefix."""
        svc = DiscoveredService(
            keys=[DiscoveredKey(address=ADDR_AGENT, role="agent")]
        )
        signers = importer._get_agent_signers(svc)
        assert signers == [ADDR_AGENT]

    def test_agent_signers_without_0x(self, importer):
        """Agent signer address without 0x gets prefix added."""
        svc = DiscoveredService(
            keys=[
                DiscoveredKey(
                    address="1111111111111111111111111111111111111111",
                    role="agent",
                )
            ]
        )
        signers = importer._get_agent_signers(svc)
        assert signers == ["0x1111111111111111111111111111111111111111"]

    def test_owner_signers(self, importer):
        """Owner signers extracts owner/operator keys."""
        svc = DiscoveredService(
            keys=[
                DiscoveredKey(address=ADDR_OWNER, role="owner"),
                DiscoveredKey(address=ADDR_AGENT, role="agent"),
                DiscoveredKey(address=ADDR_SAFE_2, role="operator"),
            ]
        )
        signers = importer._get_owner_signers(svc)
        assert len(signers) == 2
        assert ADDR_OWNER in signers
        assert ADDR_SAFE_2 in signers

    def test_owner_signers_without_0x(self, importer):
        """Owner signer address without 0x gets prefix added."""
        svc = DiscoveredService(
            keys=[
                DiscoveredKey(
                    address="2222222222222222222222222222222222222222",
                    role="owner",
                )
            ]
        )
        signers = importer._get_owner_signers(svc)
        assert signers == ["0x2222222222222222222222222222222222222222"]


# =============================================================================
# _import_key - decryption failed, encrypt exception (lines 908-909, 924-925)
# =============================================================================


class TestImportKeyEdgeCases:
    """Test _import_key edge cases."""

    def test_decryption_failed(self, importer):
        """Failed decryption returns appropriate error."""
        key = DiscoveredKey(
            address=ADDR_AGENT,
            private_key=None,
            encrypted_keystore={"crypto": {}},
            is_encrypted=True,
        )
        importer.key_storage.find_stored_account.return_value = None

        with patch.object(importer, "decrypt_key", return_value=False):
            success, msg = importer._import_key(key, "svc", password="wrong")
        assert success is False
        assert msg == "decryption failed"

    def test_encrypt_exception(self, importer):
        """Exception during re-encryption is caught."""
        key = DiscoveredKey(
            address=ADDR_AGENT,
            private_key="ab" * 32,
            role="agent",
            is_encrypted=False,
        )
        importer.key_storage.find_stored_account.return_value = None

        with patch(
            "iwa.plugins.olas.importer.EncryptedAccount.encrypt_private_key",
            side_effect=Exception("boom"),
        ):
            success, msg = importer._import_key(key, "svc")
        assert success is False
        assert "boom" in msg


# =============================================================================
# _generate_tag - owner/operator _eoa suffix (line 946)
# =============================================================================


class TestGenerateTag:
    """Test tag generation."""

    def test_owner_gets_eoa_suffix(self, importer):
        """Owner key gets _eoa suffix."""
        key = DiscoveredKey(address=ADDR_OWNER, role="owner")
        importer.key_storage.accounts = {}
        tag = importer._generate_tag(key, "trader_alpha")
        assert tag == "trader_alpha_owner_eoa"

    def test_operator_gets_eoa_suffix(self, importer):
        """Operator key gets _eoa suffix."""
        key = DiscoveredKey(address=ADDR_OWNER, role="operator")
        importer.key_storage.accounts = {}
        tag = importer._generate_tag(key, "trader_alpha")
        assert tag == "trader_alpha_operator_eoa"

    def test_no_service_name_uses_imported(self, importer):
        """None service_name uses 'imported' as prefix."""
        key = DiscoveredKey(address=ADDR_AGENT, role="agent")
        importer.key_storage.accounts = {}
        tag = importer._generate_tag(key, None)
        assert tag == "imported_agent"


# =============================================================================
# _import_safe - no address, tag collision (lines 973, 991-992)
# =============================================================================


class TestImportSafeEdgeCases:
    """Test _import_safe edge cases."""

    def test_no_address(self, importer):
        """Empty address returns error."""
        success, msg = importer._import_safe(address="")
        assert success is False
        assert msg == "no safe address"

    def test_tag_collision(self, importer):
        """Duplicate tag gets numeric suffix."""
        importer.key_storage.find_stored_account.return_value = None
        importer.key_storage.accounts = {
            "0x1": MagicMock(tag="test_multisig"),
            "0x2": MagicMock(tag="test_multisig_2"),
        }

        success, msg = importer._import_safe(
            address=ADDR_SAFE, service_name="test", tag_suffix="multisig"
        )
        assert success is True
        # Verify the tag used was test_multisig_3
        call_args = importer.key_storage.register_account.call_args
        assert call_args[0][0].tag == "test_multisig_3"


# =============================================================================
# _import_service_config edge cases (lines 1014, 1039, 1047)
# =============================================================================


class TestImportServiceConfig:
    """Test _import_service_config edge cases."""

    def test_creates_olas_config_if_missing(self, importer):
        """Creates OlasConfig if not in plugins."""
        svc = DiscoveredService(
            service_id=42,
            chain_name="gnosis",
            safe_address=ADDR_SAFE,
            service_name="new_svc",
            keys=[DiscoveredKey(address=ADDR_AGENT, role="agent", private_key="abc")],
        )
        # Ensure "olas" is not in plugins
        importer.config.plugins = {}

        success, msg = importer._import_service_config(svc)
        assert success is True
        assert msg == "ok"

    def test_import_error_returns_not_available(self, importer):
        """ImportError returns appropriate message."""
        svc = DiscoveredService(service_id=42, chain_name="gnosis")
        with patch(
            "iwa.plugins.olas.importer.OlasServiceImporter._import_service_config"
        ) as mock:
            mock.return_value = (False, "Olas plugin not available")
            success, msg = mock(svc)
        assert success is False
        assert "not available" in msg


# =============================================================================
# _attempt_decryption (lines 1053-1069)
# =============================================================================


class TestAttemptDecryption:
    """Test _attempt_decryption method."""

    def test_no_password_noop(self, importer):
        """No password set is a no-op."""
        key = DiscoveredKey(
            address=ADDR_AGENT,
            encrypted_keystore={"crypto": {}},
            is_encrypted=True,
        )
        importer.password = None
        importer._attempt_decryption(key)
        assert key.private_key is None

    def test_no_keystore_noop(self, importer):
        """No encrypted_keystore is a no-op."""
        key = DiscoveredKey(address=ADDR_AGENT, is_encrypted=True)
        importer.password = "test"
        importer._attempt_decryption(key)
        assert key.private_key is None

    def test_successful_decryption(self, importer):
        """Successful decryption sets private_key."""
        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "test_pass")
        key = DiscoveredKey(
            address=ADDR_AGENT,
            encrypted_keystore=keystore,
            is_encrypted=True,
        )
        importer.password = "test_pass"
        importer._attempt_decryption(key)
        assert key.private_key == private_key
        assert key.is_encrypted is False

    def test_wrong_password_value_error(self, importer):
        """Wrong password triggers ValueError, key stays encrypted."""
        private_key = "ab" * 32
        keystore = Account.encrypt("0x" + private_key, "correct")
        key = DiscoveredKey(
            address=ADDR_AGENT,
            encrypted_keystore=keystore,
            is_encrypted=True,
        )
        importer.password = "wrong"
        importer._attempt_decryption(key)
        assert key.private_key is None
        assert key.is_encrypted is True

    def test_generic_exception(self, importer):
        """Generic exception during decryption is handled."""
        key = DiscoveredKey(
            address=ADDR_AGENT,
            encrypted_keystore={"bad": "format"},
            is_encrypted=True,
        )
        importer.password = "test"
        # Should not raise
        importer._attempt_decryption(key)
        assert key.private_key is None


# =============================================================================
# _verify_key_signature (lines 1074, 1089)
# =============================================================================


class TestVerifyKeySignature:
    """Test key signature verification."""

    def test_no_private_key_noop(self, importer):
        """No private key is a no-op."""
        key = DiscoveredKey(address=ADDR_AGENT)
        importer._verify_key_signature(key)
        assert key.signature_verified is False
        assert key.signature_failed is False

    def test_no_address_noop(self, importer):
        """No address is a no-op."""
        key = DiscoveredKey(address="", private_key="abc")
        importer._verify_key_signature(key)
        assert key.signature_verified is False

    def test_valid_signature(self, importer):
        """Valid key passes signature verification."""
        private_key = "ab" * 32
        account = Account.from_key(bytes.fromhex(private_key))
        key = DiscoveredKey(
            address=account.address,
            private_key=private_key,
        )
        importer._verify_key_signature(key)
        assert key.signature_verified is True
        assert key.signature_failed is False

    def test_mismatched_signature(self, importer):
        """Wrong address fails signature verification."""
        private_key = "ab" * 32
        key = DiscoveredKey(
            address=ADDR_AGENT,  # Does not match private key
            private_key=private_key,
        )
        importer._verify_key_signature(key)
        assert key.signature_failed is True
        assert key.signature_verified is False

    def test_invalid_private_key_exception(self, importer):
        """Invalid private key triggers exception."""
        key = DiscoveredKey(
            address=ADDR_AGENT,
            private_key="not-hex-at-all",
        )
        importer._verify_key_signature(key)
        assert key.signature_failed is True

    def test_address_without_0x_in_verification(self, importer):
        """Address without 0x prefix is normalized during verification."""
        private_key = "ab" * 32
        account = Account.from_key(bytes.fromhex(private_key))
        # Strip 0x from address
        addr_without_prefix = account.address[2:]
        key = DiscoveredKey(
            address=addr_without_prefix,
            private_key=private_key,
        )
        importer._verify_key_signature(key)
        assert key.signature_verified is True


# =============================================================================
# _build_import_summary (all branches)
# =============================================================================


class TestBuildImportSummary:
    """Test import summary building."""

    def test_all_parts(self, importer):
        """Summary with keys, safes, and services."""
        result = ImportResult(
            success=True,
            message="",
            imported_keys=[ADDR_AGENT],
            imported_safes=[ADDR_SAFE],
            imported_services=["gnosis:1"],
        )
        importer._build_import_summary(result)
        assert "1 key(s)" in result.message
        assert "1 safe(s)" in result.message
        assert "1 service(s)" in result.message

    def test_nothing_imported(self, importer):
        """Summary when nothing imported."""
        result = ImportResult(success=True, message="")
        importer._build_import_summary(result)
        assert result.message == "Nothing imported"


# =============================================================================
# _import_discovered_service_config branches (lines 862-873)
# =============================================================================


class TestImportDiscoveredServiceConfig:
    """Test _import_discovered_service_config branches."""

    def test_duplicate_service_skipped(self, importer):
        """Duplicate service is added to skipped."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(service_id=1, chain_name="gnosis")
        with patch.object(
            importer, "_import_service_config", return_value=(False, "duplicate")
        ):
            importer._import_discovered_service_config(svc, result)
        assert len(result.skipped) == 1
        assert "already exists" in result.skipped[0]

    def test_error_service_reported(self, importer):
        """Failed service config import is added to errors."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(service_id=1, chain_name="gnosis")
        with patch.object(
            importer, "_import_service_config", return_value=(False, "some error")
        ):
            importer._import_discovered_service_config(svc, result)
        assert len(result.errors) == 1

    def test_no_service_id_skips(self, importer):
        """No service_id means no config import attempted."""
        result = ImportResult(success=True, message="")
        svc = DiscoveredService(service_id=None)
        with patch.object(importer, "_import_service_config") as mock:
            importer._import_discovered_service_config(svc, result)
            mock.assert_not_called()


# =============================================================================
# _extract_external_keys_folder (lines 521-531)
# =============================================================================


class TestExtractExternalKeysFolder:
    """Test external keys folder extraction."""

    def test_keys_folder_with_files(self, importer, tmp_path):
        """Parses key files starting with 0x in keys folder."""
        operate_dir = tmp_path / ".operate"
        keys_dir = operate_dir / "keys"
        keys_dir.mkdir(parents=True)

        keystore = {
            "address": "1111111111111111111111111111111111111111",
            "crypto": {"cipher": "aes"},
        }
        (keys_dir / "0x1111111111111111111111111111111111111111").write_text(
            json.dumps(keystore)
        )
        # Non-0x file should be ignored
        (keys_dir / "readme.txt").write_text("ignore me")

        keys = importer._extract_external_keys_folder(operate_dir)
        assert len(keys) == 1
        assert keys[0].role == "agent"

    def test_no_keys_folder(self, importer, tmp_path):
        """No keys folder returns empty list."""
        operate_dir = tmp_path / ".operate"
        operate_dir.mkdir()
        keys = importer._extract_external_keys_folder(operate_dir)
        assert keys == []


# =============================================================================
# DiscoveredKey.is_decrypted property
# =============================================================================


class TestDiscoveredKeyProperties:
    """Test DiscoveredKey properties."""

    def test_is_decrypted_true(self):
        """Key with private_key is decrypted."""
        key = DiscoveredKey(address=ADDR_AGENT, private_key="abc")
        assert key.is_decrypted is True

    def test_is_decrypted_false(self):
        """Key without private_key is not decrypted."""
        key = DiscoveredKey(address=ADDR_AGENT)
        assert key.is_decrypted is False


# =============================================================================
# _merge_unique_keys
# =============================================================================


class TestMergeUniqueKeys:
    """Test key merging deduplication."""

    def test_merge_skips_duplicates(self, importer):
        """Duplicate keys by address are not added."""
        svc = DiscoveredService(
            keys=[DiscoveredKey(address=ADDR_AGENT, role="agent")]
        )
        new_keys = [
            DiscoveredKey(address=ADDR_AGENT, role="agent"),  # duplicate
            DiscoveredKey(address=ADDR_OWNER, role="owner"),  # new
        ]
        importer._merge_unique_keys(svc, new_keys)
        assert len(svc.keys) == 2

    def test_merge_empty(self, importer):
        """Merging empty list does nothing."""
        svc = DiscoveredService(keys=[DiscoveredKey(address=ADDR_AGENT, role="agent")])
        importer._merge_unique_keys(svc, [])
        assert len(svc.keys) == 1


# =============================================================================
# _parse_plaintext_key_file - JSON decode error branch (lines 713-714)
# =============================================================================


class TestParsePlaintextKeyFile:
    """Test _parse_plaintext_key_file edge cases."""

    def test_json_decode_error_falls_through(self, importer, tmp_path):
        """Non-JSON content that doesn't match hex format returns None."""
        f = tmp_path / "bad.txt"
        f.write_text("not json and not 64 hex chars")
        result = importer._parse_plaintext_key_file(f, role="agent")
        assert result is None

    def test_hex_with_0x_prefix(self, importer, tmp_path):
        """0x-prefixed 66-char hex is parsed."""
        private_key = "ab" * 32
        f = tmp_path / "key.txt"
        f.write_text("0x" + private_key)
        result = importer._parse_plaintext_key_file(f, role="agent")
        assert result is not None
        assert result.private_key == private_key
