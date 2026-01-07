"""Gnosis Safe interaction."""

from typing import Callable, Optional

from safe_eth.eth import EthereumClient
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.safe import Safe, SafeOperationEnum
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.models import StoredSafeAccount
from iwa.core.settings import settings
from iwa.core.utils import configure_logger

logger = configure_logger()


class SafeMultisig:
    """Class to interact with Gnosis Safe multisig wallets.

    Wraps the `safe-eth-py` library to provide a simplified interface for
    checking owners, thresholds, and building/sending multi-signature transactions.
    """

    def __init__(self, safe_account: StoredSafeAccount, chain_name: str):
        """Initialize the SafeMultisig instance."""
        # Normalize chain comparison to be case-insensitive
        normalized_chains = [c.lower() for c in safe_account.chains]
        if chain_name.lower() not in normalized_chains:
            raise ValueError(f"Safe account is not deployed on chain: {chain_name}")

        rpc_secret = getattr(settings, f"{chain_name.lower()}_rpc")
        ethereum_client = EthereumClient(rpc_secret.get_secret_value())
        self.multisig = Safe(safe_account.address, ethereum_client)
        self.ethereum_client = ethereum_client

    def get_owners(self) -> list:
        """Get the list of owners of the safe."""
        return self.multisig.retrieve_owners()

    def get_threshold(self) -> int:
        """Get the threshold of the safe."""
        return self.multisig.retrieve_threshold()

    def get_nonce(self) -> int:
        """Get the current nonce of the safe."""
        return self.multisig.retrieve_nonce()

    def retrieve_all_info(self) -> dict:
        """Retrieve all information about the safe."""
        return self.multisig.retrieve_all_info()

    def build_tx(
        self,
        to: str,
        value: int,
        data: str = "",
        operation: int = SafeOperationEnum.CALL.value,
        safe_tx_gas: int = 0,
        base_gas: int = 0,
        gas_price: int = 0,
        gas_token: str = NULL_ADDRESS,
        refund_receiver: str = NULL_ADDRESS,
        signatures: str = "",
        safe_nonce: Optional[int] = None,
    ) -> SafeTx:
        """Build a Safe transaction without signing it.

        Args:
            to: Destination address.
            value: Value in Wei to transfer.
            data: Hex data string (calldata).
            operation: Operation type (0=Call, 1=DelegateCall).
            safe_tx_gas: Gas that should be used for the Safe transaction.
            base_gas: Gas costs for that are independent of the transaction execution
                      (e.g. base transaction fee, signature check, payment of the refund).
            gas_price: Gas price that should be used for the payment calculation.
            gas_token: Token address (or 0 if ETH) that is used for the payment.
            refund_receiver: Address of receiver of gas payment (or 0 if tx.origin).
            signatures: Packed signature data (optional at build time).
            safe_nonce: Nonce of the Safe transaction (optional, defaults to current).

        Returns:
            SafeTx: The constructed Safe transaction object.

        """
        return self.multisig.build_multisig_tx(
            to,
            value,
            bytes.fromhex(data[2:]) if data else b"",
            operation,
            safe_tx_gas,
            base_gas,
            gas_price,
            gas_token,
            refund_receiver,
            signatures,
            safe_nonce,
        )

    def send_tx(
        self,
        to: str,
        value: int,
        sign_and_execute_callback: Callable[[SafeTx], str],
        data: str = "",
        operation: int = SafeOperationEnum.CALL.value,
        safe_tx_gas: int = 0,
        base_gas: int = 0,
        gas_price: int = 0,
        gas_token: str = NULL_ADDRESS,
        refund_receiver: str = NULL_ADDRESS,
        signatures: str = "",
        safe_nonce: Optional[int] = None,
    ) -> str:
        """Build and execute a multisig transaction using a callback for signing/execution.

        This method:
        1. Builds the `SafeTx` object.
        2. Passes it to the `sign_and_execute_callback`.
        3. Returns the resulting transaction hash.

        Args:
            sign_and_execute_callback: A function that accepts a `SafeTx`, signs it,
                                       executes it, and returns the tx hash.
            to: Destination address.
            value: Value in Wei.
            data: Calldata hex string.
            operation: Operation type (Call/DelegateCall).
            safe_tx_gas: Gas limit for the safe tx.
            base_gas: Base gas cost.
            gas_price: Gas price for refund.
            gas_token: Gas token for refund.
            refund_receiver: Refund receiver address.
            signatures: Pre-existing signatures.
            safe_nonce: Safe nonce.

        Returns:
            str: The executed transaction hash.

        """
        safe_tx = self.build_tx(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            base_gas,
            gas_price,
            gas_token,
            refund_receiver,
            signatures,
            safe_nonce,
        )

        tx_hash = sign_and_execute_callback(safe_tx)
        logger.info(f"Safe transaction sent. Tx Hash: {tx_hash}")
        return tx_hash
