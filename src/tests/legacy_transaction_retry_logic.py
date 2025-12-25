from unittest.mock import MagicMock, patch

import pytest

from iwa.tui.app import IwaApp
from iwa.tui.modals import CreateEOAModal
from iwa.tui.screens.wallets import WalletsScreen

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


# --- WalletsScreen Filtering Tests ---


@pytest.mark.asyncio
async def test_wallets_view_filtering():
    with patch("iwa.core.db.db"):
        app = IwaApp()
        async with app.run_test() as _:
            view = app.query_one(WalletsScreen)

            with (
                patch.object(view, "fetch_all_balances") as mock_fetch,
                patch.object(view, "refresh_table_structure_and_data") as mock_refresh,
            ):
                mock_chk_event = MagicMock()
                mock_chk_event.checkbox.id = "cb_Token"
                mock_chk_event.value = True

                view.on_checkbox_changed(mock_chk_event)

                mock_fetch.assert_called_with(view.active_chain, ["Token"])

                mock_chk_event.value = False
                view.on_checkbox_changed(mock_chk_event)
                mock_refresh.assert_called()
