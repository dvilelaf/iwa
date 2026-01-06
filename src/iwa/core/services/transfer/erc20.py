"""ERC20 transfer mixin."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.db import log_transaction
from iwa.core.models import StoredSafeAccount

if TYPE_CHECKING:
    from iwa.core.services.transfer import TransferService


class ERC20TransferMixin:
    """Mixin for ERC20 token transfers and approvals."""

    def _send_erc20_via_safe(
        self: "TransferService",
        from_account: StoredSafeAccount,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: Wei,
        chain_name: str,
        erc20: ERC20Contract,
        transaction: dict,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> str:
        """Send ERC20 token via Safe multisig."""
        tx_hash = self.safe_service.execute_safe_transaction(
            safe_address_or_tag=from_address_or_tag,
            to=erc20.address,
            value=0,
            chain_name=chain_name,
            data=transaction["data"],
        )
        # Get receipt for gas calculation
        receipt = None
        try:
            interface = ChainInterfaces().get(chain_name)
            receipt = interface.web3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            logger.warning(f"Could not get receipt for Safe tx {tx_hash}: {e}")

        gas_cost, gas_value_eur = self._calculate_gas_info(receipt, chain_name)
        # Get price and value
        p_eur, v_eur = self._get_token_price_info(token_symbol, amount_wei, chain_name)
        log_transaction(
            tx_hash=tx_hash,
            from_addr=from_account.address,
            to_addr=to_address,
            token=token_symbol,
            amount_wei=amount_wei,
            chain=chain_name,
            from_tag=from_tag,
            to_tag=to_tag,
            gas_cost=gas_cost,
            gas_value_eur=gas_value_eur,
            price_eur=p_eur,
            value_eur=v_eur,
            tags=["erc20-transfer", "safe-transaction"],
        )
        return tx_hash

    def _send_erc20_via_eoa(
        self: "TransferService",
        from_account,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: Wei,
        chain_name: str,
        transaction: dict,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> Optional[str]:
        """Send ERC20 token via EOA (externally owned account)."""
        success, receipt = self.transaction_service.sign_and_send(
            transaction, from_address_or_tag, chain_name
        )
        if success and receipt:
            tx_hash = receipt["transactionHash"].hex()
            gas_cost, gas_value_eur = self._calculate_gas_info(receipt, chain_name)
            p_eur, v_eur = self._get_token_price_info(token_symbol, amount_wei, chain_name)
            log_transaction(
                tx_hash=tx_hash,
                from_addr=from_account.address,
                to_addr=to_address,
                token=token_symbol,
                amount_wei=amount_wei,
                chain=chain_name,
                from_tag=from_tag,
                to_tag=to_tag,
                gas_cost=gas_cost,
                gas_value_eur=gas_value_eur,
                price_eur=p_eur,
                value_eur=v_eur,
                tags=["erc20-transfer"],
            )
            return tx_hash
        return None

    def get_erc20_allowance(
        self: "TransferService",
        owner_address_or_tag: str,
        spender_address: str,
        token_address_or_name: str,
        chain_name: str = "gnosis",
    ) -> Optional[float]:
        """Get ERC20 token allowance."""
        chain = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        owner_account = self.account_service.resolve_account(owner_address_or_tag)
        if not owner_account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.allowance_wei(owner_account.address, spender_address)

    def approve_erc20(
        self: "TransferService",
        owner_address_or_tag: str,
        spender_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: Wei,
        chain_name: str = "gnosis",
    ) -> bool:
        """Approve ERC20 token allowance."""
        owner_account = self.account_service.resolve_account(owner_address_or_tag)
        spender_account = self.account_service.resolve_account(spender_address_or_tag)
        spender_address = spender_account.address if spender_account else spender_address_or_tag

        if not owner_account:
            logger.error(f"Owner account '{owner_address_or_tag}' not found in wallet.")
            return False

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return False

        erc20 = ERC20Contract(token_address, chain_name)

        allowance_wei = self.get_erc20_allowance(
            owner_address_or_tag,
            spender_address,
            token_address_or_name,
            chain_name,
        )
        if allowance_wei is not None and allowance_wei >= amount_wei:
            logger.info("Current allowance is sufficient. No need to approve.")
            return True

        transaction = erc20.prepare_approve_tx(
            from_address=owner_account.address,
            spender=spender_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return False

        is_safe = getattr(owner_account, "threshold", None) is not None
        amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))

        logger.info(
            f"Approving {spender_address} to spend {amount_eth:.4f} {token_address_or_name} from {owner_address_or_tag}"
        )

        if is_safe:
            tx_limit = self.safe_service.execute_safe_transaction(
                safe_address_or_tag=owner_address_or_tag,
                to=erc20.address,
                value=0,
                chain_name=chain_name,
                data=transaction["data"],
            )
            return bool(tx_limit)
        else:
            success, _ = self.transaction_service.sign_and_send(
                transaction, owner_address_or_tag, chain_name
            )
            return success

    def transfer_from_erc20(
        self: "TransferService",
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: Wei,
        chain_name: str = "gnosis",
    ):
        """TransferFrom ERC20 tokens."""
        from_account = self.account_service.resolve_account(from_address_or_tag)
        sender_account = self.account_service.resolve_account(sender_address_or_tag)
        recipient_account = self.account_service.resolve_account(recipient_address_or_tag)
        recipient_address = (
            recipient_account.address if recipient_account else recipient_address_or_tag
        )

        if not sender_account:
            logger.error(f"Sender account '{sender_address_or_tag}' not found in wallet.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return

        erc20 = ERC20Contract(token_address, chain_name)
        transaction = erc20.prepare_transfer_from_tx(
            from_address=from_account.address,
            sender=sender_account.address,
            recipient=recipient_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return

        is_safe = getattr(from_account, "threshold", None) is not None

        logger.info("Transferring ERC20 tokens via TransferFrom")

        if is_safe:
            self.safe_service.execute_safe_transaction(
                safe_address_or_tag=from_address_or_tag,
                to=erc20.address,
                value=0,
                chain_name=chain_name,
                data=transaction["data"],
            )
        else:
            self.transaction_service.sign_and_send(transaction, from_address_or_tag, chain_name)
