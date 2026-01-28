from unittest.mock import MagicMock

import pytest

from iwa.core.chain.interface import ChainInterface
from iwa.core.chain.models import SupportedChain
from iwa.core.chain.rate_limiter import _rate_limiters


@pytest.fixture
def clean_rate_limiters():
    """Clear global rate limiters before and after test."""
    _rate_limiters.clear()
    yield
    _rate_limiters.clear()


def test_chain_interface_initializes_strict_limiter(clean_rate_limiters):
    """Verify ChainInterface initializes with rate=5.0 and burst=10."""
    # Create a dummy chain
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestSlowChain"
    chain.rpcs = ["http://rpc.example.com"]
    chain.rpc = "http://rpc.example.com"

    # Initialize interface
    ci = ChainInterface(chain)

    # Get the limiter used
    limiter = ci._rate_limiter

    # Assert correct configuration
    assert limiter.rate == 5.0, f"Expected rate 5.0, got {limiter.rate}"
    assert limiter.burst == 10, f"Expected burst 10, got {limiter.burst}"
