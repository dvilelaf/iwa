"""Mech contract interaction."""

from typing import Dict, Optional

from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH


class MechContract(ContractInstance):
    """Class to interact with the Mech contract."""

    def __init__(
        self,
        address: EthereumAddress,
        chain_name: str,
        use_new_abi: bool = False,
    ):
        """Initialize the contract."""
        self.use_new_abi = use_new_abi
        if use_new_abi:
            self.abi_path = OLAS_ABI_PATH / "mech_new.json"
        else:
            self.abi_path = OLAS_ABI_PATH / "mech.json"
        super().__init__(address, chain_name)

    def get_price(self) -> int:
        """Get the current price for a request."""
        try:
            return self.call("price")
        except Exception:
            # Fallback for new ABIs if price() is not there
            return 10**16  # 0.01 xDAI

    def prepare_request_tx(
        self,
        from_address: EthereumAddress,
        data: bytes,
        value: Optional[int] = None,
    ) -> Optional[Dict]:
        """Prepare a request transaction."""
        if value is None:
            value = self.get_price()

        return self.prepare_transaction(
            method_name="request",
            method_kwargs={"data": data},
            tx_params={"from": from_address, "value": value},
        )
