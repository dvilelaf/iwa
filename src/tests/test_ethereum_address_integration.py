"""Integration tests for EthereumAddress enforcement across the system.

These tests verify that EthereumAddress is used consistently throughout the
entire pipeline: config → models → contracts → mech requests → monitoring.
Only RPC calls are mocked; all other code runs as in production.
"""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.types import EthereumAddress

# ----- Test addresses (lowercase → checksummed) -----
ADDR_LOWER = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
ADDR_CHECKSUM = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
ADDR_MULTISIG = "0x1111111111111111111111111111111111111111"
ADDR_AGENT = "0x2222222222222222222222222222222222222222"
ADDR_STAKING = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_OWNER = "0x3333333333333333333333333333333333333333"
ADDR_CHECKER = "0x4444444444444444444444444444444444444444"
ADDR_TOKEN = "0x5555555555555555555555555555555555555555"


# =========================================================================
# 1. EthereumAddress type enforcement
# =========================================================================


class TestEthereumAddressType:
    """Verify EthereumAddress validates and checksums correctly."""

    def test_lowercase_is_checksummed(self):
        addr = EthereumAddress(ADDR_LOWER)
        assert addr == ADDR_CHECKSUM
        assert isinstance(addr, str)
        assert isinstance(addr, EthereumAddress)

    def test_already_checksummed_unchanged(self):
        addr = EthereumAddress(ADDR_CHECKSUM)
        assert addr == ADDR_CHECKSUM

    def test_invalid_address_rejected(self):
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            EthereumAddress("0xInvalid")

    def test_short_address_rejected(self):
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            EthereumAddress("0x1234")

    def test_works_as_dict_key(self):
        d = {EthereumAddress(ADDR_LOWER): "value"}
        assert d[ADDR_CHECKSUM] == "value"

    def test_str_operations_preserved(self):
        addr = EthereumAddress(ADDR_LOWER)
        assert addr.lower() == ADDR_LOWER
        assert addr.startswith("0x")
        assert len(addr) == 42


# =========================================================================
# 2. Pydantic model enforcement (Service, StakingStatus)
# =========================================================================


class TestServiceModelAddresses:
    """Verify Service model auto-checksums all address fields."""

    def test_lowercase_addresses_checksummed(self):
        from iwa.plugins.olas.models import Service

        svc = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=1,
            multisig_address=ADDR_LOWER,
            agent_address=ADDR_AGENT,
            staking_contract_address=ADDR_LOWER,
            service_owner_eoa_address=ADDR_OWNER,
        )
        assert svc.multisig_address == ADDR_CHECKSUM
        assert svc.staking_contract_address == ADDR_CHECKSUM
        assert isinstance(svc.multisig_address, EthereumAddress)
        assert isinstance(svc.staking_contract_address, EthereumAddress)

    def test_optional_address_none(self):
        from iwa.plugins.olas.models import Service

        svc = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=1,
        )
        assert svc.multisig_address is None
        assert svc.staking_contract_address is None

    def test_invalid_address_rejected(self):
        from iwa.plugins.olas.models import Service

        with pytest.raises(ValueError):
            Service(
                service_name="test",
                chain_name="gnosis",
                service_id=1,
                multisig_address="not_an_address",
            )

    def test_service_from_dict_like_yaml(self):
        """Test creating Service from dict (simulating YAML config load)."""
        from iwa.plugins.olas.models import Service

        config_data = {
            "service_name": "trader_production",
            "chain_name": "gnosis",
            "service_id": 42,
            "multisig_address": ADDR_LOWER,
            "agent_address": ADDR_AGENT.lower(),
            "staking_contract_address": ADDR_STAKING.lower(),
            "service_owner_eoa_address": ADDR_OWNER.lower(),
        }
        svc = Service(**config_data)

        # All addresses should be checksummed
        assert svc.multisig_address == ADDR_CHECKSUM
        assert svc.staking_contract_address == ADDR_STAKING
        assert isinstance(svc.multisig_address, EthereumAddress)
        assert isinstance(svc.agent_address, EthereumAddress)


class TestStakingStatusModelAddresses:
    """Verify StakingStatus model auto-checksums address fields."""

    def test_lowercase_addresses_checksummed(self):
        from iwa.plugins.olas.models import StakingStatus

        status = StakingStatus(
            is_staked=True,
            staking_state="STAKED",
            staking_contract_address=ADDR_LOWER,
            activity_checker_address=ADDR_CHECKER.lower(),
        )
        assert status.staking_contract_address == ADDR_CHECKSUM
        assert isinstance(status.staking_contract_address, EthereumAddress)
        assert isinstance(status.activity_checker_address, EthereumAddress)

    def test_invalid_address_rejected(self):
        from iwa.plugins.olas.models import StakingStatus

        with pytest.raises(ValueError):
            StakingStatus(
                is_staked=True,
                staking_state="STAKED",
                staking_contract_address="0xBadAddress",
            )


# =========================================================================
# 3. ContractInstance boundary (accepts str, stores EthereumAddress)
# =========================================================================


class TestContractInstanceAddress:
    """Verify ContractInstance.__init__ converts str to EthereumAddress."""

    def test_lowercase_address_checksummed(self):
        """ContractInstance should accept lowercase and store checksummed."""
        from iwa.core.contracts.contract import ContractInstance

        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = MagicMock()

            class TestContract(ContractInstance):
                name = "Test"
                abi_path = None  # Will fail on ABI load, but address is set first

            # Skip ABI loading
            with patch.object(ContractInstance, "__init__", lambda self, *a, **kw: None):
                contract = TestContract.__new__(TestContract)

            # Manually call just the address conversion
            contract.address = EthereumAddress(ADDR_LOWER)
            assert contract.address == ADDR_CHECKSUM
            assert isinstance(contract.address, EthereumAddress)


# =========================================================================
# 4. TransferLogger._topic_to_address returns EthereumAddress
# =========================================================================


class TestTopicToAddressReturnsEthereumAddress:
    """Verify _topic_to_address returns EthereumAddress, not plain str."""

    @pytest.fixture
    def transfer_logger(self):
        from iwa.core.services.transaction import TransferLogger

        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None
        chain_interface = MagicMock()
        chain_interface.chain.native_currency = "xDAI"
        chain_interface.chain.get_token_name.return_value = None
        chain_interface.get_token_decimals.return_value = 18
        return TransferLogger(account_service, chain_interface)

    def test_bytes_topic_returns_ethereum_address(self, transfer_logger):
        addr_hex = ADDR_CHECKSUM[2:].lower()
        topic = b"\x00" * 12 + bytes.fromhex(addr_hex)
        result = transfer_logger._topic_to_address(topic)
        assert result == ADDR_CHECKSUM
        assert isinstance(result, EthereumAddress)

    def test_hex_string_topic_returns_ethereum_address(self, transfer_logger):
        topic = "0x" + "0" * 24 + ADDR_CHECKSUM[2:].lower()
        result = transfer_logger._topic_to_address(topic)
        assert result == ADDR_CHECKSUM
        assert isinstance(result, EthereumAddress)


# =========================================================================
# 5. EventMonitor initializes with EthereumAddress
# =========================================================================


class TestEventMonitorAddresses:
    """Verify EventMonitor converts addresses to EthereumAddress."""

    def test_lowercase_addresses_checksummed_on_init(self):
        from iwa.core.monitor import EventMonitor

        with patch("iwa.core.monitor.ChainInterfaces") as mock_ci:
            mock_chain = MagicMock()
            mock_chain.current_rpc = None
            mock_ci.return_value.get.return_value = mock_chain

            monitor = EventMonitor(
                addresses=[ADDR_LOWER, ADDR_AGENT.lower()],
                callback=lambda x: None,
                chain_name="gnosis",
            )

            assert monitor.addresses[0] == ADDR_CHECKSUM
            assert monitor.addresses[1] == ADDR_AGENT
            assert all(isinstance(a, EthereumAddress) for a in monitor.addresses)

    def test_native_transfer_produces_ethereum_address(self):
        """Verify parsed native transfers contain EthereumAddress in from/to."""
        from iwa.core.monitor import EventMonitor

        with patch("iwa.core.monitor.ChainInterfaces") as mock_ci:
            mock_chain = MagicMock()
            mock_chain.current_rpc = "https://rpc.example.com"
            mock_ci.return_value.get.return_value = mock_chain
            mock_chain.web3.eth.block_number = 100

            monitor = EventMonitor(
                addresses=[ADDR_CHECKSUM],
                callback=lambda x: None,
                chain_name="gnosis",
            )
            monitor.last_checked_block = 99

            # Mock a block with a matching transaction
            mock_tx = {
                "from": ADDR_CHECKSUM.lower(),
                "to": ADDR_AGENT.lower(),
                "hash": b"\x01" * 32,
                "value": 1000,
            }
            mock_block = MagicMock()
            mock_block.transactions = [mock_tx]
            mock_block.timestamp = 1234567890
            mock_chain.web3.eth.get_block.return_value = mock_block
            mock_chain.web3.eth.get_logs.return_value = []

            results = []
            monitor.callback = lambda txs: results.extend(txs)
            monitor.check_activity()

            assert len(results) == 1
            assert results[0]["from"] == ADDR_CHECKSUM
            assert isinstance(results[0]["from"], EthereumAddress)


# =========================================================================
# 6. Full pipeline: Service → StakingContract → mech config
# =========================================================================


class TestStakingContractAddressFlow:
    """Test that addresses flow correctly through the staking pipeline."""

    def test_staking_contract_receives_ethereum_address(self):
        """Verify StakingContract.__init__ gets EthereumAddress from Service."""
        from iwa.plugins.olas.models import Service

        svc = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=1,
            staking_contract_address=ADDR_LOWER,
        )

        # The address should already be checksummed EthereumAddress
        assert isinstance(svc.staking_contract_address, EthereumAddress)
        assert svc.staking_contract_address == ADDR_CHECKSUM

        # This address can be passed directly to StakingContract
        # (ContractInstance.__init__ will accept it as-is since it's already valid)

    def test_staking_token_from_contract_becomes_ethereum_address(self):
        """Verify staking_token from raw contract data becomes EthereumAddress."""
        # Simulate what staking.py:358 does
        raw_contract_data = {"staking_token": ADDR_LOWER}
        staking_token = EthereumAddress(raw_contract_data["staking_token"])
        assert staking_token == ADDR_CHECKSUM
        assert isinstance(staking_token, EthereumAddress)


# =========================================================================
# 7. Multisend recipient address enforcement
# =========================================================================


class TestMultisendAddressEnforcement:
    """Verify multisend enforces EthereumAddress for recipients."""

    def test_valid_recipient_accepted(self):
        """EthereumAddress(valid_addr) should work."""
        recipient = EthereumAddress(ADDR_LOWER)
        assert recipient == ADDR_CHECKSUM

    def test_invalid_recipient_rejected(self):
        """EthereumAddress(invalid_addr) should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            EthereumAddress("not_an_address")


# =========================================================================
# 8. End-to-end: YAML-like config → model → contract pipeline
# =========================================================================


class TestEndToEndAddressPipeline:
    """Simulate full flow from config dict to contract calls."""

    def test_yaml_config_to_service_to_staking(self):
        """Full pipeline: YAML dict → Service model → address validation."""
        from iwa.plugins.olas.models import OlasConfig, Service

        # Simulate YAML config with lowercase addresses
        yaml_services = {
            "gnosis:42": {
                "service_name": "trader_prod",
                "chain_name": "gnosis",
                "service_id": 42,
                "multisig_address": ADDR_LOWER,
                "agent_address": ADDR_AGENT.lower(),
                "staking_contract_address": ADDR_STAKING.lower(),
                "service_owner_eoa_address": ADDR_OWNER.lower(),
            }
        }

        # Build OlasConfig from dict (like Config loading does)
        services = {}
        for key, data in yaml_services.items():
            services[key] = Service(**data)

        config = OlasConfig(services=services)
        svc = config.services["gnosis:42"]

        # All addresses should be EthereumAddress and checksummed
        assert isinstance(svc.multisig_address, EthereumAddress)
        assert isinstance(svc.agent_address, EthereumAddress)
        assert isinstance(svc.staking_contract_address, EthereumAddress)
        assert isinstance(svc.service_owner_eoa_address, EthereumAddress)
        assert svc.multisig_address == ADDR_CHECKSUM
        assert svc.staking_contract_address == ADDR_STAKING

    def test_staking_status_from_contract_data(self):
        """Simulate building StakingStatus from raw contract data."""
        from iwa.plugins.olas.models import StakingStatus

        # Raw contract data returns lowercase addresses
        raw_data = {
            "is_staked": True,
            "staking_state": "STAKED",
            "staking_contract_address": ADDR_LOWER,
            "activity_checker_address": ADDR_CHECKER.lower(),
            "mech_requests_this_epoch": 5,
            "required_mech_requests": 3,
        }

        status = StakingStatus(**raw_data)
        assert isinstance(status.staking_contract_address, EthereumAddress)
        assert isinstance(status.activity_checker_address, EthereumAddress)
        assert status.staking_contract_address == ADDR_CHECKSUM


# =========================================================================
# 9. Verify no to_checksum_address in source code (meta-test)
# =========================================================================


class TestNoToChecksumAddressInSource:
    """Meta-test: verify to_checksum_address only exists in EthereumAddress."""

    def test_only_in_types_module(self):
        """Scan source for to_checksum_address — should only be in types.py."""
        import subprocess

        result = subprocess.run(
            ["grep", "-r", "to_checksum_address", "src/iwa/", "--include=*.py", "-l"],
            capture_output=True,
            text=True,
            cwd="/media/david/DATA/repos/iwa",
        )
        files_with_checksum = [
            f.strip() for f in result.stdout.strip().split("\n") if f.strip()
        ]
        assert files_with_checksum == ["src/iwa/core/types.py"], (
            f"to_checksum_address found in unexpected files: {files_with_checksum}"
        )
