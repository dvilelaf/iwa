"""Activity checker contract interaction.

The MechActivityChecker contract tracks liveness for staked services by monitoring:
- Safe multisig transaction nonces
- Mech request counts

The liveness check (isRatioPass) verifies that the service is making enough mech
requests relative to the time elapsed since the last checkpoint.
"""

from typing import Optional, Tuple

from iwa.core.constants import DEFAULT_MECH_CONTRACT_ADDRESS
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH, ContractInstance


class ActivityCheckerContract(ContractInstance):
    """Class to interact with the MechActivityChecker contract.

    This contract tracks mech request activity for staked services and determines
    if they meet the liveness requirements for staking rewards.

    The getMultisigNonces() function returns an array with two values:
        - nonces[0]: Safe multisig nonce (total transaction count)
        - nonces[1]: Mech requests count (from AgentMech.getRequestsCount)

    The isRatioPass() function checks if:
        1. diffRequestsCounts <= diffNonces (requests can't exceed txs)
        2. ratio = (diffRequestsCounts * 1e18) / time >= livenessRatio
    """

    name = "activity_checker"
    abi_path = OLAS_ABI_PATH / "activity_checker.json"

    def __init__(self, address: EthereumAddress, chain_name: str = "gnosis"):
        """Initialize ActivityCheckerContract.

        Args:
            address: The activity checker contract address.
            chain_name: The chain name (default: gnosis).

        """
        super().__init__(address, chain_name=chain_name)

        # Cache for lazy loading
        self._mech_marketplace: Optional[EthereumAddress] = None
        self._agent_mech: Optional[EthereumAddress] = None
        self._liveness_ratio: Optional[int] = None

    def get_multisig_nonces(self, multisig: EthereumAddress) -> Tuple[int, int]:
        """Get the nonces for a multisig address.

        Args:
            multisig: The multisig address to check.

        Returns:
            Tuple of (safe_nonce, mech_requests_count):
                - safe_nonce: Total Safe transaction count
                - mech_requests_count: Total mech requests made

        """
        nonces = self.contract.functions.getMultisigNonces(multisig).call()
        return (nonces[0], nonces[1])

    @property
    def mech_marketplace(self) -> Optional[EthereumAddress]:
        """Get the mech marketplace address."""
        if self._mech_marketplace is None:
            try:
                mech_mp_function = getattr(self.contract.functions, "mechMarketplace", None)
                self._mech_marketplace = mech_mp_function().call() if mech_mp_function else None
            except Exception:
                self._mech_marketplace = None
        return self._mech_marketplace

    @property
    def agent_mech(self) -> EthereumAddress:
        """Get the agent mech address."""
        if self._agent_mech is None:
            try:
                agent_mech_function = getattr(self.contract.functions, "agentMech", None)
                self._agent_mech = (
                    agent_mech_function().call()
                    if agent_mech_function
                    else DEFAULT_MECH_CONTRACT_ADDRESS
                )
            except Exception:
                self._agent_mech = DEFAULT_MECH_CONTRACT_ADDRESS
        return self._agent_mech

    @property
    def liveness_ratio(self) -> int:
        """Get the liveness ratio."""
        if self._liveness_ratio is None:
            try:
                self._liveness_ratio = self.contract.functions.livenessRatio().call()
            except Exception:
                self._liveness_ratio = 0
        return self._liveness_ratio

    def is_ratio_pass(
        self,
        current_nonces: Tuple[int, int],
        last_nonces: Tuple[int, int],
        ts_diff: int,
    ) -> bool:
        """Check if the liveness ratio requirement is passed.

        The formula checks:
        1. diffRequestsCounts <= diffNonces (mech requests can't exceed total txs)
        2. ratio = (diffRequestsCounts * 1e18) / ts_diff >= livenessRatio

        Args:
            current_nonces: Current (safe_nonce, mech_requests_count).
            last_nonces: Nonces at last checkpoint (safe_nonce, mech_requests_count).
            ts_diff: Time difference in seconds since last checkpoint.

        Returns:
            True if liveness requirements are met.

        """
        # Optimized implementation to avoid RPC call
        current_safe, current_requests = current_nonces
        last_safe, last_requests = last_nonces

        diff_safe = current_safe - last_safe
        diff_requests = current_requests - last_requests

        # 1. Check if requests exceed transactions (impossible in valid operation)
        # Also check for negative diffs (data corruption/stale data edge case)
        if diff_requests > diff_safe or diff_requests < 0 or diff_safe < 0:
            return False

        # 2. Check time difference validity
        if ts_diff == 0:
            return False

        # 3. Check ratio
        # ratio = (diffRequests * 1e18) / ts_diff >= livenessRatio
        # We use integer arithmetic as per Solidity
        ratio = (diff_requests * 10**18) // ts_diff

        return ratio >= self.liveness_ratio
