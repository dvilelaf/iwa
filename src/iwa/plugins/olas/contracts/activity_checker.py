"""Activity checker contract interaction."""

from iwa.core.constants import DEFAULT_MECH_CONTRACT_ADDRESS
from iwa.plugins.olas.contracts.base import ContractInstance, OLAS_ABI_PATH


class ActivityCheckerContract(ContractInstance):
    """Class to interact with the activity checker."""

    name = "activity_checker"
    abi_path = OLAS_ABI_PATH / "activity_checker.json"

    def __init__(self, address):
        """Initialize ActivityCheckerContract."""
        super().__init__(address)
        agent_mech_function = getattr(self.contract.functions, "agentMech", None)
        self.agent_mech = (
            agent_mech_function().call() if agent_mech_function else DEFAULT_MECH_CONTRACT_ADDRESS
        )
        self.liveness_ratio = self.contract.functions.livenessRatio().call()

    def get_multisig_nonces(self, multisig: str) -> int:
        """Get the number of nonces for a multisig address."""
        return self.contract.functions.getMultisigNonces(multisig).call()

    def is_ratio_pass(self, current_nonces: int, last_nonces: int, timestamp: int) -> bool:
        """Check if the liveness ratio is passed."""
        return self.contract.functions.isRatioPass(current_nonces, last_nonces, timestamp).call()
