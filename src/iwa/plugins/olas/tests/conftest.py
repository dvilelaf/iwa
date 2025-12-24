"""Shared fixtures for Olas tests."""

import pytest
from unittest.mock import MagicMock
from iwa.plugins.olas.models import OlasConfig, Service
from iwa.plugins.olas.contracts.service import ServiceState

@pytest.fixture
def mock_wallet():
    wallet = MagicMock()
    wallet.key_storage = MagicMock()
    wallet.address = "0xWalletAddress"
    return wallet

@pytest.fixture
def mock_olas_config():
    service = Service(
        service_name="Test Service",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[],
        multisig_address="0x1111111111111111111111111111111111111111",
        staking_contract_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    )
    return OlasConfig(services={"gnosis:1": service})
