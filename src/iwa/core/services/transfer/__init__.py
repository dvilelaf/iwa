"""Transfer service package."""

from typing import Optional

from loguru import logger
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.contracts.multisend import (
    MultiSendCallOnlyContract,
    MultiSendContract,
)
from iwa.core.models import StoredSafeAccount
from iwa.core.services.transfer.base import TransferServiceBase
from iwa.core.services.transfer.erc20 import ERC20TransferMixin
from iwa.core.services.transfer.multisend import MultiSendMixin
from iwa.core.services.transfer.native import NativeTransferMixin
from iwa.core.services.transfer.swap import SwapMixin
from iwa.plugins.gnosis.cow import CowSwap, OrderType

__all__ = [
    "TransferService",
    # Re-export for backward compatibility
    "MultiSendCallOnlyContract",
    "MultiSendContract",
    "StoredSafeAccount",
    "CowSwap",
    "OrderType",
    "ERC20Contract",
]


class TransferService(
    NativeTransferMixin, ERC20TransferMixin, MultiSendMixin, SwapMixin, TransferServiceBase
):
    """Service for handling transfers, swaps, and approvals.

    Composed of mixins for specific functionalities:
    - NativeTransferMixin: Native currency transfers and wrapping
    - ERC20TransferMixin: ERC20 tokens transfers and approvals
    - MultiSendMixin: Batch transactions and draining
    - SwapMixin: CowSwap integration
    - TransferServiceBase: Shared implementations and helpers
    """

    def send(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str,
        amount_wei: Wei,
        token_address_or_name: str = "native",
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Send native currency or ERC20 token.

        Args:
            from_address_or_tag: Source account address or tag
            to_address_or_tag: Destination address or tag
            amount_wei: Amount in wei
            token_address_or_name: Token address, name, or "native"
            chain_name: Chain name (default: "gnosis")

        Returns:
            Transaction hash if successful, None otherwise.

        """
        # Resolve accounts
        from_account = self.account_service.resolve_account(from_address_or_tag)
        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return None

        to_address, to_tag = self._resolve_destination(to_address_or_tag)
        if not to_address:
            return None

        # SECURITY: Validate destination is whitelisted
        if not self._is_whitelisted_destination(to_address):
            return None

        # SECURITY: Validate token is supported
        if not self._is_supported_token(token_address_or_name, chain_name):
            return None

        # Resolve chain and token
        chain_interface = ChainInterfaces().get(chain_name)
        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return None

        # Resolve tags and symbols for logging
        from_tag = self.account_service.get_tag_by_address(from_account.address)
        token_symbol = self._resolve_token_symbol(
            token_address, token_address_or_name, chain_interface
        )
        is_safe = getattr(from_account, "threshold", None) is not None

        # Native currency transfer
        if token_address == NATIVE_CURRENCY_ADDRESS:
            amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))
            logger.info(
                f"Sending {amount_eth:.4f} {chain_interface.chain.native_currency} "
                f"from {from_address_or_tag} to {to_address_or_tag}"
            )
            if is_safe:
                return self._send_native_via_safe(
                    from_account,
                    from_address_or_tag,
                    to_address,
                    amount_wei,
                    chain_name,
                    from_tag,
                    to_tag,
                    token_symbol,
                )
            return self._send_native_via_eoa(
                from_account,
                to_address,
                amount_wei,
                chain_name,
                chain_interface,
                from_tag,
                to_tag,
                token_symbol,
            )

        # ERC20 token transfer
        erc20 = ERC20Contract(token_address, chain_name)
        transaction = erc20.prepare_transfer_tx(from_account.address, to_address, amount_wei)
        if not transaction:
            return None

        amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))
        logger.info(
            f"Sending {amount_eth:.4f} {token_address_or_name} "
            f"from {from_address_or_tag} to {to_address_or_tag}"
        )

        if is_safe:
            return self._send_erc20_via_safe(
                from_account,
                from_address_or_tag,
                to_address,
                amount_wei,
                chain_name,
                erc20,
                transaction,
                from_tag,
                to_tag,
                token_symbol,
            )
        return self._send_erc20_via_eoa(
            from_account,
            from_address_or_tag,
            to_address,
            amount_wei,
            chain_name,
            transaction,
            from_tag,
            to_tag,
            token_symbol,
        )
