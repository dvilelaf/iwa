"""Tests for core SafeService."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.services.safe import SafeService


@pytest.fixture
def mock_key_storage():
    """Mock key storage."""
    mock = MagicMock(spec=KeyStorage)
    mock.accounts = {}

    # Mock find_stored_account to return appropriate account types
    def find_account(tag_or_addr):
        if tag_or_addr == "deployer":
            acc = MagicMock(spec=EncryptedAccount)
            # Valid checksum address - Deployer
            acc.address = "0xAB7C8803962c0f2F5BBBe3FA8BF0Dcd705084223"
            return acc
        if tag_or_addr == "owner1":
            acc = MagicMock(spec=EncryptedAccount)
            # Valid checksum address - Owner
            acc.address = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
            return acc
        return None

    mock.find_stored_account.side_effect = find_account

    # Mock private key retrieval
    mock._get_private_key.return_value = (
        "0x1234567890123456789012345678901234567890123456789012345678901234"
    )

    return mock


@pytest.fixture
def mock_account_service():
    """Mock account service."""
    mock = MagicMock()
    mock.get_tag_by_address.return_value = "deployer_tag"
    return mock


@pytest.fixture
def mock_dependencies():
    """Mock external dependencies (Safe, EthereumClient, etc)."""
    with (
        patch("iwa.core.services.safe.EthereumClient") as mock_client,
        patch("iwa.core.services.safe.Safe") as mock_safe,
        patch("iwa.core.services.safe.ProxyFactory") as mock_proxy_factory,
        patch("iwa.core.services.safe.settings") as mock_settings,
        patch("iwa.core.services.safe.log_transaction") as mock_log,
        patch("iwa.core.services.safe.get_safe_master_copy_address") as mock_master,
        patch("iwa.core.services.safe.get_safe_proxy_factory_address") as mock_factory,
    ):
        mock_settings.gnosis_rpc.get_secret_value.return_value = "http://rpc"

        # Setup Safe creation return
        mock_create_tx = MagicMock()
        # Valid Checksum Address - New Safe (Matches Pydantic output)
        mock_create_tx.contract_address = "0xbEC49fa140ACaa83533f900357DCD37866d50618"
        mock_create_tx.tx_hash.hex.return_value = "0xTxHash"

        mock_safe.create.return_value = mock_create_tx

        # Setup ProxyFactory return
        mock_deploy_tx = MagicMock()
        # Valid checksum address - Salted Safe
        mock_deploy_tx.contract_address = "0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5"
        mock_deploy_tx.tx_hash.hex.return_value = "0xTxHashSalted"

        mock_proxy_factory.return_value.deploy_proxy_contract_with_nonce.return_value = (
            mock_deploy_tx
        )

        # Fix for setup_data chaining
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

        # Mock get_transaction_receipt for gas calc
        mock_client.return_value.w3.eth.get_transaction_receipt.return_value = {
            "gasUsed": 50000,
            "effectiveGasPrice": 20,
        }

        yield {
            "client": mock_client,
            "safe": mock_safe,
            "proxy_factory": mock_proxy_factory,
            "settings": mock_settings,
            "log": mock_log,
            "master": mock_master,
            "factory": mock_factory,
        }


def test_create_safe_standard(mock_key_storage, mock_account_service, mock_dependencies):
    """Test standard create_safe without salt."""
    service = SafeService(mock_key_storage, mock_account_service)

    safe_account, tx_hash = service.create_safe(
        deployer_tag_or_address="deployer",
        owner_tags_or_addresses=["owner1"],
        threshold=1,
        chain_name="gnosis",
        tag="MySafe",
    )

    # Checksum address matching what Pydantic/Web3 produces
    assert safe_account.address == "0xbEC49fa140ACaa83533f900357DCD37866d50618"
    assert safe_account.tag == "MySafe"
    assert tx_hash == "0xTxHash"

    mock_dependencies["safe"].create.assert_called_once()
    mock_key_storage.save.assert_called_once()


def test_create_safe_with_salt(mock_key_storage, mock_account_service, mock_dependencies):
    """Test create_safe with salt nonce."""
    service = SafeService(mock_key_storage, mock_account_service)

    mock_dependencies["client"].return_value.w3.eth.gas_price = 1000

    safe_account, tx_hash = service.create_safe(
        deployer_tag_or_address="deployer",
        owner_tags_or_addresses=["owner1"],
        threshold=1,
        chain_name="gnosis",
        tag="MySaltedSafe",
        salt_nonce=123,
    )

    # 0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5
    assert safe_account.address == "0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5"
    assert tx_hash == "0xTxHashSalted"

    # Check that manual ProxyFactory logic was used
    mock_dependencies[
        "proxy_factory"
    ].return_value.deploy_proxy_contract_with_nonce.assert_called_once()
    # Safe.create should NOT be called
    mock_dependencies["safe"].create.assert_not_called()


def test_create_safe_invalid_deployer(mock_key_storage, mock_account_service):
    """Test error when deployer invalid."""
    mock_key_storage.find_stored_account.return_value = None
    service = SafeService(mock_key_storage, mock_account_service)

    with pytest.raises(ValueError, match="Deployer account .* not found"):
        service.create_safe("invalid", [], 1, "gnosis")
