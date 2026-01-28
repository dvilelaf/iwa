"""Safe service module."""

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from loguru import logger
from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe, SafeOperationEnum
from safe_eth.safe.proxy_factory import ProxyFactory
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.constants import ZERO_ADDRESS
from iwa.core.db import log_transaction
from iwa.core.models import StoredSafeAccount
from iwa.core.utils import (
    get_safe_master_copy_address,
    get_safe_proxy_factory_address,
)

if TYPE_CHECKING:
    from iwa.core.keys import EncryptedAccount, KeyStorage
    from iwa.core.services.account import AccountService

# We need EncryptedAccount for checks at runtime
try:
    from iwa.core.keys import EncryptedAccount
except ImportError:
    # Circular import prevention if keys imports safe (it shouldn't)
    pass


class SafeService:
    """Service for Safe deployment and management."""

    def __init__(self, key_storage: "KeyStorage", account_service: "AccountService"):
        """Initialize SafeService."""
        self.key_storage = key_storage
        self.account_service = account_service
        self._client_cache: Dict[str, EthereumClient] = {}

    def create_safe(
        self,
        deployer_tag_or_address: str,
        owner_tags_or_addresses: List[str],
        threshold: int,
        chain_name: str,
        tag: Optional[str] = None,
        salt_nonce: Optional[int] = None,
    ) -> Tuple[StoredSafeAccount, str]:
        """Deploy a new Safe."""
        deployer_account = self._prepare_deployer_account(deployer_tag_or_address)
        owner_addresses = self._resolve_owner_addresses(owner_tags_or_addresses)

        ethereum_client = self._get_ethereum_client(chain_name)

        contract_address, tx_hash = self._deploy_safe_contract(
            deployer_account, owner_addresses, threshold, salt_nonce, ethereum_client
        )

        logger.info(
            f"Safe {tag} [{contract_address}] deployed on {chain_name} on transaction: {tx_hash}"
        )

        self._log_safe_deployment(
            deployer_account,
            deployer_tag_or_address,
            contract_address,
            tx_hash,
            chain_name,
            ethereum_client,
            tag,
        )

        safe_account = self._store_safe_account(
            contract_address, chain_name, owner_addresses, threshold, tag
        )

        return safe_account, tx_hash

    def _prepare_deployer_account(self, deployer_tag_or_address: str):
        deployer_stored_account = self.key_storage.find_stored_account(deployer_tag_or_address)
        if not deployer_stored_account or not isinstance(deployer_stored_account, EncryptedAccount):
            raise ValueError(
                f"Deployer account '{deployer_tag_or_address}' not found or is a Safe."
            )
        from eth_account import Account

        deployer_private_key = self.key_storage._get_private_key(deployer_stored_account.address)
        if not deployer_private_key:
            raise ValueError("Deployer private key not available.")
        return Account.from_key(deployer_private_key)

    def _resolve_owner_addresses(self, owner_tags_or_addresses: List[str]) -> List[str]:
        owner_addresses = []
        for tag_or_address in owner_tags_or_addresses:
            owner_stored_account = self.key_storage.find_stored_account(tag_or_address)
            if not owner_stored_account:
                raise ValueError(f"Owner account '{tag_or_address}' not found in wallet.")
            owner_addresses.append(owner_stored_account.address)
        return owner_addresses

    def _get_ethereum_client(self, chain_name: str) -> EthereumClient:
        from iwa.core.chain import ChainInterfaces

        # Use ChainInterface which has proper RPC rotation and parsing
        chain_interface = ChainInterfaces().get(chain_name)
        rpc_url = chain_interface.current_rpc

        if rpc_url not in self._client_cache:
            self._client_cache[rpc_url] = EthereumClient(rpc_url)

        return self._client_cache[rpc_url]

    def _deploy_safe_contract(
        self,
        deployer_account,
        owner_addresses: List[str],
        threshold: int,
        salt_nonce: Optional[int],
        ethereum_client: EthereumClient,
    ) -> Tuple[str, str]:
        master_copy = get_safe_master_copy_address("1.4.1")
        proxy_factory_address = get_safe_proxy_factory_address("1.4.1")

        if salt_nonce is not None:
            # Use ProxyFactory directly to enforce salt
            proxy_factory = ProxyFactory(proxy_factory_address, ethereum_client)

            # Encoded setup data
            empty_safe = Safe(master_copy, ethereum_client)
            setup_data = empty_safe.contract.functions.setup(
                owner_addresses,
                threshold,
                str(ZERO_ADDRESS),
                b"",
                str(ZERO_ADDRESS),
                str(ZERO_ADDRESS),
                0,
                str(ZERO_ADDRESS),
            ).build_transaction({"gas": 0, "gasPrice": 0})["data"]

            gas_price = ethereum_client.w3.eth.gas_price
            tx_sent = proxy_factory.deploy_proxy_contract_with_nonce(
                deployer_account,
                master_copy,
                initializer=bytes.fromhex(setup_data[2:])
                if setup_data.startswith("0x")
                else bytes.fromhex(setup_data),
                nonce=salt_nonce,
                gas=5_000_000,
                gas_price=gas_price,
            )
            return tx_sent.contract_address, f"0x{tx_sent.tx_hash.hex()}"

        else:
            # Standard random salt via Safe.create
            create_tx = Safe.create(
                ethereum_client=ethereum_client,
                deployer_account=deployer_account,
                master_copy_address=master_copy,
                owners=owner_addresses,
                threshold=threshold,
                proxy_factory_address=proxy_factory_address,
            )
            return create_tx.contract_address, f"0x{create_tx.tx_hash.hex()}"

    def _log_safe_deployment(
        self,
        deployer_account,
        deployer_tag_or_address: str,
        contract_address: str,
        tx_hash: str,
        chain_name: str,
        ethereum_client: EthereumClient,
        tag: Optional[str],
    ):
        # Resolve tag for logging
        resolved_from_tag = self.account_service.get_tag_by_address(deployer_account.address)

        # Get receipt and calculate gas info
        gas_cost = None
        gas_value_eur = None
        try:
            receipt = ethereum_client.w3.eth.get_transaction_receipt(tx_hash)
            if receipt:
                gas_used = receipt.get("gasUsed", 0)
                effective_gas_price = receipt.get("effectiveGasPrice", 0)
                gas_cost = gas_used * effective_gas_price

                # Get native token price for gas value calculation
                from iwa.core.pricing import PriceService

                chain_coingecko_ids = {"gnosis": "dai", "ethereum": "ethereum", "base": "ethereum"}
                coingecko_id = chain_coingecko_ids.get(chain_name, "ethereum")
                price_service = PriceService()
                native_price_eur = price_service.get_token_price(coingecko_id, "eur")

                if native_price_eur and gas_cost > 0:
                    gas_cost_eth = gas_cost / 10**18
                    gas_value_eur = gas_cost_eth * native_price_eur
        except Exception as e:
            logger.warning(f"Could not calculate gas info for Safe deployment: {e}")

        # Get native currency symbol for this chain
        from iwa.core.chain import ChainInterfaces

        chain_interface = ChainInterfaces().get(chain_name)
        native_symbol = chain_interface.chain.native_currency

        log_transaction(
            tx_hash=tx_hash,
            from_addr=deployer_account.address,
            to_addr=contract_address,
            token=native_symbol,
            amount_wei=0,
            chain=chain_name,
            from_tag=resolved_from_tag or deployer_tag_or_address,
            to_tag=tag,
            gas_cost=gas_cost,
            gas_value_eur=gas_value_eur,
            tags=["safe-deployment"],
        )

    def _store_safe_account(
        self,
        contract_address: str,
        chain_name: str,
        owner_addresses: List[str],
        threshold: int,
        tag: Optional[str],
    ) -> StoredSafeAccount:
        # Check if already exists (by address)
        existing = self.key_storage.find_stored_account(contract_address)
        if existing and isinstance(existing, StoredSafeAccount):
            if chain_name not in existing.chains:
                existing.chains.append(chain_name)
            self.key_storage.save()
            return existing

        # Create new Safe account object
        safe_account = StoredSafeAccount(
            tag=tag or f"Safe {contract_address[:6]}",
            address=contract_address,
            chains=[chain_name],
            threshold=threshold,
            signers=owner_addresses,
        )

        # Register via centralized method (enforces tag uniqueness)
        self.key_storage.register_account(safe_account)
        return safe_account

    def redeploy_safes(self):
        """Redeploy all safes to ensure they exist on all chains."""
        for account in list(self.key_storage.accounts.values()):
            if not isinstance(account, StoredSafeAccount):
                continue

            for chain in account.chains:
                from iwa.core.chain import ChainInterfaces

                # Use ChainInterface which has proper RPC rotation and parsing
                chain_interface = ChainInterfaces().get(chain)
                ethereum_client = EthereumClient(chain_interface.current_rpc)

                code = ethereum_client.w3.eth.get_code(account.address)

                if code and code != b"":
                    continue

                self.key_storage.remove_account(account.address)

                self.create_safe(
                    deployer_tag_or_address="master",
                    owner_tags_or_addresses=account.signers,
                    threshold=account.threshold,
                    chain_name=chain,
                    tag=account.tag,
                )

    def _get_signer_keys(self, safe_account: StoredSafeAccount) -> List[str]:
        """Get signer private keys for a safe (INTERNAL USE ONLY).

        This method is private and should never be called from outside SafeService.
        Keys are used only within execute_safe_transaction and cleared immediately after.
        """
        signer_pkeys = []
        for signer_address in safe_account.signers:
            pkey = self.key_storage._get_private_key(signer_address)
            if pkey:
                signer_pkeys.append(pkey)

        if len(signer_pkeys) < safe_account.threshold:
            raise ValueError(
                "Not enough signer private keys in wallet to meet the Safe's threshold."
            )

        return signer_pkeys

    def _sign_and_execute_safe_tx(
        self,
        safe_tx: SafeTx,
        signer_keys: List[str],
        chain_name: str,
        safe_address: str,
    ) -> str:
        """Sign and execute a SafeTx internally (INTERNAL USE ONLY).

        This method handles the signing and execution of a Safe transaction,
        keeping private keys internal to SafeService.

        Uses SafeTransactionExecutor for retry logic and gas handling.

        SECURITY: Keys are overwritten with zeros and cleared after use.
        """
        from iwa.core.chain import ChainInterfaces
        from iwa.core.services.safe_executor import SafeTransactionExecutor

        try:
            # Sign with all available signers (local operation)
            for pk in signer_keys:
                if pk:
                    safe_tx.sign(pk)

            chain_interface = ChainInterfaces().get(chain_name)
            executor = SafeTransactionExecutor(chain_interface)

            success, tx_hash_or_error, receipt = executor.execute_with_retry(
                safe_address=safe_address,
                safe_tx=safe_tx,
                signer_keys=signer_keys,
                operation_name=f"safe_tx_{safe_address[:10]}",
            )

            if success:
                return tx_hash_or_error
            else:
                raise ValueError(f"Safe transaction failed: {tx_hash_or_error}")

        finally:
            # SECURITY: Overwrite keys with zeros before clearing (best effort)
            for i in range(len(signer_keys)):
                if signer_keys[i]:
                    signer_keys[i] = "0" * len(signer_keys[i])
            signer_keys.clear()

    def execute_safe_transaction(
        self,
        safe_address_or_tag: str,
        to: str,
        value: int,
        chain_name: str,
        data: str = "",
        operation: int = SafeOperationEnum.CALL.value,
    ) -> str:
        """Execute a Safe transaction with internal signing.

        This is the preferred method for executing Safe transactions as it
        handles all signing internally without exposing private keys.

        Args:
            safe_address_or_tag: The Safe account address or tag
            to: Destination address
            value: Amount in wei
            chain_name: Chain name (e.g., 'gnosis')
            data: Transaction data (hex string or empty)
            operation: Safe operation type (CALL or DELEGATE_CALL)

        Returns:
            Transaction hash as hex string

        """
        from iwa.plugins.gnosis.safe import SafeMultisig

        safe_account = self.key_storage.find_stored_account(safe_address_or_tag)
        if not safe_account or not isinstance(safe_account, StoredSafeAccount):
            raise ValueError(f"Safe account '{safe_address_or_tag}' not found.")

        safe = SafeMultisig(safe_account, chain_name)
        safe_tx = safe.build_tx(
            to=to,
            value=value,
            data=data,
            operation=operation,
        )

        # Get signer keys, execute, and immediately clear
        signer_keys = self._get_signer_keys(safe_account)
        tx_hash = self._sign_and_execute_safe_tx(
            safe_tx=safe_tx,
            signer_keys=signer_keys,
            chain_name=chain_name,
            safe_address=safe_account.address,
        )
        logger.info(f"Safe transaction executed. Tx Hash: {tx_hash}")
        return tx_hash

    def get_sign_and_execute_callback(self, safe_address_or_tag: str, chain_name: str):
        """Get a callback function that signs and executes a SafeTx.

        This method returns a callback that can be passed to SafeMultisig.send_tx().
        The callback handles all signing internally.

        Args:
            safe_address_or_tag: The Safe account address or tag
            chain_name: The chain name for context

        Returns:
            A callable that takes a SafeTx and returns the transaction hash

        """
        safe_account = self.key_storage.find_stored_account(safe_address_or_tag)
        if not safe_account or not isinstance(safe_account, StoredSafeAccount):
            raise ValueError(f"Safe account '{safe_address_or_tag}' not found.")

        def _sign_and_execute(safe_tx: SafeTx) -> str:
            signer_keys = self._get_signer_keys(safe_account)
            return self._sign_and_execute_safe_tx(
                safe_tx=safe_tx,
                signer_keys=signer_keys,
                chain_name=chain_name,
                safe_address=safe_account.address,
            )

        return _sign_and_execute
