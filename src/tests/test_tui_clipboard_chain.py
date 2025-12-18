from unittest.mock import MagicMock, patch

import pytest
from textual.widget import Widget

from iwa.tui.app import IwaApp
from iwa.tui.views import WalletsView

# --- WalletsView Clipboard Tests ---


@pytest.mark.asyncio
async def test_wallets_view_clipboard():
    with patch("iwa.core.db.db"):
        app = IwaApp()
        async with app.run_test() as _:
            view = app.query_one(WalletsView)

            # Test on_account_cell_selected
            mock_event = MagicMock()
            mock_event.coordinate.column = 1
            mock_event.value = "0xAddress"

            with patch.dict("sys.modules", {"pyperclip": MagicMock()}):
                view.on_account_cell_selected(mock_event)
                pass

            # Test on_tx_cell_selected
            mock_event_tx = MagicMock()
            mock_event_tx.coordinate.column = 0
            mock_event_tx.data_table.columns.values.return_value = [
                MagicMock(label="Hash"),
                MagicMock(label="Status"),
            ]
            mock_event_tx.cell_key.row_key.value = "0xFullHash"

            with patch.dict("sys.modules", {"pyperclip": MagicMock()}):
                view.on_tx_cell_selected(mock_event_tx)


# --- WalletsView Chain Change Tests ---


class DummySelect(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(id=kwargs.get("id"))

    def set_options(self, options):
        pass


@pytest.mark.asyncio
async def test_wallets_view_chain_change():
    with patch("iwa.core.db.db"):
        app = IwaApp()
        async with app.run_test() as _:
            view = app.query_one(WalletsView)

            # Mock ChainInterfaces
            with patch("iwa.tui.views.ChainInterfaces") as mock_chains:
                mock_interface = MagicMock()
                mock_interface.chain.rpc = "http://rpc"
                mock_interface.chain.native_currency = "ETH"
                mock_interface.tokens = {"TOKEN": "0xToken"}
                mock_chains.return_value.get.return_value = mock_interface

                # Patch Select with DummyWidget to satisfy isinstance(w, Widget)
                with patch("iwa.tui.views.Select", side_effect=DummySelect) as mock_select:
                    # Chain changed event
                    mock_event = MagicMock()
                    mock_event.value = "gnosis"
                    mock_event.control.value = "gnosis"
                    view.active_chain = "ethereum"

                    # Trigger
                    await view.on_chain_changed(mock_event)

                    assert view.active_chain == "gnosis"
                    assert mock_select.called
