"""Modal callback tests for OlasView."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.plugins.olas.tui.olas_view import OlasView


@pytest.mark.asyncio
async def test_olas_view_modal_callbacks_full(mock_wallet):
    """Test OlasView modal callbacks directly for coverage."""
    # Patch ServiceManager globally for the view init
    with patch("iwa.plugins.olas.service_manager.ServiceManager"):
        view = OlasView(wallet=mock_wallet)
        view.load_services = MagicMock()
        view.notify = MagicMock()
        mock_app = MagicMock()

        # Patch the read-only property 'app'
        with patch.object(OlasView, "app", new_callable=PropertyMock) as mock_app_prop:
            mock_app_prop.return_value = mock_app

            # 1. Create Service callback (Full flow)
            view.show_create_service_modal()
            assert mock_app.push_screen.called
            args, kwargs = mock_app.push_screen.call_args
            callback = kwargs.get("callback") or (args[1] if len(args) > 1 else None)

            if callback:
                with patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls:
                    mock_sm = mock_sm_cls.return_value
                    mock_sm.create.return_value = 123

                    # Sub-case: created but deploy failed
                    mock_sm.spin_up.return_value = False
                    callback({"chain": "gnosis", "name": "test", "staking_contract": None})
                    view.notify.assert_any_call(
                        "Service created (ID: 123) but deployment failed", severity="warning"
                    )

                    # Sub-case: success with staking
                    mock_sm.spin_up.return_value = True
                    callback({"chain": "gnosis", "name": "test", "staking_contract": "0x1"})
                    view.notify.assert_any_call(
                        "Service deployed and staked! ID: 123", severity="information"
                    )

                    # Sub-case: exception
                    mock_sm.create.side_effect = Exception("creation error")
                    callback({"chain": "gnosis", "name": "test"})
                    view.notify.assert_any_call("Error: creation error", severity="error")

            view.load_services.reset_mock()
            mock_app.push_screen.reset_mock()

            # 2. Fund Service callback (Full flow)
            view.show_fund_service_modal("gnosis:1")
            assert mock_app.push_screen.called
            args, kwargs = mock_app.push_screen.call_args
            callback = kwargs.get("callback") or (args[1] if len(args) > 1 else None)

            if callback:
                with patch("iwa.core.models.Config") as mock_conf_cls:
                    mock_conf_instance = mock_conf_cls.return_value
                    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
                    mock_conf_instance.plugins = {
                        "olas": {
                            "services": {
                                "gnosis:1": {
                                    "agent_address": addr,
                                    "multisig_address": addr,
                                    "chain_name": "gnosis",
                                    "service_name": "test",
                                    "service_id": 1,
                                }
                            }
                        }
                    }
                    callback({"agent_amount": 1.0, "safe_amount": 0.5})
                    assert mock_wallet.send.call_count == 2
                    view.notify.assert_any_call("Service funded!", severity="information")
                    view.load_services.assert_called_once()

                    # Sub-case: skip amount 0
                    mock_wallet.send.reset_mock()
                    callback({"agent_amount": 0.0, "safe_amount": 0.0})
                    assert mock_wallet.send.call_count == 0

            view.load_services.reset_mock()
            mock_app.push_screen.reset_mock()

            # 3. Stake Service callback
            view._chain = "gnosis"
            with patch(
                "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"test": "0x1"}},
            ):
                view.stake_service("gnosis:1")
                assert mock_app.push_screen.called
                args, kwargs = mock_app.push_screen.call_args
                callback = kwargs.get("callback") or (args[1] if len(args) > 1 else None)
                if callback:
                    with (
                        patch(
                            "iwa.plugins.olas.service_manager.ServiceManager"
                        ) as mock_sm_inner_cls,
                        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci,
                    ):
                        mock_ci.get_instance.return_value.web3.eth.contract.return_value = (
                            MagicMock()
                        )
                        mock_sm_inner = mock_sm_inner_cls.return_value
                        mock_sm_inner.stake.return_value = True
                        try:
                            # Use a valid checksum address
                            callback("0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB")
                        except Exception as e:
                            pytest.fail(f"Stake callback failed: {e}")
                        view.load_services.assert_called_once()
