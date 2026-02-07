"""Tests for TransferService.multi_send."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.models import StoredSafeAccount
from iwa.core.services.transfer import TransferService

# Valid Ethereum addresses for testing
ADDR_FROM = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
ADDR_TO_1 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_TO_2 = "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
ADDR_TOKEN = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
ADDR_MULTISEND = "0x1111111111111111111111111111111111111111"
ADDR_MULTISEND_CO = "0x2222222222222222222222222222222222222222"
ADDR_RECIPIENT = "0x3333333333333333333333333333333333333333"
ADDR_SAFE = "0x4444444444444444444444444444444444444444"


@pytest.fixture
def mock_deps():
    """Mock dependencies for TransferService."""
    with (
        patch("iwa.core.services.transfer.base.ChainInterfaces") as mock_chain,
        patch("iwa.core.services.transfer.multisend.ChainInterfaces", new=mock_chain),
        patch("iwa.core.services.transfer.swap.ChainInterfaces", new=mock_chain),
        patch("iwa.core.services.transfer.multisend.MultiSendContract") as mock_ms,
        patch("iwa.core.services.transfer.multisend.MultiSendCallOnlyContract") as mock_ms_co,
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.swap.ERC20Contract", new=mock_erc20),
        patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20),
    ):
        mock_account_service = MagicMock()
        mock_key_storage = MagicMock()
        mock_balance_service = MagicMock()
        mock_safe_service = MagicMock()
        mock_txn_service = MagicMock()
        # Set default return for sign_and_send
        mock_txn_service.sign_and_send.return_value = (True, {})

        # Setup Chain Interface
        mock_w3 = MagicMock()
        mock_w3.to_wei.return_value = 1000  # 1000 wei default
        mock_chain.return_value.get.return_value.web3 = mock_w3
        mock_chain.return_value.get.return_value.chain.name = "gnosis"
        mock_chain.return_value.get.return_value.chain.tokens = {"TEST": ADDR_TOKEN}
        mock_erc20.return_value.allowance_wei.return_value = 0

        deps = {
            "account_service": mock_account_service,
            "key_storage": mock_key_storage,
            "balance_service": mock_balance_service,
            "safe_service": mock_safe_service,
            "transaction_service": mock_txn_service,
            "contracts": {"ms": mock_ms, "ms_co": mock_ms_co, "erc20": mock_erc20},
        }
        yield deps


def test_multi_send_eoa_native(mock_deps):
    """Test multi_send with EOA and native transfers."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    # Mock From Account (EOA)
    mock_from = MagicMock()
    mock_from.address = ADDR_FROM
    mock_from.tag = "from_tag"

    def resolve_side_effect(arg):
        if arg == "from_tag":
            return mock_from
        return None

    service.account_service.resolve_account.side_effect = resolve_side_effect

    # Mock dependencies
    mock_ms_co = mock_deps["contracts"]["ms_co"].return_value
    mock_ms_co.prepare_tx.return_value = {"value": 0, "data": b"encoded"}
    mock_ms_co.address = ADDR_MULTISEND_CO

    transactions = [
        {
            "to": ADDR_TO_1,
            "amount": 1.0,
            "token": NATIVE_CURRENCY_ADDRESS,
        },
        {"to": ADDR_TO_2, "amount_wei": 500, "token": NATIVE_CURRENCY_ADDRESS},
    ]

    service.multi_send("from_tag", transactions)

    # Verify Account Resolution
    # mock_deps["account_service"].resolve_account.assert_called() # Side effect makes called_with tricky

    # Verify Contract Interaction
    mock_deps["contracts"]["ms_co"].assert_called()
    mock_ms_co.prepare_tx.assert_called()

    # Verify Transaction Service called
    mock_deps["transaction_service"].sign_and_send.assert_called()


def test_multi_send_safe_erc20(mock_deps):
    """Test multi_send with Safe and ERC20 transfers."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    # Mock From Account (Safe)
    mock_safe_account = MagicMock(spec=StoredSafeAccount)
    mock_safe_account.address = ADDR_SAFE

    service.account_service.resolve_account.side_effect = (
        lambda x: mock_safe_account if x == "safe_tag" else None
    )

    # Mock ERC20
    mock_erc20 = mock_deps["contracts"]["erc20"].return_value
    mock_erc20.decimals = 18
    mock_erc20.prepare_transfer_tx.return_value = {"data": b"transfer_data"}
    mock_erc20.address = ADDR_TOKEN

    mock_deps["account_service"].get_token_address.return_value = ADDR_TOKEN

    # Mock MultiSend Normal (for Safe)
    mock_ms = mock_deps["contracts"]["ms"].return_value
    mock_ms.prepare_tx.return_value = {"value": 0, "data": b"multisend_data"}
    mock_ms.address = ADDR_MULTISEND

    transactions = [{"to": ADDR_RECIPIENT, "amount": 10.0, "token": "TEST"}]

    service.multi_send("safe_tag", transactions)

    # Verify ERC20 prep (Safe uses transfer, not transferFrom)
    mock_erc20.prepare_transfer_tx.assert_called()

    # Verify Safe Service execution
    mock_deps["safe_service"].execute_safe_transaction.assert_called()


def test_multi_send_eoa_erc20_approval(mock_deps):
    """Test multi_send with EOA checks for allowances."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    # Stub approve_erc20 to verify it's called
    service.approve_erc20 = MagicMock()

    # Mock From Account (EOA)
    mock_from = MagicMock()
    mock_from.address = ADDR_FROM
    del mock_from.threshold  # EOA has no threshold
    service.account_service.resolve_account.side_effect = (
        lambda x: mock_from if x == "from_tag" else None
    )

    mock_deps["account_service"].get_token_address.return_value = ADDR_TOKEN
    mock_erc20 = mock_deps["contracts"]["erc20"].return_value
    mock_erc20.decimals = 18
    mock_erc20.prepare_transfer_from_tx.return_value = {"data": b"transferFrom"}

    mock_ms_co = mock_deps["contracts"]["ms_co"].return_value
    mock_ms_co.prepare_tx.return_value = {"value": 0, "data": b"encoded"}

    transactions = [{"to": ADDR_RECIPIENT, "amount": 10.0, "token": "TEST"}]

    service.multi_send("from_tag", transactions)

    # Verify Approval logic was triggered
    service.approve_erc20.assert_called_once()
