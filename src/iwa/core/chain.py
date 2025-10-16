from web3 import Web3
import time
from typing import Callable, Optional, Tuple, Dict
from triton.tools import singleton
from triton.models import TritonSecrets
from loguru import logger



@singleton
class ChainInterface:

    def __init__(self, rpc: Optional[str] = None):
        rpc = rpc or TritonSecrets().gnosis_rpc.get_secret_value()
        self.web3 = Web3(Web3.HTTPProvider(rpc))

    def sign_and_send_transaction(self, transaction: dict, private_key: str) -> Tuple[bool, Dict]:
        """Sign and send a transaction."""
        signed_txn = self.web3.eth.account.sign_transaction(
            transaction, private_key=private_key
        )
        txn_hash = self.web3.eth.send_raw_transaction(signed_txn.raw_transaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(txn_hash)
        if receipt.status == 1:
            self.wait_for_no_pending_tx(transaction["from"])
            return True, receipt
        return False, {}

    def estimate_gas(self, from_address: str, function: Callable, **kwargs) -> int:
        """Estimate gas for a contract function call."""
        value = kwargs.get("value", 0)
        if "value" in kwargs:
            del kwargs["value"]
        method = function(*kwargs.values())
        estimated_gas = method.estimate_gas({"from": from_address, "value": value})
        return int(estimated_gas * 1.1)

    def calculate_transaction_params(self, from_address: str, function: Callable, **kwargs) -> dict:
        """Calculate transaction parameters for a contract function call."""
        value = kwargs.get("value", 0)
        params = {
            "from": from_address,
            "nonce": self.web3.eth.get_transaction_count(from_address),
            "gas": self.estimate_gas(from_address, function, **kwargs),
            "gasPrice": self.web3.eth.gas_price,
            "value": value,
        }
        return params

    def wait_for_no_pending_tx(self, from_address: str, max_wait_seconds: int = 60, poll_interval: float = 2.0):
        """Wait for no pending transactions for a specified time."""
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            latest_nonce = self.web3.eth.get_transaction_count(from_address, block_identifier="latest")
            pending_nonce = self.web3.eth.get_transaction_count(from_address, block_identifier="pending")

            if pending_nonce == latest_nonce:
                return True

            time.sleep(poll_interval)

        return False

    def get_native_balance_wei(self, address: str):
        """Get the native balance in wei"""
        return self.web3.eth.get_balance(address)

    def get_native_balance(self, address: str):
        """Get the native balance in ether"""
        balance_wei = self.get_native_balance_wei(address)
        balance_ether = self.web3.from_wei(balance_wei, "ether")
        return balance_ether
