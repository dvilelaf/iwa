"""Olas models"""

from typing import Optional

from pydantic import BaseModel

from iwa.core.models import EthereumAddress


class Service(BaseModel):
    """Service"""

    service_name: str
    chain_name: str
    service_id: Optional[int] = None
    service_owner_address: EthereumAddress = None
    agent_address: Optional[EthereumAddress] = None
    multisig_address: Optional[EthereumAddress] = None
    staking_contract_address: Optional[EthereumAddress] = None


class OlasConfig(BaseModel):
    """OlasConfig"""

    services: list[Service] = []
