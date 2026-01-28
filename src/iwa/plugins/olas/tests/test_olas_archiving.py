"""Tests for Olas multisig archiving logic."""

import unittest
from unittest.mock import MagicMock, patch

from iwa.core.models import StoredAccount
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager


class TestOlasArchiving(unittest.TestCase):
    """Test multisig archiving logic during deployment."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_wallet = MagicMock()
        # Mock KeyStorage
        self.mock_key_storage = MagicMock()
        self.mock_wallet.key_storage = self.mock_key_storage

        # Initialize ServiceManager
        with (
            patch("iwa.core.models.Config"),
            patch("iwa.plugins.olas.service_manager.base.ChainInterfaces"),
            patch("iwa.plugins.olas.service_manager.base.ContractCache"),
            patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract"),
        ):
            self.sm = ServiceManager(self.mock_wallet)
            self.sm.service = Service(service_name="trader_psi", chain_name="gnosis", service_id=1)
            self.sm.chain_name = "gnosis"

    def test_multisig_archiving_logic(self):
        """Test that old multisig is archived if tag is taken by different address."""
        multisig_tag = "trader_psi_multisig"
        old_address = "0x1111111111111111111111111111111111111111"
        new_address = "0x2222222222222222222222222222222222222222"

        # 1. Simulate existing multisig in wallet with same tag
        existing_acc = StoredAccount(address=old_address, tag=multisig_tag)
        self.mock_key_storage.find_stored_account.return_value = existing_acc

        # 2. Mock required contract calls for deploy()
        self.sm.registry.get_service.return_value = {
            "state": ServiceState.FINISHED_REGISTRATION,  # DEPLOYED
            "security_deposit": 0,
            "multisig": new_address,
            "threshold": 1,
            "configHash": b"\x00" * 32,
        }
        self.sm.registry.call.return_value = (None, [])  # getAgentInstances

        # 3. Trigger deploy (archiving happens here)
        with (
            patch.object(
                self.mock_wallet, "sign_and_send_transaction", return_value=(True, {"status": 1})
            ),
            patch.object(
                self.sm.registry,
                "extract_events",
                return_value=[
                    {"name": "DeployService", "args": {}},
                    {"name": "CreateMultisigWithAgents", "args": {"multisig": new_address}},
                ],
            ),
            patch("iwa.plugins.olas.service_manager.lifecycle.get_tx_hash", return_value="0xhash"),
            patch("iwa.core.models.StoredSafeAccount") as mock_safe_cls,
        ):
            self.sm.deploy(fund_multisig=False)

            # 4. Verify rename_account was called for the old address
            archive_tag = f"{multisig_tag}_old_{old_address[:6]}"
            self.mock_key_storage.rename_account.assert_called_with(old_address, archive_tag)

            # 5. Verify new account constructor was called with correct params
            mock_safe_cls.assert_called()
            _, kwargs = mock_safe_cls.call_args
            self.assertEqual(kwargs["address"], new_address)
            self.assertEqual(kwargs["tag"], multisig_tag)


if __name__ == "__main__":
    unittest.main()
