"""Mech manager mixin."""

from typing import Optional

from loguru import logger
from web3 import Web3

from iwa.core.constants import ZERO_ADDRESS
from iwa.plugins.olas.constants import (
    OLAS_CONTRACTS,
    PAYMENT_TYPE_NATIVE,
)
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract


class MechManagerMixin:
    """Mixin for Mech interactions."""

    def send_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        mech_address: Optional[str] = None,
        use_marketplace: bool = False,
        use_new_abi: bool = False,
        priority_mech: Optional[str] = None,
        max_delivery_rate: Optional[int] = None,
        payment_type: Optional[bytes] = None,
        payment_data: bytes = b"",
        response_timeout: int = 300,
    ) -> Optional[str]:
        """Send a Mech request from the service multisig.

        Args:
            data: The request data (IPFS hash bytes).
            value: Payment value in wei. For marketplace, should match mech's maxDeliveryRate.
            mech_address: Address of the Mech contract (for legacy/direct flow).
            use_marketplace: Whether to use the Mech Marketplace flow.
            use_new_abi: Whether to use new ABI for legacy flow.
            priority_mech: Priority mech address (required for marketplace).
            max_delivery_rate: Max delivery rate in wei (for marketplace). If None, uses value.
            payment_type: Payment type bytes32 (for marketplace). Defaults to NATIVE.
            payment_data: Payment data (for marketplace).
            response_timeout: Timeout in seconds for marketplace request (60-300).

        Returns:
            The transaction hash if successful, None otherwise.

        """
        if not self.service:
            logger.error("No active service loaded")
            return None

        service_id = self.service.service_id
        multisig_address = self.service.multisig_address

        if not multisig_address:
            logger.error(f"Service {service_id} has no multisig address")
            return None

        if use_marketplace:
            return self._send_marketplace_mech_request(
                data=data,
                value=value,
                priority_mech=priority_mech,
                max_delivery_rate=max_delivery_rate,
                payment_type=payment_type,
                payment_data=payment_data,
                response_timeout=response_timeout,
            )
        else:
            return self._send_legacy_mech_request(
                data=data,
                value=value,
                mech_address=mech_address,
                use_new_abi=use_new_abi,
            )

    def _send_legacy_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        mech_address: Optional[str] = None,
        use_new_abi: bool = False,
    ) -> Optional[str]:
        """Send a legacy (direct) mech request."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        protocol_contracts = OLAS_CONTRACTS.get(self.chain_name, {})
        mech_address = mech_address or protocol_contracts.get("OLAS_MECH")

        if not mech_address:
            logger.error(f"Legacy mech address not found for chain {self.chain_name}")
            return None

        mech = MechContract(str(mech_address), chain_name=self.chain_name, use_new_abi=use_new_abi)

        # Get mech price if value not provided
        if value is None:
            value = mech.get_price()
            logger.info(f"Using mech price: {value} wei")

        tx_data = mech.prepare_request_tx(
            from_address=multisig_address,
            data=data,
            value=value,
        )

        if not tx_data:
            logger.error("Failed to prepare legacy mech request transaction")
            return None

        return self._execute_mech_tx(
            tx_data=tx_data,
            to_address=str(mech_address),
            contract_instance=mech,
            expected_event="Request",
        )

    def _validate_priority_mech(self, marketplace, priority_mech: str) -> bool:
        """Validate priority mech is registered on marketplace."""
        try:
            mech_multisig = marketplace.call("checkMech", priority_mech)
            if mech_multisig == ZERO_ADDRESS:
                logger.error(f"Priority mech {priority_mech} is NOT registered on marketplace")
                return False
            logger.debug(f"Priority mech {priority_mech} -> multisig {mech_multisig}")
        except Exception as e:
            logger.error(f"Failed to verify priority mech registration: {e}")
            return False

        # Log mech factory info (optional validation)
        try:
            mech_factory = marketplace.call("mapAgentMechFactories", priority_mech)
            if mech_factory == ZERO_ADDRESS:
                logger.warning(
                    f"Priority mech {priority_mech} has no factory (may be unregistered)"
                )
            else:
                logger.debug(f"Priority mech factory: {mech_factory}")
        except Exception as e:
            logger.warning(f"Could not fetch mech factory: {e}")

        return True

    def _validate_marketplace_params(
        self, marketplace, response_timeout: int, payment_type: bytes
    ) -> bool:
        """Validate marketplace parameters."""
        # Validate response_timeout bounds
        try:
            min_timeout = marketplace.call("minResponseTimeout")
            max_timeout = marketplace.call("maxResponseTimeout")
            if response_timeout < min_timeout or response_timeout > max_timeout:
                logger.error(
                    f"response_timeout {response_timeout} out of bounds [{min_timeout}, {max_timeout}]"
                )
                return False
            logger.debug(
                f"Response timeout {response_timeout}s within bounds [{min_timeout}, {max_timeout}]"
            )
        except Exception as e:
            logger.warning(f"Could not validate response_timeout bounds: {e}")

        # Validate payment type has balance tracker
        try:
            balance_tracker = marketplace.call("mapPaymentTypeBalanceTrackers", payment_type)
            if balance_tracker == ZERO_ADDRESS:
                logger.error(f"No balance tracker for payment type 0x{payment_type.hex()}")
                return False
            logger.debug(f"Payment type balance tracker: {balance_tracker}")
        except Exception as e:
            logger.warning(f"Could not validate payment type: {e}")

        return True

    def _send_marketplace_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        priority_mech: Optional[str] = None,
        max_delivery_rate: Optional[int] = None,
        payment_type: Optional[bytes] = None,
        payment_data: bytes = b"",
        response_timeout: int = 300,
    ) -> Optional[str]:
        """Send a marketplace mech request with validation."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        chain_name = self.chain_name if self.service else getattr(self, "chain_name", "gnosis")
        protocol_contracts = OLAS_CONTRACTS.get(chain_name, {})
        marketplace_address = protocol_contracts.get("OLAS_MECH_MARKETPLACE")

        if not marketplace_address:
            logger.error(f"Mech Marketplace address not found for chain {chain_name}")
            return None

        if not priority_mech:
            logger.error("priority_mech is required for marketplace requests")
            return None

        priority_mech = Web3.to_checksum_address(priority_mech)
        marketplace = MechMarketplaceContract(str(marketplace_address), chain_name=chain_name)

        if not self._validate_priority_mech(marketplace, priority_mech):
            return None

        # Set defaults for payment
        if payment_type is None:
            payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        if value is None:
            value = 10_000_000_000_000_000
            logger.info(f"Using default value: {value} wei (0.01 xDAI)")

        if max_delivery_rate is None:
            max_delivery_rate = value
            logger.info(f"Using value as max_delivery_rate: {max_delivery_rate}")

        if not self._validate_marketplace_params(marketplace, response_timeout, payment_type):
            return None

        # Prepare transaction
        tx_data = marketplace.prepare_request_tx(
            from_address=multisig_address,
            request_data=data,
            priority_mech=priority_mech,
            response_timeout=response_timeout,
            max_delivery_rate=max_delivery_rate,
            payment_type=payment_type,
            payment_data=payment_data,
            value=value,
        )

        if not tx_data:
            logger.error("Failed to prepare marketplace request transaction")
            return None

        return self._execute_mech_tx(
            tx_data=tx_data,
            to_address=str(marketplace_address),
            contract_instance=marketplace,
            expected_event="MarketplaceRequest",
        )

    def _execute_mech_tx(
        self,
        tx_data: dict,
        to_address: str,
        contract_instance,
        expected_event: str,
    ) -> Optional[str]:
        """Execute a mech transaction and verify the event."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        tx_value = int(tx_data.get("value", 0))

        from iwa.core.models import StoredSafeAccount

        sender_account = self.wallet.account_service.resolve_account(str(multisig_address))
        is_safe = isinstance(sender_account, StoredSafeAccount)

        if is_safe:
            logger.info(f"Sending mech request via Safe {multisig_address} (value: {tx_value} wei)")
            try:
                tx_hash = self.wallet.safe_service.execute_safe_transaction(
                    safe_address_or_tag=str(multisig_address),
                    to=to_address,
                    value=tx_value,
                    chain_name=self.chain_name,
                    data=tx_data["data"],
                )
            except Exception as e:
                logger.error(f"Safe transaction failed: {e}")
                return None
        else:
            logger.info(f"Sending mech request via EOA {multisig_address} (value: {tx_value} wei)")
            tx = {
                "to": to_address,
                "value": tx_value,
                "data": tx_data["data"],
            }
            success, receipt = self.wallet.sign_and_send_transaction(
                transaction=tx,
                signer_address_or_tag=str(multisig_address),
                chain_name=self.chain_name,
                tags=["olas_mech_request"],
            )
            tx_hash = receipt.get("transactionHash").hex() if success else None

        if not tx_hash:
            logger.error("Failed to send mech request transaction")
            return None

        logger.info(f"Mech request transaction sent: {tx_hash}")

        # Verify event emission
        try:
            receipt = self.registry.chain_interface.web3.eth.wait_for_transaction_receipt(tx_hash)
            events = contract_instance.extract_events(receipt)
            event_found = next((e for e in events if e["name"] == expected_event), None)

            if event_found:
                logger.info(f"Event '{expected_event}' verified successfully")
                return tx_hash
            else:
                logger.error(f"Event '{expected_event}' NOT found in transaction logs")
                logger.debug(f"Found events: {[e['name'] for e in events]}")
                return None
        except Exception as e:
            logger.error(f"Error verifying event emission: {e}")
            return None
