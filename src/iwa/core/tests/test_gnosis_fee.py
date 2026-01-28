"""Test Gnosis fee calculation fix."""

import unittest
from unittest.mock import MagicMock

from iwa.core.chain.interface import ChainInterface


class TestGnosisFeeFix(unittest.TestCase):
    """Test fee calculation for Gnosis chain."""

    def setUp(self):
        """Set up test fixtures."""
        self.chain_interface = ChainInterface("gnosis")
        # Mock web3 to avoid real connection
        self.chain_interface.web3 = MagicMock()
        self.chain_interface.web3.eth = MagicMock()

    def test_fee_too_low_fix(self):
        """Test that maxPriorityFeePerGas is forced to at least 1 wei on Gnosis."""
        # 1. Setup EIP-1559 environment (block has baseFeePerGas)
        mock_block = {"baseFeePerGas": 5000}
        self.chain_interface.web3.eth.get_block.return_value = mock_block

        # 2. Simulate RPC returning 0 priority fee (cause of the error)
        self.chain_interface.web3.eth.max_priority_fee = 0

        # 3. Setup dummy function for gas estimation
        mock_func = MagicMock()
        mock_func.estimate_gas.return_value = 100_000

        # 4. Call calculation
        tx_params = {"from": "0x123", "value": 0}
        params = self.chain_interface.calculate_transaction_params(mock_func, tx_params)

        # 5. Verify the fix
        # Should have EIP-1559 fields
        self.assertIn("maxFeePerGas", params)
        self.assertIn("maxPriorityFeePerGas", params)
        self.assertNotIn("gasPrice", params)

        # CRITICAL ASSERTION: maxPriorityFeePerGas must be >= 1
        # If the fix works, it should be 1. If it fails (old behavior), it would be 0.
        self.assertEqual(
            params["maxPriorityFeePerGas"], 1, "Priority fee should be forced to 1 wei"
        )

        # Verify max fee calculation: (base * 1.5) + priority
        expected_max_fee = int(5000 * 1.5) + 1
        self.assertEqual(params["maxFeePerGas"], expected_max_fee)

    def test_legacy_fallback(self):
        """Test fallback to legacy gasPrice if baseFeePerGas is missing."""
        # Setup legacy block (no baseFeePerGas)
        self.chain_interface.web3.eth.get_block.return_value = {}
        self.chain_interface.web3.eth.gas_price = 2000000000

        mock_func = MagicMock()
        mock_func.estimate_gas.return_value = 100_000

        tx_params = {"from": "0x123", "value": 0}
        params = self.chain_interface.calculate_transaction_params(mock_func, tx_params)

        self.assertIn("gasPrice", params)
        self.assertNotIn("maxFeePerGas", params)
        self.assertEqual(params["gasPrice"], 2000000000)

    def test_other_chain_behavior(self):
        """Test that other chains (e.g. Ethereum) don't necessarily upgrade 0 to 1 (unless generic rule applies)."""
        # Our fix in interface.py applies the fallback logic:
        # if max_priority_fee < 1: max_priority_fee = 1
        # This is now generic in the cleaned up code (lines 449-450: if max_priority_fee < 1: max_priority_fee = 1)
        # So it should apply to ALL chains that support EIP-1559.

        # We'll use Ethereum to verify generic behavior
        eth_interface = ChainInterface("ethereum")
        eth_interface.web3 = MagicMock()
        eth_interface.web3.eth = MagicMock()

        mock_block = {"baseFeePerGas": 100_000}
        eth_interface.web3.eth.get_block.return_value = mock_block
        eth_interface.web3.eth.max_priority_fee = 0

        mock_func = MagicMock()
        mock_func.estimate_gas.return_value = 21000

        params = eth_interface.calculate_transaction_params(mock_func, {"from": "0x123"})

        self.assertEqual(
            params["maxPriorityFeePerGas"], 1, "Generic fallback should apply to all chains"
        )
