from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe
from safe_eth.safe.safe_tx import SafeTx
from typing import Optional, Dict
from iwa.core.models import EthereumAddress, Secrets, StoredSafeAccount
from safe_eth.eth.constants import NULL_ADDRESS
from loguru import logger
from safe_eth.safe import SafeOperationEnum


class SafeMultisig:
    """Class to interact with Gnosis Safe multisig wallets."""

    def __init__(self, safe_account: StoredSafeAccount, chain_name: str):
        """Initialize the SafeMultisig instance."""

        if chain_name not in safe_account.chains:
            raise ValueError(f"Safe account is not deployed on chain: {chain_name}")

        rpc_secret = getattr(Secrets(), f"{chain_name}_rpc")
        ethereum_client = EthereumClient(rpc_secret.get_secret_value())
        self.multisig = Safe(safe_account.address, ethereum_client)

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

    def send_tx(
        self,
        to: str,
        value: int,
        signers_private_keys: list,
        data: str = "",
        operation: int = SafeOperationEnum.CALL.value,
        safe_tx_gas: int = 0,
        base_gas: int = 0,
        gas_price: int = 0,
        gas_token: str = NULL_ADDRESS,
        refund_receiver: str = NULL_ADDRESS,
        signatures: str = "",
        safe_nonce: Optional[int] = None,
    ) -> dict:
        """Prepare a multisig transaction."""

        safe_tx = self.multisig.build_multisig_tx(
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

        for pk in signers_private_keys:
            safe_tx.sign(pk)

        safe_tx.call()  # Check it works
        safe_tx.execute(signers_private_keys[0])
        logger.info(f"Safe transaction sent. Tx Hash: {safe_tx.tx_hash.hex()}")
