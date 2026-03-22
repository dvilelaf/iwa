"""Tests for SafeService gaps: thresholds, ProxyFactory, gas estimation, _log_safe_deployment."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.models import StoredSafeAccount
from iwa.core.services.safe import SafeService


@pytest.fixture
def mock_key_storage():
    """Mock key storage."""
    mock = MagicMock(spec=KeyStorage)
    mock.accounts = {}

    def find_account(tag_or_addr):
        if tag_or_addr == "deployer":
            acc = MagicMock(spec=EncryptedAccount)
            acc.address = "0xAB7C8803962c0f2F5BBBe3FA8BF0Dcd705084223"
            return acc
        if tag_or_addr in ("owner1", "owner2", "owner3"):
            acc = MagicMock(spec=EncryptedAccount)
            acc.address = f"0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4{'a' if tag_or_addr == 'owner1' else 'b' if tag_or_addr == 'owner2' else 'c'}"
            return acc
        return None

    mock.find_stored_account.side_effect = find_account
    mock._get_private_key.return_value = "0x" + "12" * 32
    return mock


@pytest.fixture
def mock_account_service():
    """Mock account service."""
    mock = MagicMock()
    mock.get_tag_by_address.return_value = "deployer_tag"
    return mock


@pytest.fixture
def mock_deps():
    """Mock external dependencies for Safe operations."""
    with (
        patch("iwa.core.services.safe.EthereumClient") as mock_client,
        patch("iwa.plugins.gnosis.safe.get_ethereum_client") as mock_get_client,
        patch("iwa.core.services.safe.Safe") as mock_safe,
        patch("iwa.core.services.safe.ProxyFactory") as mock_proxy_factory,
        patch("iwa.core.services.safe.log_transaction") as mock_log,
        patch("iwa.core.services.safe.get_safe_master_copy_address") as mock_master,
        patch("iwa.core.services.safe.get_safe_proxy_factory_address") as mock_factory,
        patch("time.sleep"),
    ):
        mock_get_client.return_value = mock_client.return_value

        mock_create_tx = MagicMock()
        mock_create_tx.contract_address = "0xbEC49fa140ACaa83533f900357DCD37866d50618"
        mock_create_tx.tx_hash.hex.return_value = "TxHash"

        mock_safe.create.return_value = mock_create_tx

        mock_deploy_tx = MagicMock()
        mock_deploy_tx.contract_address = "0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5"
        mock_deploy_tx.tx_hash.hex.return_value = "TxHashSalted"

        mock_proxy_factory.return_value.deploy_proxy_contract_with_nonce.return_value = mock_deploy_tx

        mock_function = MagicMock()
        mock_function.build_transaction.return_value = {"data": "0x1234"}
        mock_contract = MagicMock()
        mock_contract.functions.setup.return_value = mock_function
        mock_safe_instance = MagicMock()
        mock_safe_instance.contract = mock_contract

        def safe_side_effect(*args, **kwargs):
            return mock_safe_instance

        mock_safe.side_effect = safe_side_effect
        mock_safe.create.return_value = mock_create_tx

        mock_client.return_value.w3.eth.get_transaction_receipt.return_value = {
            "gasUsed": 50000,
            "effectiveGasPrice": 20,
        }
        mock_client.return_value.w3.eth.gas_price = 1000

        yield {
            "client": mock_client,
            "safe": mock_safe,
            "proxy_factory": mock_proxy_factory,
            "log": mock_log,
            "master": mock_master,
            "factory": mock_factory,
        }


# ---- Threshold tests ----


class TestCreateSafeThresholds:
    def test_create_safe_threshold_1(self, mock_key_storage, mock_account_service, mock_deps):
        """Create safe with threshold=1 (single signer)."""
        service = SafeService(mock_key_storage, mock_account_service)
        safe_account, tx_hash = service.create_safe(
            "deployer", ["owner1"], threshold=1, chain_name="gnosis", tag="Safe1of1"
        )
        assert safe_account.threshold == 1
        assert safe_account.tag == "Safe1of1"

    def test_create_safe_threshold_2_of_3(self, mock_key_storage, mock_account_service, mock_deps):
        """Create safe with threshold=2 out of 3 owners."""
        service = SafeService(mock_key_storage, mock_account_service)
        safe_account, tx_hash = service.create_safe(
            "deployer",
            ["owner1", "owner2", "owner3"],
            threshold=2,
            chain_name="gnosis",
            tag="Safe2of3",
        )
        assert safe_account.threshold == 2
        assert len(safe_account.signers) == 3


# ---- ProxyFactory path tests ----


class TestDeploySafeContract:
    def test_standard_deployment_uses_safe_create(self, mock_key_storage, mock_account_service, mock_deps):
        """Standard deployment (no salt) uses Safe.create."""
        service = SafeService(mock_key_storage, mock_account_service)
        service.create_safe("deployer", ["owner1"], 1, "gnosis", tag="StdSafe")
        mock_deps["safe"].create.assert_called_once()

    def test_salted_deployment_uses_proxy_factory(self, mock_key_storage, mock_account_service, mock_deps):
        """Salted deployment uses ProxyFactory."""
        service = SafeService(mock_key_storage, mock_account_service)
        service.create_safe("deployer", ["owner1"], 1, "gnosis", tag="SaltedSafe", salt_nonce=42)
        mock_deps["proxy_factory"].return_value.deploy_proxy_contract_with_nonce.assert_called_once()
        mock_deps["safe"].create.assert_not_called()


# ---- Gas estimation / _log_safe_deployment tests ----


class TestLogSafeDeployment:
    def test_log_deployment_with_receipt(self, mock_key_storage, mock_account_service, mock_deps):
        """Deployment logs transaction with gas info from receipt."""
        service = SafeService(mock_key_storage, mock_account_service)
        service.create_safe("deployer", ["owner1"], 1, "gnosis", tag="TestSafe")

        mock_deps["log"].assert_called_once()
        call_kwargs = mock_deps["log"].call_args.kwargs
        assert call_kwargs["tags"] == ["safe-deployment"]
        assert call_kwargs["amount_wei"] == 0

    def test_log_deployment_receipt_failure_still_logs(
        self, mock_key_storage, mock_account_service, mock_deps
    ):
        """When receipt fails, deployment is still logged with None gas."""
        mock_deps["client"].return_value.w3.eth.get_transaction_receipt.side_effect = Exception("RPC error")

        service = SafeService(mock_key_storage, mock_account_service)
        service.create_safe("deployer", ["owner1"], 1, "gnosis", tag="NoReceipt")

        mock_deps["log"].assert_called_once()
        call_kwargs = mock_deps["log"].call_args.kwargs
        # Gas should be None since receipt failed
        assert call_kwargs["gas_cost"] is None


# ---- Error cases ----


class TestSafeErrors:
    def test_resolve_owner_not_found_raises(self, mock_key_storage, mock_account_service, mock_deps):
        """Resolving non-existent owner raises ValueError."""
        service = SafeService(mock_key_storage, mock_account_service)
        with pytest.raises(ValueError, match="Owner account .* not found"):
            service.create_safe("deployer", ["nonexistent"], 1, "gnosis")

    def test_deployer_is_safe_raises(self, mock_key_storage, mock_account_service, mock_deps):
        """Using a Safe account as deployer raises ValueError."""

        def find_account(tag_or_addr):
            if tag_or_addr == "my_safe":
                acc = MagicMock(spec=StoredSafeAccount)
                acc.address = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
                return acc
            return None

        mock_key_storage.find_stored_account.side_effect = find_account
        service = SafeService(mock_key_storage, mock_account_service)

        with pytest.raises(ValueError, match="Deployer account .* not found"):
            service.create_safe("my_safe", ["owner1"], 1, "gnosis")

    def test_get_signer_keys_insufficient_threshold(self, mock_key_storage, mock_account_service):
        """_get_signer_keys raises when not enough keys for threshold."""
        service = SafeService(mock_key_storage, mock_account_service)

        safe_account = MagicMock(spec=StoredSafeAccount)
        safe_account.signers = ["0xAddr1", "0xAddr2"]
        safe_account.threshold = 3  # Needs 3, but only 2 signers exist

        mock_key_storage._get_private_key.return_value = "0x" + "ab" * 32

        with pytest.raises(ValueError, match="Not enough signer private keys"):
            service._get_signer_keys(safe_account)
