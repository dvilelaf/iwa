"""Safe service module."""
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from loguru import logger
from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe
from safe_eth.safe.proxy_factory import ProxyFactory

from iwa.core.db import log_transaction
from iwa.core.models import StoredSafeAccount
from iwa.core.settings import settings
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
        deployer_stored_account = self.key_storage.find_stored_account(deployer_tag_or_address)
        if not deployer_stored_account or not isinstance(deployer_stored_account, EncryptedAccount):
            raise ValueError(
                f"Deployer account '{deployer_tag_or_address}' not found or is a Safe."
            )
        # Using internal method _get_private_key via a public accessor check or just access protected member
        # Since SafeService is core, accessing protected _get_private_key is acceptable if we friend it,
        # but KeyStorage doesn't expose it. We should use a method that provides the key or refactor KeyStorage.
        # KeyStorage has get_private_key_unsafe. Let's use that for now or add a friend-like method.
        # Ideally KeyStorage should handle signing deploy tx, but safe-eth-py wants an account object or key.
        from eth_account import Account

        # Accessing protected member is not ideal but KeyStorage is passed in.
        # For now, let's assume we can use _get_private_key or get_private_key_unsafe which logs a warning.
        # But wait, we don't want to log warning for legitimate internal use.
        # Let's use _get_private_key and suppress the "protected member" lint if needed, or better,
        # moving this logic OUT of KeyStorage suggests KeyStorage should expose a "get_signer" or similar.
        # Currently clean usage: accessing private key to create Account object for safe-eth-py.
        deployer_private_key = self.key_storage._get_private_key(deployer_stored_account.address)
        if not deployer_private_key:
             raise ValueError("Deployer private key not available.")
        deployer_account = Account.from_key(deployer_private_key)

        owner_addresses = []
        for tag_or_address in owner_tags_or_addresses:
            owner_stored_account = self.key_storage.find_stored_account(tag_or_address)
            if not owner_stored_account:
                raise ValueError(f"Owner account '{tag_or_address}' not found in wallet.")
            owner_addresses.append(owner_stored_account.address)

        rpc_secret = getattr(settings, f"{chain_name}_rpc")
        ethereum_client = EthereumClient(rpc_secret.get_secret_value())

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
                "0x0000000000000000000000000000000000000000",
                b"",
                "0x0000000000000000000000000000000000000000",
                "0x0000000000000000000000000000000000000000",
                0,
                "0x0000000000000000000000000000000000000000",
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
            contract_address = tx_sent.contract_address
            tx_hash = tx_sent.tx_hash.hex()

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
            contract_address = create_tx.contract_address
            tx_hash = create_tx.tx_hash.hex()

        logger.info(
            f"Safe {tag} [{contract_address}] deployed on {chain_name} on transaction: {tx_hash}"
        )

        # Resolve tag for logging
        resolved_from_tag = self.account_service.get_tag_by_address(deployer_account.address)

        log_transaction(
            tx_hash=tx_hash,
            from_addr=deployer_account.address,
            to_addr=contract_address,
            token="Native",
            amount_wei=0,
            chain=chain_name,
            from_tag=resolved_from_tag or deployer_tag_or_address,
            to_tag=tag,
            tags=["safe-deployment"],
        )

        # Check if already exists
        accounts = self.key_storage.accounts
        if contract_address in accounts and isinstance(
            accounts[contract_address], StoredSafeAccount
        ):
            safe_account = accounts[contract_address]
            if chain_name not in safe_account.chains:
                safe_account.chains.append(chain_name)
        else:
            safe_account = StoredSafeAccount(
                tag=tag or f"Safe {contract_address[:6]}",
                address=contract_address,
                chains=[chain_name],
                threshold=threshold,
                signers=owner_addresses,
            )
            accounts[contract_address] = safe_account

        self.key_storage.save()
        return safe_account, tx_hash

    def redeploy_safes(self):
        """Redeploy all safes to ensure they exist on all chains."""
        for account in list(self.key_storage.accounts.values()):
            if not isinstance(account, StoredSafeAccount):
                continue

            for chain in account.chains:
                rpc_secret = getattr(settings, f"{chain}_rpc")
                ethereum_client = EthereumClient(rpc_secret.get_secret_value())

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

    def get_safe_signer_keys(self, safe_address_or_tag: str) -> List[str]:
        """Get all signer private keys for a safe."""
        safe_account = self.key_storage.find_stored_account(safe_address_or_tag)
        if not safe_account or not isinstance(safe_account, StoredSafeAccount):
            raise ValueError(f"Safe account '{safe_address_or_tag}' not found in wallet.")

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

    def sign_safe_transaction(
        self, safe_address_or_tag: str, signing_callback: Callable[[List[str]], str]
    ) -> str:
        """Sign a Safe transaction internally."""
        stored = self.key_storage.find_stored_account(safe_address_or_tag)
        if not stored or not isinstance(stored, StoredSafeAccount):
            raise ValueError(f"Safe account '{safe_address_or_tag}' not found.")

        signer_pkeys = self.get_safe_signer_keys(safe_address_or_tag)
        try:
            return signing_callback(signer_pkeys)
        finally:
            # Clear the list and references
            for i in range(len(signer_pkeys)):
                signer_pkeys[i] = None
            del signer_pkeys
