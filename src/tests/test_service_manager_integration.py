import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_main():
    # Create mocks for all required modules
    mock_cowpy = MagicMock()
    modules_to_patch = {
        "cowdao_cowpy": mock_cowpy,
        "cowdao_cowpy.common": MagicMock(),
        "cowdao_cowpy.common.chains": MagicMock(),
        "cowdao_cowpy.app_data": MagicMock(),
        "cowdao_cowpy.app_data.utils": MagicMock(),
        "cowdao_cowpy.contracts": MagicMock(),
        "cowdao_cowpy.contracts.order": MagicMock(),
        "cowdao_cowpy.contracts.sign": MagicMock(),
        "cowdao_cowpy.cow": MagicMock(),
        "cowdao_cowpy.cow.swap": MagicMock(),
        "cowdao_cowpy.order_book": MagicMock(),
        "cowdao_cowpy.order_book.api": MagicMock(),
        "cowdao_cowpy.order_book.config": MagicMock(),
        "cowdao_cowpy.order_book.generated": MagicMock(),
        "cowdao_cowpy.order_book.generated.model": MagicMock(),
    }

    with patch.dict(sys.modules, modules_to_patch):
        # Ensure iwa.core.wallet is imported so we can patch it
        # We need to make sure it's re-imported if it was already imported,
        # to use the mocked cowdao_cowpy if needed, but actually we just need to patch Wallet.
        # If iwa.core.wallet is already imported, patching Wallet is enough.
        # But iwa.core.test might be already imported.
        if "iwa.core.test" in sys.modules:
            del sys.modules["iwa.core.test"]

        # We need to ensure iwa.core.wallet is importable.
        # If it's not in sys.modules, import it.
        # But importing it triggers cowdao_cowpy import.
        # Since we patched sys.modules, it should use our mocks.
        if "iwa.core.wallet" not in sys.modules:
            pass

        with (
            patch("iwa.core.wallet.Wallet"),
            patch("iwa.core.test.ServiceManager") as mock_service_manager,
        ):
            # Import main here
            from iwa.core.test import main

            # Mock the instance returned by ServiceManager()
            mock_sm_instance = mock_service_manager.return_value

            await main()

            # Verify ServiceManager was initialized with wallet
            mock_service_manager.assert_called()

            # Verify create was called
            mock_sm_instance.create.assert_called_once()
