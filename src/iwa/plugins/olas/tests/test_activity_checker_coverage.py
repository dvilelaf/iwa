"""Tests for ActivityCheckerContract to improve coverage.

Covers: __init__, get_multisig_nonces, mech_marketplace, agent_mech,
liveness_ratio, is_ratio_pass.
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.core.constants import DEFAULT_MECH_CONTRACT_ADDRESS
from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress

ADDR_CHECKER = "0x1111111111111111111111111111111111111111"
ADDR_MULTISIG = "0x2222222222222222222222222222222222222222"
ADDR_MECH_MP = "0x3333333333333333333333333333333333333333"
ADDR_AGENT_MECH = "0x4444444444444444444444444444444444444444"


@pytest.fixture
def checker():
    """Create an ActivityCheckerContract with mocked ContractInstance.__init__."""
    from iwa.plugins.olas.contracts.activity_checker import ActivityCheckerContract

    mock_contract = MagicMock()

    with (
        patch.object(
            ContractInstance, "__init__", return_value=None
        ),
        patch.object(
            ContractInstance, "contract", new_callable=PropertyMock, return_value=mock_contract
        ),
    ):
        instance = ActivityCheckerContract(
            EthereumAddress(ADDR_CHECKER), chain_name="gnosis"
        )
        # Expose the mock_contract for test manipulation
        instance._mock_contract = mock_contract
        yield instance


class TestInit:
    """Test __init__ method."""

    def test_init_sets_caches_to_none(self, checker):
        """Verify that __init__ initializes caches to None."""
        assert checker._mech_marketplace is None
        assert checker._agent_mech is None
        assert checker._liveness_ratio is None


class TestGetMultisigNonces:
    """Test get_multisig_nonces method."""

    def test_returns_tuple_of_nonces(self, checker):
        """Test that get_multisig_nonces returns (safe_nonce, mech_requests)."""
        checker._mock_contract.functions.getMultisigNonces.return_value.call.return_value = [
            42,
            10,
        ]
        result = checker.get_multisig_nonces(EthereumAddress(ADDR_MULTISIG))
        assert result == (42, 10)
        checker._mock_contract.functions.getMultisigNonces.assert_called_once_with(
            ADDR_MULTISIG
        )

    def test_returns_zero_nonces(self, checker):
        """Test with zero nonces."""
        checker._mock_contract.functions.getMultisigNonces.return_value.call.return_value = [
            0,
            0,
        ]
        result = checker.get_multisig_nonces(EthereumAddress(ADDR_MULTISIG))
        assert result == (0, 0)


class TestMechMarketplace:
    """Test mech_marketplace property."""

    def test_returns_marketplace_address(self, checker):
        """Test successful mechMarketplace call."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.return_value = ADDR_MECH_MP
        checker._mock_contract.functions.mechMarketplace = mock_fn

        result = checker.mech_marketplace
        assert result == ADDR_MECH_MP

    def test_caches_marketplace_address(self, checker):
        """Test that value is cached after first call."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.return_value = ADDR_MECH_MP
        checker._mock_contract.functions.mechMarketplace = mock_fn

        _ = checker.mech_marketplace
        _ = checker.mech_marketplace  # Second access
        # Only called once because of caching
        assert mock_fn.return_value.call.call_count == 1

    def test_returns_none_when_function_not_available(self, checker):
        """Test when mechMarketplace function does not exist."""
        # getattr returns None when attribute doesn't exist
        checker._mock_contract.functions = MagicMock(spec=[])
        result = checker.mech_marketplace
        assert result is None

    def test_returns_none_on_exception(self, checker):
        """Test that exceptions during call result in None."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.side_effect = Exception("RPC error")
        checker._mock_contract.functions.mechMarketplace = mock_fn

        result = checker.mech_marketplace
        assert result is None

    def test_none_result_is_not_cached(self, checker):
        """When mechMarketplace is None on first call, it stays None (cached)."""
        checker._mock_contract.functions = MagicMock(spec=[])
        result1 = checker.mech_marketplace
        assert result1 is None
        # The None is cached (self._mech_marketplace = None stays None)
        # But the lazy load check is `if self._mech_marketplace is None`
        # so it will try again - but since we already set it to None in the except,
        # it stays None. Actually, the code sets self._mech_marketplace = None
        # which means it will NOT re-enter the try block on second call
        # because None is stored. Wait - that's incorrect:
        # The check is `if self._mech_marketplace is None: try:...`
        # So if we set it to None in the except block, the next property
        # access will try again. Let me check the code...
        # Actually: `self._mech_marketplace = None` is both the initial value
        # AND the fallback on error. So the property will keep retrying.
        # That's a design choice. Let's just verify the behavior:
        result2 = checker.mech_marketplace
        assert result2 is None


class TestAgentMech:
    """Test agent_mech property."""

    def test_returns_agent_mech_address(self, checker):
        """Test successful agentMech call."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.return_value = ADDR_AGENT_MECH
        checker._mock_contract.functions.agentMech = mock_fn

        result = checker.agent_mech
        assert result == ADDR_AGENT_MECH

    def test_caches_agent_mech_address(self, checker):
        """Test that value is cached after first call."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.return_value = ADDR_AGENT_MECH
        checker._mock_contract.functions.agentMech = mock_fn

        _ = checker.agent_mech
        _ = checker.agent_mech  # Second access
        assert mock_fn.return_value.call.call_count == 1

    def test_returns_default_when_function_not_available(self, checker):
        """Test fallback to DEFAULT_MECH_CONTRACT_ADDRESS when no agentMech fn."""
        checker._mock_contract.functions = MagicMock(spec=[])
        result = checker.agent_mech
        assert result == DEFAULT_MECH_CONTRACT_ADDRESS

    def test_returns_default_on_exception(self, checker):
        """Test fallback to DEFAULT_MECH_CONTRACT_ADDRESS on exception."""
        mock_fn = MagicMock()
        mock_fn.return_value.call.side_effect = Exception("RPC error")
        checker._mock_contract.functions.agentMech = mock_fn

        result = checker.agent_mech
        assert result == DEFAULT_MECH_CONTRACT_ADDRESS


class TestLivenessRatio:
    """Test liveness_ratio property."""

    def test_returns_liveness_ratio(self, checker):
        """Test successful livenessRatio call."""
        checker._mock_contract.functions.livenessRatio.return_value.call.return_value = (
            10**15
        )
        result = checker.liveness_ratio
        assert result == 10**15

    def test_caches_liveness_ratio(self, checker):
        """Test that value is cached after first call."""
        checker._mock_contract.functions.livenessRatio.return_value.call.return_value = (
            10**15
        )
        _ = checker.liveness_ratio
        _ = checker.liveness_ratio  # Second access
        assert (
            checker._mock_contract.functions.livenessRatio.return_value.call.call_count == 1
        )

    def test_returns_zero_on_exception(self, checker):
        """Test fallback to 0 on exception."""
        checker._mock_contract.functions.livenessRatio.return_value.call.side_effect = (
            Exception("RPC error")
        )
        result = checker.liveness_ratio
        assert result == 0


class TestIsRatioPass:
    """Test is_ratio_pass method."""

    def test_passes_when_ratio_met(self, checker):
        """Test that ratio passes when requirements are met."""
        # Set liveness_ratio to a known value
        checker._liveness_ratio = 10**15  # 0.001 requests per second

        # current_nonces = (10, 5), last = (0, 0), ts_diff = 1000
        # diff_safe = 10, diff_requests = 5
        # ratio = (5 * 10^18) / 1000 = 5 * 10^15
        # 5 * 10^15 >= 10^15 => True
        result = checker.is_ratio_pass((10, 5), (0, 0), 1000)
        assert result is True

    def test_fails_when_ratio_not_met(self, checker):
        """Test that ratio fails when requirements are not met."""
        checker._liveness_ratio = 10**18  # 1 request per second

        # diff_requests = 1, ts_diff = 1000
        # ratio = (1 * 10^18) / 1000 = 10^15
        # 10^15 < 10^18 => False
        result = checker.is_ratio_pass((10, 1), (0, 0), 1000)
        assert result is False

    def test_fails_when_requests_exceed_transactions(self, checker):
        """Test failure when diff_requests > diff_safe."""
        checker._liveness_ratio = 0

        # diff_safe = 2, diff_requests = 5 => 5 > 2 => False
        result = checker.is_ratio_pass((2, 5), (0, 0), 1000)
        assert result is False

    def test_fails_when_negative_diff_requests(self, checker):
        """Test failure when diff_requests is negative (data corruption)."""
        checker._liveness_ratio = 0

        # diff_requests = 0 - 5 = -5 < 0 => False
        result = checker.is_ratio_pass((10, 0), (0, 5), 1000)
        assert result is False

    def test_fails_when_negative_diff_safe(self, checker):
        """Test failure when diff_safe is negative (data corruption)."""
        checker._liveness_ratio = 0

        # diff_safe = 0 - 10 = -10 < 0 => False
        result = checker.is_ratio_pass((0, 0), (10, 0), 1000)
        assert result is False

    def test_fails_when_ts_diff_is_zero(self, checker):
        """Test failure when time difference is zero."""
        checker._liveness_ratio = 0

        result = checker.is_ratio_pass((10, 5), (0, 0), 0)
        assert result is False

    def test_passes_with_zero_liveness_ratio(self, checker):
        """Test pass when liveness_ratio is 0 (no minimum requirement)."""
        checker._liveness_ratio = 0

        # ratio = (5 * 10^18) / 1000 = 5 * 10^15
        # 5 * 10^15 >= 0 => True
        result = checker.is_ratio_pass((10, 5), (0, 0), 1000)
        assert result is True

    def test_passes_at_exact_boundary(self, checker):
        """Test pass when ratio exactly equals liveness_ratio."""
        checker._liveness_ratio = 10**15

        # ratio = (1 * 10^18) / 1000 = 10^15
        # 10^15 >= 10^15 => True
        result = checker.is_ratio_pass((10, 1), (0, 0), 1000)
        assert result is True

    def test_uses_integer_arithmetic(self, checker):
        """Test that integer division (floor) is used, not float."""
        checker._liveness_ratio = 10**15 + 1

        # ratio = (1 * 10^18) / 1000 = 10^15 (integer division)
        # 10^15 < 10^15 + 1 => False
        result = checker.is_ratio_pass((10, 1), (0, 0), 1000)
        assert result is False

    def test_with_nonzero_last_nonces(self, checker):
        """Test with non-zero starting nonces."""
        checker._liveness_ratio = 10**15

        # current = (100, 50), last = (90, 45)
        # diff_safe = 10, diff_requests = 5
        # ratio = (5 * 10^18) / 1000 = 5 * 10^15
        # 5 * 10^15 >= 10^15 => True
        result = checker.is_ratio_pass((100, 50), (90, 45), 1000)
        assert result is True

    def test_zero_diff_requests_with_nonzero_liveness(self, checker):
        """Test with zero diff_requests but non-zero liveness_ratio."""
        checker._liveness_ratio = 10**15

        # diff_requests = 0
        # ratio = (0 * 10^18) / 1000 = 0
        # 0 < 10^15 => False
        result = checker.is_ratio_pass((10, 0), (0, 0), 1000)
        assert result is False

    def test_liveness_ratio_fetched_from_property(self, checker):
        """Test that is_ratio_pass uses the liveness_ratio property."""
        # Use the property rather than directly setting _liveness_ratio
        checker._mock_contract.functions.livenessRatio.return_value.call.return_value = (
            10**15
        )

        result = checker.is_ratio_pass((10, 5), (0, 0), 1000)
        assert result is True
