import time
from typing import Dict, Optional, Tuple, Union

from eth_account import Account
from loguru import logger
from pydantic import BaseModel
from web3 import Web3

from iwa.core.models import EthereumAddress, Secrets
from iwa.core.utils import singleton


class SupportedChain(BaseModel):
    """SupportedChain"""

    name: str
    rpc: str
    chain_id: int
    native_currency: str
    tokens: Dict[str, EthereumAddress] = {}

    def get_token_address(self, token_name: str) -> Optional[EthereumAddress]:
        """Get token address by name"""
        return self.tokens.get(token_name.upper(), None)


@singleton
class Gnosis(SupportedChain):
    """Gnosis Chain"""

    name: str = "Gnosis"
    rpc: str = Secrets().gnosis_rpc.get_secret_value() if Secrets().gnosis_rpc else None
    chain_id: int = 100
    native_currency: str = "xDAI"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f")
    }


@singleton
class Ethereum(SupportedChain):
    """Ethereum Mainnet"""

    name: str = "Ethereum"
    rpc: str = Secrets().ethereum_rpc.get_secret_value() if Secrets().ethereum_rpc else None
    chain_id: int = 1
    native_currency: str = "ETH"


@singleton
class Base(SupportedChain):
    """Base"""

    name: str = "Base"
    rpc: str = Secrets().base_rpc.get_secret_value() if Secrets().base_rpc else None
    chain_id: int = 8453
    native_currency: str = "ETH"


@singleton
class SupportedChains:
    """SupportedChains"""

    gnosis: SupportedChain = Gnosis()
    ethereum: SupportedChain = Ethereum()
    base: SupportedChain = Base()


class ChainInterface:
    """ChainInterface"""

    def __init__(self, chain: Union[SupportedChain, str] = Gnosis()):
        """ChainInterface"""
        if isinstance(chain, str):
            chain: SupportedChain = getattr(SupportedChains(), chain.lower())

        self.chain = chain
        self.web3 = Web3(Web3.HTTPProvider(self.chain.rpc))

    def is_contract(self, address: str) -> bool:
        """Check if address is a contract"""
        code = self.web3.eth.get_code(address)
        return code != b""

    def get_native_balance_wei(self, address: str):
        """Get the native balance in wei"""
        return self.web3.eth.get_balance(address)

    def get_native_balance(self, address: str):
        """Get the native balance in ether"""
        balance_wei = self.get_native_balance_wei(address)
        balance_ether = self.web3.from_wei(balance_wei, "ether")
        return balance_ether

    def sign_and_send_transaction(self, transaction: dict, private_key: str) -> Tuple[bool, Dict]:
        """Sign and send a transaction."""
        signed_txn = self.web3.eth.account.sign_transaction(transaction, private_key=private_key)
        txn_hash = self.web3.eth.send_raw_transaction(signed_txn.raw_transaction)
        receipt = self.web3.eth.wait_for_transaction_receipt(txn_hash)
        if receipt.status == 1:
            self.wait_for_no_pending_tx(transaction["from"])
            logger.info(f"Transaction sent successfully. Tx Hash: {txn_hash.hex()}")
            return True, receipt
        logger.error("Transaction failed.")
        return False, {}

    def estimate_gas(self, built_method, tx_params) -> int:
        """Estimate gas for a contract function call."""
        from_address = tx_params["from"]
        value = tx_params.get("value", 0)
        estimated_gas = (
            0
            if self.is_contract(from_address)
            else built_method.estimate_gas({"from": from_address, "value": value})
        )
        return int(estimated_gas * 1.1)

    def calculate_transaction_params(self, built_method, tx_params) -> dict:
        """Calculate transaction parameters for a contract function call."""
        params = {
            "from": tx_params["from"],
            "value": tx_params.get("value", 0),
            "nonce": self.web3.eth.get_transaction_count(tx_params["from"]),
            "gas": self.estimate_gas(built_method, tx_params),
            "gasPrice": self.web3.eth.gas_price,
        }
        return params

    def wait_for_no_pending_tx(
        self, from_address: str, max_wait_seconds: int = 60, poll_interval: float = 2.0
    ):
        """Wait for no pending transactions for a specified time."""
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            latest_nonce = self.web3.eth.get_transaction_count(
                from_address, block_identifier="latest"
            )
            pending_nonce = self.web3.eth.get_transaction_count(
                from_address, block_identifier="pending"
            )

            if pending_nonce == latest_nonce:
                return True

            time.sleep(poll_interval)

        return False

    def send_native_transaction(
        self,
        from_account: Account,
        to_address: EthereumAddress,
        amount_wei: int,
    ) -> bool:
        """Send native currency transaction"""

        tx = {
            "from": from_account.address,
            "to": to_address,
            "value": amount_wei,
            "nonce": self.web3.eth.get_transaction_count(from_account.address),
            "chainId": self.chain.chain_id,
        }

        balance_wei = self.get_native_balance_wei(from_account.address)
        gas_price = self.web3.eth.gas_price
        gas_estimate = self.web3.eth.estimate_gas(tx)
        required_wei = amount_wei + (gas_estimate * gas_price)

        if balance_wei < required_wei:
            logger.error(
                f"Insufficient balance to cover amount and gas fees.\nBalance: {self.web3.from_wei(balance_wei, 'ether'):.2f} {self.chain.native_currency}, Required: {self.web3.from_wei(required_wei, 'ether'):.2f} {self.chain.native_currency}"
            )
            return False

        tx["gas"] = gas_estimate
        tx["gasPrice"] = gas_price

        success, receipt = self.sign_and_send_transaction(tx, from_account.key)
        return success

    def get_token_address(self, token_name: str) -> Optional[EthereumAddress]:
        """Get token address by name"""
        return self.chain.get_token_address(token_name)


@singleton
class ChainInterfaces:
    """ChainInterfaces"""

    gnosis: ChainInterface = ChainInterface(Gnosis())
    ethereum: ChainInterface = ChainInterface(Ethereum())
    base: ChainInterface = ChainInterface(Base())

    def get(self, chain_name: str) -> ChainInterface:
        """Get ChainInterface by chain name"""
        chain_name = chain_name.strip().lower()

        if not hasattr(self, chain_name):
            raise ValueError(f"Unsupported chain: {chain_name}")

        return getattr(self, chain_name)
