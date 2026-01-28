"""Regression tests for recent fixes."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from iwa.core.keys import KeyStorage
from iwa.core.models import EthereumAddress
from iwa.core.services.transaction import TransactionService


class TestRegressionFixes(unittest.TestCase):
    """Test regression fixes for fees and serialization."""

    def test_transaction_service_fee_autofill(self):
        """Test that TransactionService auto-fills fees if missing."""
        # 1. Setup mocks
        mock_key_storage = MagicMock()
        mock_account_service = MagicMock()

        # Mock account resolution
        mock_account = MagicMock()
        mock_account.address = "0x1234567890123456789012345678901234567890"
        mock_account.tag = "signer"
        mock_account_service.resolve_account.return_value = mock_account

        service = TransactionService(mock_key_storage, mock_account_service)

        # 2. Mock ChainInterface to return specific fees
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.chain_id = 100
        mock_chain_interface.web3.eth.get_transaction_count.return_value = 1

        # This is what we are testing: get_suggested_fees() provides the safety net
        mock_chain_interface.get_suggested_fees.return_value = {
            "maxFeePerGas": 1500,
            "maxPriorityFeePerGas": 10,
        }

        with patch("iwa.core.services.transaction.ChainInterfaces") as mock_interfaces:
            mock_interfaces.return_value.get.return_value = mock_chain_interface

            # 3. Prepare transaction WITHOUT fees
            tx = {"to": "0x09312C66A14a024B4e903D986Ca7E2C0dDD06227", "value": 1000, "gas": 21000}

            # 4. Run internal preparation
            service._prepare_transaction(tx, "signer", mock_chain_interface)

            # 5. Verify fees were auto-filled
            self.assertEqual(tx["maxFeePerGas"], 1500)
            self.assertEqual(tx["maxPriorityFeePerGas"], 10)
            self.assertIn("nonce", tx)
            self.assertEqual(tx["chainId"], 100)

    def test_key_storage_mode_json_serialization(self):
        """Test that KeyStorage uses mode='json' to serialize EthereumAddress correctly."""
        import tempfile

        from iwa.core.models import StoredAccount

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "wallet.json"

            # 1. Initialize KeyStorage
            storage = KeyStorage(path=tmp_path, password="test")

            # 2. Add an account with a real EthereumAddress object
            addr_str = "0x1234567890123456789012345678901234567890"
            addr_obj = EthereumAddress(addr_str)
            acc = StoredAccount(address=addr_obj, tag="test-tag")
            storage.accounts = {addr_obj: acc}

            # 3. Mock json.dump to see what's being written
            with patch("json.dump") as mock_dump:
                # We need to mock open() as well to prevent real file creation if not needed,
                # but since we are in a temp dir, it's fine.
                storage.save()

                # 4. Capture the data passed to json.dump
                self.assertTrue(mock_dump.called)
                dumped_data = mock_dump.call_args[0][0]

                # 5. Verify the address is a plain string in the dump
                accounts = dumped_data["accounts"]

                for key in accounts.keys():
                    # Key serialization in Pydantic v2 model_dump(mode='json')
                    self.assertIsInstance(key, str, f"Key {key} should be a string")
                    self.assertEqual(key.lower(), addr_str.lower())

                    # Also check the address field inside the value
                    self.assertIsInstance(accounts[key]["address"], str)
                    self.assertEqual(accounts[key]["address"].lower(), addr_str.lower())


if __name__ == "__main__":
    unittest.main()
