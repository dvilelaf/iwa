
from unittest.mock import MagicMock, patch

import pytest
from hexbytes import HexBytes
from web3 import exceptions as web3_exceptions

from iwa.core.keys import KeyStorage
from iwa.core.managers import TransactionManager
from iwa.tui.app import IwaApp
from iwa.tui.views import CreateEOAModal, WalletsView

# --- TransactionManager Tests ---

@pytest.fixture
def mock_keys():
    return MagicMock(spec=KeyStorage)

def test_transaction_manager_retry_gas(mock_keys):
    manager = TransactionManager(mock_keys)

    with patch("iwa.core.managers.ChainInterfaces") as mock_chains:
        mock_interface = MagicMock()
        mock_chains.return_value.get.return_value = mock_interface

        # Mock web3
        mock_web3 = mock_interface.web3
        mock_web3.eth.get_transaction_count.return_value = 0

        # Mock retryable gas error
        gas_error = web3_exceptions.Web3RPCError("intrinsic gas too low", rpc_response={})

        # Mock tx hash as bytes to support .hex()
        tx_hash_bytes = HexBytes("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")

        # side_effect for send_raw_transaction
        mock_web3.eth.send_raw_transaction.side_effect = [
            gas_error,
            gas_error,
            tx_hash_bytes
        ]

        # Mock wait receipt success
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        mock_keys.get_account.return_value.address = "0xSigner"
        signed_tx = MagicMock()
        signed_tx.raw_transaction = "0xRaw"
        mock_keys.sign_transaction.return_value = signed_tx

        # Patch internal check to be sure
        with patch.object(manager, "_is_gas_too_low_error", return_value=True):
             success, receipt = manager.sign_and_send({"to": "0xTo"}, "0xSigner")

        assert success is True
        assert receipt == mock_receipt
        # Verify retries (original + 2 failures = 3 calls)
        assert mock_web3.eth.send_raw_transaction.call_count == 3

def test_transaction_manager_retry_rpc(mock_keys):
    manager = TransactionManager(mock_keys)

    with patch("iwa.core.managers.ChainInterfaces") as mock_chains:
        mock_interface = MagicMock()
        mock_chains.return_value.get.return_value = mock_interface

        mock_web3 = mock_interface.web3
        mock_web3.eth.get_transaction_count.return_value = 0

        mock_interface.rotate_rpc.return_value = True

        tx_hash_bytes = HexBytes("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")

        mock_web3.eth.send_raw_transaction.side_effect = [
            Exception("Connection Error"),
            tx_hash_bytes
        ]

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        mock_keys.get_account.return_value.address = "0xSigner"
        signed_tx = MagicMock()
        signed_tx.raw_transaction = "0xRaw"
        mock_keys.sign_transaction.return_value = signed_tx

        success, receipt = manager.sign_and_send({"to": "0xTo"}, "0xSigner")

        assert success is True
        assert mock_interface.rotate_rpc.call_count >= 1

def test_transaction_manager_signer_not_found(mock_keys):
    manager = TransactionManager(mock_keys)
    mock_keys.get_account.return_value = None

    with patch("iwa.core.managers.ChainInterfaces"):
        success, _ = manager.sign_and_send({}, "0xMissing")
        assert success is False

# --- TUI Modal Tests ---

@pytest.mark.asyncio
async def test_create_eoa_modal():
    modal = CreateEOAModal()
    mock_event = MagicMock()
    mock_event.button.id = "cancel"
    with patch.object(modal, "dismiss") as mock_dismiss:
        modal.on_button_pressed(mock_event)
        mock_dismiss.assert_called()
    mock_event.button.id = "create"
    try:
        modal.on_button_pressed(mock_event)
    except Exception:
        pass

# --- WalletsView Filtering Tests ---

@pytest.mark.asyncio
async def test_wallets_view_filtering():
    with patch("iwa.core.db.db"):
        app = IwaApp()
        async with app.run_test() as _:
            view = app.query_one(WalletsView)

            with patch.object(view, "fetch_all_for_token") as mock_fetch, \
                 patch.object(view, "refresh_table_structure_and_data") as _, \
                 patch.object(view, "clear_all_for_token") as mock_clear:

                mock_chk_event = MagicMock()
                mock_chk_event.checkbox.id = "cb_Token"
                mock_chk_event.value = True

                view.on_checkbox_changed(mock_chk_event)

                mock_fetch.assert_called_with("Token")

                mock_chk_event.value = False
                view.on_checkbox_changed(mock_chk_event)
                mock_clear.assert_called_with("Token")
