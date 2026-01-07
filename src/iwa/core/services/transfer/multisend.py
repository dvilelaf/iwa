"""Multisend and drain mixin."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from safe_eth.safe import SafeOperationEnum

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.contracts.multisend import (
    MULTISEND_ADDRESS,
    MULTISEND_CALL_ONLY_ADDRESS,
    MultiSendCallOnlyContract,
    MultiSendContract,
)
from iwa.core.models import Config, StoredSafeAccount

if TYPE_CHECKING:
    from iwa.core.services.transfer import TransferService


class MultiSendMixin:
    """Mixin for multisend and drain operations."""

    def multi_send(
        self: "TransferService",
        from_address_or_tag: str,
        transactions: list,
        chain_name: str = "gnosis",
    ):
        """Send multiple transactions in a single multisend transaction."""
        from_account = self.account_service.resolve_account(from_address_or_tag)
        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        is_safe = isinstance(from_account, StoredSafeAccount)
        chain_interface = ChainInterfaces().get(chain_name)

        if not is_safe:
            self._handle_erc20_approvals(from_address_or_tag, transactions, chain_interface)

        valid_transactions = []
        for tx in transactions:
            prepared_tx = self._prepare_multisend_transaction(
                tx, from_account, chain_interface, is_safe
            )
            if prepared_tx:
                valid_transactions.append(prepared_tx)

        if not valid_transactions:
            logger.error("No valid transactions to send")
            return

        return self._execute_multisend(
            from_account, from_address_or_tag, valid_transactions, chain_interface, is_safe
        )

    def _handle_erc20_approvals(
        self: "TransferService",
        from_address_or_tag: str,
        transactions: list,
        chain_interface,
    ):
        """Check allowances and approve ERC20s if needed (for EOAs)."""
        from_account = self.account_service.resolve_account(from_address_or_tag)

        if getattr(from_account, "threshold", None) is not None:
            return

        is_all_native = all(
            tx.get("token", NATIVE_CURRENCY_ADDRESS) == NATIVE_CURRENCY_ADDRESS
            for tx in transactions
        )
        if is_all_native:
            return

        erc20_totals = {}
        for tx in transactions:
            token_addr_or_tag = tx.get("token", NATIVE_CURRENCY_ADDRESS)
            if token_addr_or_tag == NATIVE_CURRENCY_ADDRESS:
                continue

            token_address = self.account_service.get_token_address(
                token_addr_or_tag, chain_interface.chain
            )
            # Support both amount_wei (preferred) and amount (legacy)
            if "amount_wei" in tx:
                amount_wei = tx["amount_wei"]
            elif "amount" in tx:
                erc20_temp = ERC20Contract(token_address, chain_interface.chain.name)
                amount_wei = int(tx["amount"] * (10**erc20_temp.decimals))
            else:
                continue
            erc20_totals[token_address] = erc20_totals.get(token_address, 0) + amount_wei

        for token_addr, total_amount in erc20_totals.items():
            self.approve_erc20(
                owner_address_or_tag=from_address_or_tag,
                spender_address_or_tag=MULTISEND_CALL_ONLY_ADDRESS,
                token_address_or_name=token_addr,
                amount_wei=total_amount,
                chain_name=chain_interface.chain.name,
            )

    def _prepare_multisend_transaction(
        self: "TransferService",
        tx: dict,
        from_account,
        chain_interface,
        is_safe: bool,
    ) -> Optional[dict]:
        """Prepare a single transaction for multisend."""
        tx_copy = dict(tx)
        to = self.account_service.resolve_account(tx_copy["to"])
        recipient_address = to.address if to else tx_copy["to"]
        # Ensure recipient address is checksummed for Web3 compatibility
        recipient_address = chain_interface.web3.to_checksum_address(recipient_address)
        token_address_or_tag = tx_copy.get("token", NATIVE_CURRENCY_ADDRESS)
        chain_name = chain_interface.chain.name

        # Prefer amount_wei if provided (no precision loss), else convert from amount
        if "amount_wei" in tx_copy:
            amount_wei = tx_copy["amount_wei"]
        elif "amount" in tx_copy:
            # Calculate amount_wei respecting the token's decimals
            if token_address_or_tag == NATIVE_CURRENCY_ADDRESS:
                amount_wei = chain_interface.web3.to_wei(tx_copy["amount"], "ether")
            else:
                token_address = self.account_service.get_token_address(
                    token_address_or_tag, chain_interface.chain
                )
                erc20_temp = ERC20Contract(token_address, chain_name)
                # Use the token's actual decimals
                amount_wei = int(tx_copy["amount"] * (10**erc20_temp.decimals))
        else:
            logger.error(f"Transaction missing amount or amount_wei: {tx_copy}")
            return None

        # Clean up transaction dict
        tx_copy.pop("amount", None)
        tx_copy.pop("amount_wei", None)
        tx_copy.pop("token", None)

        if token_address_or_tag == NATIVE_CURRENCY_ADDRESS:
            tx_copy["to"] = recipient_address
            tx_copy["value"] = amount_wei
            tx_copy["data"] = b""
            tx_copy["operation"] = SafeOperationEnum.CALL
        else:
            # Create ERC20 contract instance for the transfer
            token_address = self.account_service.get_token_address(
                token_address_or_tag, chain_interface.chain
            )
            erc20 = ERC20Contract(token_address, chain_name)

            if is_safe:
                # Safe uses transfer() because it DelegateCalls the MultiSend (sender identity preserved)
                transfer_tx = erc20.prepare_transfer_tx(
                    from_address=from_account.address,
                    to=recipient_address,
                    amount_wei=amount_wei,
                )
            else:
                # EOA uses transferFrom() because MultiSendCallOnly matches the calls (sender is MultiSend contract)
                transfer_tx = erc20.prepare_transfer_from_tx(
                    from_address=from_account.address,
                    sender=from_account.address,
                    recipient=recipient_address,
                    amount_wei=amount_wei,
                )

            if not transfer_tx:
                logger.error(f"Failed to prepare transfer transaction for {token_address_or_tag}")
                return None

            tx_copy["to"] = erc20.address
            tx_copy["value"] = 0
            tx_copy["data"] = transfer_tx["data"]
            tx_copy["operation"] = SafeOperationEnum.CALL

        return tx_copy

    def _execute_multisend(
        self: "TransferService",
        from_account,
        from_address_or_tag: str,
        valid_transactions: list,
        chain_interface,
        is_safe: bool,
    ):
        """Build and execute the multisend transaction."""
        chain_name = chain_interface.chain.name
        multi_send_normal_contract = MultiSendContract(
            address=MULTISEND_ADDRESS, chain_name=chain_name
        )
        multi_send_call_only_contract = MultiSendCallOnlyContract(
            address=MULTISEND_CALL_ONLY_ADDRESS, chain_name=chain_name
        )

        multi_send_contract = (
            multi_send_normal_contract if is_safe else multi_send_call_only_contract
        )
        transaction = multi_send_contract.prepare_tx(
            from_address=from_account.address, transactions=valid_transactions
        )
        if not transaction:
            return

        logger.info("Sending multisend transaction")

        if is_safe:
            return self.safe_service.execute_safe_transaction(
                safe_address_or_tag=from_address_or_tag,
                to=multi_send_contract.address,
                value=transaction["value"],
                chain_name=chain_name,
                data=transaction["data"],
                operation=SafeOperationEnum.DELEGATE_CALL.value,
            )
        else:
            return self.transaction_service.sign_and_send(
                transaction, from_address_or_tag, chain_name
            )

    def drain(
        self: "TransferService",
        from_address_or_tag: str,
        to_address_or_tag: str = "master",
        chain_name: str = "gnosis",
    ):
        """Drain entire balance of an account to another account.

        For Safes that are Olas service multisigs, this will first claim any
        pending staking rewards before draining.

        Uses multi_send to batch all transfers (ERC20 + native) into a single
        transaction for gas efficiency.
        """
        from_account = self.account_service.resolve_account(from_address_or_tag)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        to_account = self.account_service.resolve_account(to_address_or_tag)
        to_address = to_account.address if to_account else to_address_or_tag

        is_safe = getattr(from_account, "threshold", None) is not None
        chain_interface = ChainInterfaces().get(chain_name)

        # If this is a Safe, check if it's an Olas service multisig and claim rewards
        if is_safe:
            self._claim_olas_rewards_if_service(from_account.address, chain_name)

        transactions = []

        # Collect ERC-20 token transfers
        for token_name in chain_interface.chain.tokens.keys():
            balance_wei = self.balance_service.get_erc20_balance_wei(
                from_address_or_tag, token_name, chain_name
            )
            if balance_wei and balance_wei > 0:
                # Use amount_wei directly for zero precision loss
                transactions.append(
                    {
                        "to": to_address,
                        "amount_wei": balance_wei,
                        "token": token_name,
                    }
                )
                logger.info(f"Queued {balance_wei} wei of {token_name} for drain.")
            else:
                logger.debug(f"No {token_name} to drain on {from_address_or_tag}.")

        # Calculate drainable native balance
        native_balance_wei = self.balance_service.get_native_balance_wei(from_account.address)
        if native_balance_wei and native_balance_wei > 0:
            if is_safe:
                # Safe pays gas from the Safe, so we can drain all
                drainable_balance_wei = native_balance_wei
            else:
                # EOA needs to reserve gas for the multi_send transaction
                # Conservative estimate: base 100k + ~50k per transfer + 20% buffer
                num_transfers = len(transactions) + 1  # +1 for native
                estimated_gas = 100_000 + (50_000 * num_transfers)
                gas_price = chain_interface.web3.eth.gas_price
                gas_cost_wei = int(gas_price * estimated_gas * 1.2)  # 20% buffer
                drainable_balance_wei = native_balance_wei - gas_cost_wei
                logger.debug(
                    f"EOA drain: balance={native_balance_wei}, gas_reserve={gas_cost_wei}, "
                    f"drainable={drainable_balance_wei}"
                )

            if drainable_balance_wei > 0:
                # Use amount_wei directly for zero precision loss
                transactions.append(
                    {
                        "to": to_address,
                        "amount_wei": drainable_balance_wei,
                        # No "token" key = native currency
                    }
                )
                logger.info(f"Queued {drainable_balance_wei} wei native for drain.")
            else:
                logger.info(
                    f"Not enough native balance to cover gas fees for draining from {from_address_or_tag}."
                )

        if not transactions:
            logger.info(f"Nothing to drain from {from_address_or_tag}.")
            return

        logger.info(
            f"Draining {len(transactions)} assets from {from_address_or_tag} to {to_address_or_tag}..."
        )
        return self.multi_send(
            from_address_or_tag=from_address_or_tag,
            transactions=transactions,
            chain_name=chain_name,
        )

    def _claim_olas_rewards_if_service(self, safe_address: str, chain_name: str) -> bool:
        """Check if Safe is an Olas service multisig and claim pending rewards.

        This is a best-effort operation - if the Olas plugin is not available or
        there's an error, it will log a warning and continue without failing.

        Args:
            safe_address: The Safe address to check.
            chain_name: The chain name.

        Returns:
            True if rewards were claimed, False otherwise.

        """
        try:
            # Import Olas plugin (optional dependency)
            from iwa.plugins.olas.models import OlasConfig

            # Check if this Safe is an Olas service multisig
            config = Config()
            if "olas" not in config.plugins:
                return False

            olas_config: OlasConfig = config.plugins["olas"]
            service = olas_config.get_service_by_multisig(safe_address)

            if not service:
                logger.debug(f"Safe {safe_address} is not an Olas service multisig.")
                return False

            if not service.staking_contract_address:
                logger.debug(f"Olas service {service.key} is not staked.")
                return False

            logger.info(
                f"Safe {safe_address} is Olas service {service.key}. "
                "Checking for pending staking rewards..."
            )

            # Use ServiceManager to claim rewards
            # Need to import Wallet dynamically to avoid circular import
            from iwa.core.wallet import Wallet
            from iwa.plugins.olas.service_manager import ServiceManager

            wallet = Wallet()
            service_manager = ServiceManager(wallet=wallet, service_key=service.key)
            success, claimed_amount = service_manager.claim_rewards()

            if success and claimed_amount > 0:
                claimed_olas = claimed_amount / 1e18
                logger.info(f"Claimed {claimed_olas:.4f} OLAS rewards before drain.")
                return True
            elif not success:
                logger.debug("No rewards to claim or claim failed.")

            return False

        except ImportError:
            logger.debug("Olas plugin not available, skipping reward claiming.")
            return False
        except Exception as e:
            logger.warning(f"Failed to check/claim Olas rewards: {e}")
            return False
