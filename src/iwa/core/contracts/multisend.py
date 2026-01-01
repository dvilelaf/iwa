"""Multisend contract interaction."""

from typing import Dict, List, Optional, cast

from hexbytes import HexBytes
from safe_eth.safe import SafeOperationEnum

from iwa.core.constants import ABI_PATH
from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress

# MultiSend addresses (same across Ethereum, Base, Gnosis via Singleton Factory)
MULTISEND_CALL_ONLY_ADDRESS = EthereumAddress("0x40A2aCCbd92BCA938b02010E17A5b8929b49130D")
MULTISEND_ADDRESS = EthereumAddress("0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761")


class MultiSendCallOnlyContract(ContractInstance):
    """Class to interact with multisend (call only) contract."""

    name = "multisend_call_only"
    abi_path = ABI_PATH / "multisend_call_only.json"

    @staticmethod
    def encode_data(tx: Dict) -> bytes:
        """Encodes multisend transaction."""
        # Operation 1 byte
        operation = HexBytes("{:0>2x}".format(cast(SafeOperationEnum, tx.get("operation")).value))

        # Address 20 bytes
        to = HexBytes("{:0>40x}".format(int(cast(str, tx.get("to")), 16)))

        # Value 32 bytes
        value = HexBytes("{:0>64x}".format(cast(int, tx.get("value", 0))))

        # Data length 32 bytes
        data = cast(bytes, tx.get("data", b""))
        data_ = HexBytes(data)
        data_length = HexBytes("{:0>64x}".format(len(data_)))

        return operation + to + value + data_length + data_

    @staticmethod
    def to_bytes(multi_send_txs: List[Dict]) -> bytes:
        """Multi send tx list to bytes."""
        return b"".join([MultiSendCallOnlyContract.encode_data(tx) for tx in multi_send_txs])

    def prepare_tx(
        self,
        from_address: EthereumAddress,
        transactions: list,
    ) -> Optional[Dict]:
        """Prepare multisend transaction."""
        encoded_multisend_data = MultiSendCallOnlyContract.to_bytes(transactions)

        total_value_wei = sum([tx.get("value", 0) for tx in transactions])

        return self.prepare_transaction(
            method_name="multiSend",
            method_kwargs={"encoded_multisend_data": encoded_multisend_data},
            tx_params={
                "from": from_address,
                "value": total_value_wei,
            },
        )


class MultiSendContract(MultiSendCallOnlyContract):
    """Class to interact with multisend contract."""

    name = "multisend"
    abi_path = ABI_PATH / "multisend.json"
