"""Activity checker contract interaction.

The MechActivityChecker contract tracks liveness for staked services by monitoring:
- Safe multisig transaction nonces
- Mech request counts

The liveness check (isRatioPass) verifies that the service is making enough mech
requests relative to the time elapsed since the last checkpoint.
"""

from typing import Tuple

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

        # Get the mech address this checker tracks
        agent_mech_function = getattr(self.contract.functions, "agentMech", None)
        self.agent_mech = (
            agent_mech_function().call() if agent_mech_function else DEFAULT_MECH_CONTRACT_ADDRESS
        )

        # Get liveness ratio (requests per second * 1e18)
        self.liveness_ratio = self.contract.functions.livenessRatio().call()

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
        return self.contract.functions.isRatioPass(
            list(current_nonces), list(last_nonces), ts_diff
        ).call()
