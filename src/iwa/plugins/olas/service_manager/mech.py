"""Mech manager mixin.

This module handles sending mech requests for OLAS services. There are THREE
distinct flows for mech requests, and the correct one is automatically selected
based on the service's staking contract configuration:

Flow Selection Logic:
    1. `get_marketplace_config()` checks if staking contract's activity checker
       has a non-zero `mechMarketplace` address
    2. If yes → marketplace request (v1 or v2 depending on address)
    3. If no → legacy mech request

┌─────────────────────────────────────────────────────────────────────────────┐
│ FLOW 1: Legacy Mech (use_marketplace=False)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Contract:    Legacy Mech (0x77af31De...)                                    │
│ Used by:     NON-MM staking contracts (e.g., "Expert X (Yk OLAS)")          │
│ Counting:    agentMech.getRequestsCount(multisig)                           │
│ Method:      _send_legacy_mech_request()                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ FLOW 2: Marketplace v2 (use_marketplace=True, marketplace=0x735F...)        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Contract:    MechMarketplace v2 (0x735FAAb1c...)                            │
│ Used by:     Newer MM staking contracts                                     │
│ Counting:    mechMarketplace.mapRequestCounts(multisig)                     │
│ Method:      _send_marketplace_mech_request() → MechMarketplaceContract     │
│ Signature:   request(bytes,uint256,bytes32,address,uint256,bytes)           │
│ Note:        Uses payment types (PAYMENT_TYPE_NATIVE)                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ FLOW 3: Marketplace v1 (use_marketplace=True, marketplace=0x4554...)        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Contract:    MechMarketplace v1 (0x4554fE75...)  [VERSION 1.0.0]            │
│ Used by:     Older MM contracts (e.g., "Expert 17 MM", trader_ant)          │
│ Counting:    mechMarketplace.mapRequestCounts(multisig)                     │
│ Method:      _send_v1_marketplace_request() → MechMarketplaceV1Contract     │
│ Signature:   request(bytes,address,address,uint256,address,uint256,uint256) │
│ Note:        Requires staking instance + service ID for mech AND requester  │
│              No payment types - simpler but different parameter set         │
└─────────────────────────────────────────────────────────────────────────────┘

Important:
    If a service is staked in an MM contract but sends requests to the wrong
    marketplace (or uses legacy flow), those requests will NOT be counted by
    the activity checker, and the service will not receive staking rewards.

The dispatch logic:
    1. _send_marketplace_mech_request() checks if marketplace ∈ V1_MARKETPLACES
    2. If v1 → dispatches to _send_v1_marketplace_request()
    3. If v2 → continues with MechMarketplaceContract (v2 ABI)

"""

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
from iwa.plugins.olas.contracts.mech_marketplace_v1 import (
    MechMarketplaceV1Contract,
    V1RequestParams,
)

# Maps marketplace address to (priority_mech_address, priority_mech_service_id, mech_staking_instance)
# Source: olas-operate-middleware profiles.py and manage.py
# The 3rd element (staking instance) is only needed for v1 marketplaces
DEFAULT_PRIORITY_MECH = {
    "0x4554fE75c1f5576c1d7F765B2A036c199Adae329": (
        "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053",
        975,
        "0x998dEFafD094817EF329f6dc79c703f1CF18bC90",  # Mech staking instance for v1
    ),
    "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB": (
        "0xC05e7412439bD7e91730a6880E18d5D5873F632C",
        2182,
        None,  # v2 doesn't need staking instance
    ),
}

# Marketplace v1 addresses (use different request signature)
V1_MARKETPLACES = {
    "0x4554fE75c1f5576c1d7F765B2A036c199Adae329",  # VERSION 1.0.0
}


class MechManagerMixin:
    """Mixin for Mech interactions."""

    def get_marketplace_config(self) -> tuple:
        """Check if current service requires marketplace mech requests.

        Queries the staking contract's activityChecker to determine if it
        tracks marketplace requests.

        Returns:
            Tuple of (use_marketplace, marketplace_address, priority_mech):
                - use_marketplace: True if marketplace requests are required.
                - marketplace_address: Address of the mech marketplace (if applicable).
                - priority_mech: Address of the priority mech (if applicable).

        """
        from iwa.core.constants import ZERO_ADDRESS

        if not self.service or not self.service.staking_contract_address:
            return (False, None, None)

        try:
            # Get staking contract with its activity checker
            from iwa.plugins.olas.contracts.staking import StakingContract

            staking = StakingContract(
                self.service.staking_contract_address, chain_name=self.chain_name
            )

            # StakingContract has activity_checker attribute set in __init__
            checker = staking.activity_checker

            if checker.mech_marketplace and checker.mech_marketplace != ZERO_ADDRESS:
                # Get priority mech from mapping based on marketplace address
                marketplace_addr = Web3.to_checksum_address(checker.mech_marketplace)
                priority_mech_info = DEFAULT_PRIORITY_MECH.get(marketplace_addr)

                if priority_mech_info:
                    priority_mech = priority_mech_info[0]  # First element is mech address
                else:
                    # Fallback to constants if marketplace not in mapping
                    protocol_contracts = OLAS_CONTRACTS.get(self.chain_name, {})
                    priority_mech = protocol_contracts.get("OLAS_MECH_MARKETPLACE_PRIORITY")
                    logger.warning(
                        f"[MECH] Marketplace {marketplace_addr} not in DEFAULT_PRIORITY_MECH, "
                        f"using fallback priority_mech: {priority_mech}"
                    )

                logger.info(
                    f"[MECH] Service {self.service.service_id} requires marketplace requests "
                    f"(marketplace={marketplace_addr}, priority_mech={priority_mech})"
                )
                return (True, marketplace_addr, priority_mech)

            return (False, None, None)

        except Exception as e:
            logger.debug(f"[MECH] Failed to detect marketplace config: {e}")
            return (False, None, None)

    def send_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        mech_address: Optional[str] = None,
        use_marketplace: Optional[bool] = None,
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
                             If None, auto-detects based on staking contract.
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

        # Auto-detect marketplace requirement if not explicitly specified
        detected_marketplace = None
        if use_marketplace is None:
            use_marketplace, detected_marketplace, detected_priority_mech = (
                self.get_marketplace_config()
            )
            if use_marketplace:
                priority_mech = priority_mech or detected_priority_mech
                mech_address = mech_address or detected_marketplace

        if use_marketplace:
            # Use detected marketplace if available, otherwise _send_marketplace_mech_request
            # will fall back to constant
            return self._send_marketplace_mech_request(
                data=data,
                value=value,
                marketplace_address=detected_marketplace,
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
        """Validate priority mech is registered on marketplace.

        Note: OLD marketplace v1 (0x4554...) doesn't have checkMech function.
        In that case, we skip validation and proceed - v1 doesn't require
        mech registration.
        """
        try:
            mech_multisig = marketplace.call("checkMech", priority_mech)
            if mech_multisig == ZERO_ADDRESS:
                logger.error(f"Priority mech {priority_mech} is NOT registered on marketplace")
                return False
            logger.debug(f"Priority mech {priority_mech} -> multisig {mech_multisig}")
        except Exception as e:
            # Check if this is a revert (v1 doesn't have checkMech) vs a network error
            error_str = str(e).lower()
            if "reverted" in error_str or "execution reverted" in error_str:
                # v1 marketplaces don't have checkMech - skip validation
                logger.warning(
                    f"Could not validate priority mech (marketplace may be v1): {e}. "
                    "Proceeding without validation."
                )
                return True
            else:
                # Real error (network, timeout, etc.) - fail validation
                logger.error(f"Failed to validate priority mech (network error?): {e}")
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
        """Validate marketplace parameters.

        Note: v1 marketplaces may not have all validation functions.
        We proceed with warnings when validation functions are unavailable.
        """
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

        # Validate payment type has balance tracker (v2 only)
        try:
            balance_tracker = marketplace.call("mapPaymentTypeBalanceTrackers", payment_type)
            if balance_tracker == ZERO_ADDRESS:
                # This is a validation failure for v2 - return False
                logger.error(
                    f"No balance tracker for payment type 0x{payment_type.hex()}. "
                    "This is required for v2 marketplace requests."
                )
                return False
            else:
                logger.debug(f"Payment type balance tracker: {balance_tracker}")
        except Exception as e:
            # Check if this is a revert (v1 doesn't have this function) vs a network error
            error_str = str(e).lower()
            if "reverted" in error_str or "execution reverted" in error_str:
                # v1 marketplaces don't have mapPaymentTypeBalanceTrackers - skip
                logger.warning(
                    f"Could not validate payment type (marketplace may be v1): {e}. "
                    "Proceeding without validation."
                )
            else:
                # Real error - fail validation
                logger.error(f"Failed to validate payment type (network error?): {e}")
                return False

        return True

    def _resolve_marketplace_config(
        self, marketplace_addr: Optional[str], priority_addr: Optional[str]
    ) -> tuple[str, str]:
        """Resolve marketplace and priority mech addresses. Returns (marketplace, priority)."""
        chain_name = self.chain_name if self.service else getattr(self, "chain_name", "gnosis")
        protocol_contracts = OLAS_CONTRACTS.get(chain_name, {})

        resolved_mp = marketplace_addr or protocol_contracts.get("OLAS_MECH_MARKETPLACE_V2")
        if not resolved_mp:
            raise ValueError(f"Mech Marketplace address not found for chain {chain_name}")

        if not priority_addr:
            raise ValueError("priority_mech is required for marketplace requests")

        return str(resolved_mp), Web3.to_checksum_address(priority_addr)

    def _prepare_marketplace_params(
        self,
        value: Optional[int],
        max_delivery_rate: Optional[int],
        payment_type: Optional[bytes],
    ) -> tuple[int, int, bytes]:
        """Prepare default values for marketplace parameters."""
        p_type = payment_type or bytes.fromhex(PAYMENT_TYPE_NATIVE)
        val = value if value is not None else 10_000_000_000_000_000
        rate = max_delivery_rate if max_delivery_rate is not None else val
        return val, rate, p_type

    def _send_marketplace_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        priority_mech: Optional[str] = None,
        marketplace_address: Optional[str] = None,
        max_delivery_rate: Optional[int] = None,
        payment_type: Optional[bytes] = None,
        payment_data: bytes = b"",
        response_timeout: int = 300,
    ) -> Optional[str]:
        """Send a marketplace mech request with validation.

        Args:
            data: Request data payload (bytes).
            value: Native currency value to send with request (wei).
            priority_mech: Priority mech address for request processing.
            marketplace_address: The marketplace contract address from activity checker.
                                 If None, falls back to OLAS_MECH_MARKETPLACE_V2 constant.
            max_delivery_rate: Maximum delivery rate for the mech.
            payment_type: Payment type bytes32 (defaults to PAYMENT_TYPE_NATIVE).
            payment_data: Additional payment data.
            response_timeout: Timeout for response in seconds.

        Returns:
            Transaction hash if successful, None otherwise.

        """
        if not self.service:
            logger.error("No active service")
            return None

        try:
            marketplace_address, priority_mech = self._resolve_marketplace_config(
                marketplace_address, priority_mech
            )
        except ValueError as e:
            logger.error(e)
            return None

        # Dispatch to v1 handler if marketplace is v1
        if marketplace_address in V1_MARKETPLACES:
            return self._send_v1_marketplace_request(
                data=data,
                marketplace_address=marketplace_address,
                priority_mech=priority_mech,
                response_timeout=response_timeout,
                value=value,
            )

        # v2 flow
        marketplace = MechMarketplaceContract(marketplace_address, chain_name=self.chain_name)

        if not self._validate_priority_mech(marketplace, priority_mech):
            return None

        # Set defaults for payment and delivery
        value, max_delivery_rate, payment_type = self._prepare_marketplace_params(
            value, max_delivery_rate, payment_type
        )

        if not self._validate_marketplace_params(marketplace, response_timeout, payment_type):
            return None

        # Prepare transaction
        tx_data = marketplace.prepare_request_tx(
            from_address=self.service.multisig_address,
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

    def _send_v1_marketplace_request(
        self,
        data: bytes,
        marketplace_address: str,
        priority_mech: str,
        response_timeout: int = 300,
        value: Optional[int] = None,
    ) -> Optional[str]:
        """Send a v1 marketplace mech request.

        v1 marketplace (VERSION 1.0.0) requires staking instance and service ID
        for both the mech and the requester, unlike v2 which uses payment types.
        """
        if not self.service:
            logger.error("No active service")
            return None

        # Get mech info from DEFAULT_PRIORITY_MECH (now a 3-tuple)
        mech_info = DEFAULT_PRIORITY_MECH.get(marketplace_address)
        if not mech_info or len(mech_info) < 3:
            logger.error(f"No priority mech info for v1 marketplace {marketplace_address}")
            return None

        priority_mech_address, priority_mech_service_id, priority_mech_staking = mech_info

        if not priority_mech_staking:
            logger.error(f"No mech staking instance for v1 marketplace {marketplace_address}")
            return None

        # Get requester staking info from current service
        requester_staking_instance = self.service.staking_contract_address
        requester_service_id = self.service.service_id

        if not requester_staking_instance:
            logger.error("No staking contract for current service (required for v1)")
            return None

        # Build v1 request params
        params = V1RequestParams(
            data=data,
            priority_mech=priority_mech_address,
            priority_mech_staking_instance=priority_mech_staking,
            priority_mech_service_id=priority_mech_service_id,
            requester_staking_instance=requester_staking_instance,
            requester_service_id=requester_service_id,
            response_timeout=response_timeout,
            value=value or 10_000_000_000_000_000,  # 0.01 xDAI default
        )

        logger.info(
            f"[MECH-V1] Sending v1 marketplace request to {marketplace_address} "
            f"(mech={priority_mech_address}, mech_svc={priority_mech_service_id})"
        )

        marketplace = MechMarketplaceV1Contract(marketplace_address, chain_name=self.chain_name)
        tx_data = marketplace.prepare_request_tx(
            from_address=self.service.multisig_address,
            params=params,
        )

        if not tx_data:
            logger.error("Failed to prepare v1 marketplace request transaction")
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
            tx_hash = Web3.to_hex(receipt.get("transactionHash")) if success else None

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

                # Log transfer events from receipt
                from iwa.core.services.transaction import TransferLogger

                transfer_logger = TransferLogger(
                    self.wallet.account_service, self.registry.chain_interface
                )
                transfer_logger.log_transfers(receipt)

                return tx_hash
            else:
                logger.error(f"Event '{expected_event}' NOT found in transaction logs")
                logger.debug(f"Found events: {[e['name'] for e in events]}")
                return None
        except Exception as e:
            logger.error(f"Error verifying event emission: {e}")
            return None
