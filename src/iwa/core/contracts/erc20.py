"""ERC20 contract interaction."""

from typing import Dict, Optional

from iwa.core.constants import ABI_PATH
from iwa.core.contracts.contract import ContractInstance


class ERC20Contract(ContractInstance):
    """Class to interact with ERC20 contracts."""

    name = "erc20"
    abi_path = ABI_PATH / "ERC20.json"

    def __init__(self, address: str, chain_name: str = "gnosis"):
        """Initialize ERC20 contract instance."""
        super().__init__(address, chain_name)

        self.decimals = self.call("decimals")
        self.symbol = self.call("symbol")
        self.name = self.call("name")
        self.total_supply = self.call("totalSupply")

    def allowance_wei(self, owner: str, spender: str) -> int:
        """Allowance"""
        return self.call("allowance", owner, spender)

    def allowance_eth(self, owner: str, spender: str) -> float:
        """Allowance in human readable format"""
        return self.allowance_wei(owner, spender) / (10**self.decimals)

    def balance_of_wei(self, account: str) -> int:
        """Balance of"""
        return self.call("balanceOf", account)

    def balance_of_eth(self, account: str) -> float:
        """Balance of in human readable format"""
        return self.balance_of_wei(account) / (10**self.decimals)

    def prepare_transfer_tx(
        self,
        from_address: str,
        to: str,
        amount_wei: int,
    ) -> Optional[Dict]:
        """Transfer."""
        return self.prepare_transaction(
            method_name="transfer",
            method_kwargs={"to": to, "amount": amount_wei},
            tx_params={"from": from_address},
        )

    def prepare_transfer_from_tx(
        self,
        from_address: str,
        sender: str,
        recipient: str,
        amount_wei: int,
    ) -> Optional[Dict]:
        """Transfer from."""
        return self.prepare_transaction(
            method_name="transferFrom",
            method_kwargs={"sender": sender, "recipient": recipient, "amount": amount_wei},
            tx_params={"from": from_address},
        )

    def prepare_approve_tx(
        self,
        from_address: str,
        spender: str,
        amount_wei: int,
    ) -> Optional[Dict]:
        """Approve."""
        return self.prepare_transaction(
            method_name="approve",
            method_kwargs={"spender": spender, "amount": amount_wei},
            tx_params={"from": from_address},
        )
