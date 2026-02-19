"""Tests to improve coverage for iwa.web.routers.olas.staking module.

Covers missing lines: 31-33, 62-67, 81-123, 241, 248, 259-265, 283, 293-299,
318, 331-337, 352-395, 414, 427-435.
"""

import sys
from enum import IntEnum
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

# Valid Ethereum addresses for testing
ADDR_CONTRACT = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_TOKEN = "0x1111111111111111111111111111111111111111"
ADDR_AGENT = "0x2222222222222222222222222222222222222222"
ADDR_MULTISIG = "0x3333333333333333333333333333333333333333"
ADDR_OWNER = "0x4444444444444444444444444444444444444444"
ADDR_STAKING = "0x5555555555555555555555555555555555555555"
ADDR_UTILITY = "0x6666666666666666666666666666666666666666"


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock wallet dependency before importing router modules."""
    mock_dep_module = MagicMock()
    mock_dep_module.wallet = MagicMock()
    mock_dep_module.verify_auth = MagicMock()
    mock_dep_module.get_config = MagicMock()

    with patch.dict(sys.modules, {"iwa.web.dependencies": mock_dep_module}):
        yield mock_dep_module


# ========================================================================
# Tests for _get_service_filter_info (lines 81-123)
# ========================================================================


class TestGetServiceFilterInfo:
    """Tests for _get_service_filter_info helper function."""

    def test_no_service_key_returns_nones(self):
        """When service_key is None, both bond and token should be None."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        bond, token = _get_service_filter_info(None)
        assert bond is None
        assert token is None

    def test_no_service_key_empty_returns_nones(self):
        """When service_key is empty string, both bond and token should be None."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        bond, token = _get_service_filter_info("")
        assert bond is None
        assert token is None

    def test_service_key_with_utility_contract(self):
        """Lines 81-111: Service key found, token utility contract returns deposit info."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        mock_service = MagicMock()
        mock_service.service_id = 1
        mock_service.chain_name = "gnosis"
        mock_service.token_address = ADDR_TOKEN

        mock_manager = MagicMock()
        mock_manager.service = mock_service

        mock_token_utility = MagicMock()
        mock_token_utility.get_service_token_deposit.return_value = (ADDR_TOKEN, 10**18)

        mock_contract_cache = MagicMock()
        mock_contract_cache.get_contract.return_value = mock_token_utility

        with (
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.core.contracts.cache.ContractCache",
                return_value=mock_contract_cache,
            ),
            patch(
                "iwa.plugins.olas.constants.OLAS_CONTRACTS",
                {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
            ),
            patch("iwa.plugins.olas.contracts.service.ServiceRegistryTokenUtilityContract"),
        ):
            bond, token = _get_service_filter_info("gnosis:1")

        assert bond == 10**18
        assert token == ADDR_TOKEN.lower()

    def test_service_key_no_utility_address(self):
        """Lines 112-114: Token utility address not found for chain, falls back to service token_address."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        mock_service = MagicMock()
        mock_service.service_id = 1
        mock_service.chain_name = "gnosis"
        mock_service.token_address = ADDR_TOKEN

        mock_manager = MagicMock()
        mock_manager.service = mock_service

        with (
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.core.contracts.cache.ContractCache"),
            patch(
                "iwa.plugins.olas.constants.OLAS_CONTRACTS",
                {"gnosis": {}},  # No utility address
            ),
            patch("iwa.plugins.olas.contracts.service.ServiceRegistryTokenUtilityContract"),
        ):
            bond, token = _get_service_filter_info("gnosis:1")

        assert bond is None
        assert token == ADDR_TOKEN.lower()

    def test_service_key_token_deposit_exception(self):
        """Lines 115-118: Exception getting token deposit falls back to service token_address."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        mock_service = MagicMock()
        mock_service.service_id = 1
        mock_service.chain_name = "gnosis"
        mock_service.token_address = ADDR_TOKEN

        mock_manager = MagicMock()
        mock_manager.service = mock_service

        mock_contract_cache = MagicMock()
        mock_contract_cache.get_contract.side_effect = Exception("RPC error")

        with (
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.core.contracts.cache.ContractCache",
                return_value=mock_contract_cache,
            ),
            patch(
                "iwa.plugins.olas.constants.OLAS_CONTRACTS",
                {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": ADDR_UTILITY}},
            ),
            patch("iwa.plugins.olas.contracts.service.ServiceRegistryTokenUtilityContract"),
        ):
            bond, token = _get_service_filter_info("gnosis:1")

        assert bond is None
        assert token == ADDR_TOKEN.lower()

    def test_service_key_no_service_found(self):
        """Lines 89: When ServiceManager has no service, returns nones."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        mock_manager = MagicMock()
        mock_manager.service = None  # No service found

        with patch(
            "iwa.plugins.olas.service_manager.ServiceManager",
            return_value=mock_manager,
        ):
            bond, token = _get_service_filter_info("gnosis:999")

        assert bond is None
        assert token is None

    def test_service_key_outer_exception(self):
        """Lines 120-123: Outer exception in _get_service_filter_info returns nones."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        with patch(
            "iwa.plugins.olas.service_manager.ServiceManager",
            side_effect=Exception("import error"),
        ):
            bond, token = _get_service_filter_info("gnosis:1")

        assert bond is None
        assert token is None

    def test_service_key_token_address_is_none(self):
        """When service.token_address is None and utility address not found."""
        from iwa.web.routers.olas.staking import _get_service_filter_info

        mock_service = MagicMock()
        mock_service.service_id = 1
        mock_service.chain_name = "gnosis"
        mock_service.token_address = None  # No token address

        mock_manager = MagicMock()
        mock_manager.service = mock_service

        with (
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.core.contracts.cache.ContractCache"),
            patch(
                "iwa.plugins.olas.constants.OLAS_CONTRACTS",
                {"gnosis": {}},
            ),
            patch("iwa.plugins.olas.contracts.service.ServiceRegistryTokenUtilityContract"),
        ):
            bond, token = _get_service_filter_info("gnosis:1")

        assert bond is None
        assert token == ""  # (None or "").lower() = ""


# ========================================================================
# Tests for get_staking_contracts endpoint (lines 31-33, 62-67)
# ========================================================================


class TestGetStakingContracts:
    """Tests for the get_staking_contracts endpoint function."""

    def test_invalid_chain_name(self):
        """Lines 31-33: Invalid chain name raises HTTPException 400."""
        from iwa.web.routers.olas.staking import get_staking_contracts

        mock_config = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_staking_contracts(chain="drop;table", config=mock_config)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid chain name"

    def test_invalid_chain_with_special_chars(self):
        """Lines 31-33: Chain name with special characters raises HTTPException 400."""
        from iwa.web.routers.olas.staking import get_staking_contracts

        mock_config = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_staking_contracts(chain="gnosis; DROP TABLE", config=mock_config)
        assert exc_info.value.status_code == 400

    def test_exception_in_staking_contracts_returns_empty(self):
        """Lines 62-67: Exception during contract fetching returns empty list."""
        from iwa.web.routers.olas.staking import get_staking_contracts

        mock_config = MagicMock()
        with patch(
            "iwa.core.chain.ChainInterfaces",
            side_effect=Exception("RPC unavailable"),
        ):
            result = get_staking_contracts(chain="gnosis", config=mock_config)
        assert result == []


# ========================================================================
# Helper to set up config mocks for endpoint functions
# ========================================================================


def _setup_config_mocks(services_dict):
    """Create mock Config and OlasConfig with given services."""
    mock_olas_config = MagicMock()
    mock_olas_config.services = services_dict

    mock_config = MagicMock()
    mock_config.plugins = {"olas": {}}

    return mock_config, mock_olas_config


# ========================================================================
# Tests for stake_service endpoint (lines 241, 248, 259-265)
# ========================================================================


class TestStakeService:
    """Tests for the stake_service endpoint function."""

    def _make_service(self, staking_address=None):
        """Create a mock Service."""
        service = MagicMock()
        service.chain_name = "gnosis"
        service.service_id = 1
        service.staking_contract_address = staking_address
        return service

    def test_service_not_found(self):
        """Line 241: Service not found raises 404."""
        from iwa.web.routers.olas.staking import stake_service

        mock_request = MagicMock(spec=Request)

        mock_config, mock_olas_config = _setup_config_mocks({})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                stake_service(
                    request=mock_request,
                    service_key="gnosis:999",
                    staking_contract=ADDR_STAKING,
                )
            assert exc_info.value.status_code == 404

    def test_invalid_staking_contract_address(self):
        """Line 248: Invalid staking contract address (no 0x prefix) raises 400."""
        from iwa.web.routers.olas.staking import stake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                stake_service(
                    request=mock_request,
                    service_key="gnosis:1",
                    staking_contract="not_valid_address",
                )
            assert exc_info.value.status_code == 400
            assert "Invalid staking contract address" in exc_info.value.detail

    def test_stake_failure_returns_400(self):
        """Lines 259: Stake returns False raises 400."""
        from iwa.web.routers.olas.staking import stake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_manager = MagicMock()
        mock_manager.stake.return_value = False

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                stake_service(
                    request=mock_request,
                    service_key="gnosis:1",
                    staking_contract=ADDR_STAKING,
                )
            assert exc_info.value.status_code == 400
            assert "Failed to stake" in exc_info.value.detail

    def test_stake_generic_exception(self):
        """Lines 263-265: Generic exception in stake raises 400."""
        from iwa.web.routers.olas.staking import stake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                side_effect=Exception("unexpected error"),
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                stake_service(
                    request=mock_request,
                    service_key="gnosis:1",
                    staking_contract=ADDR_STAKING,
                )
            assert exc_info.value.status_code == 400


# ========================================================================
# Tests for claim_rewards endpoint (lines 283, 293-299)
# ========================================================================


class TestClaimRewards:
    """Tests for the claim_rewards endpoint function."""

    def test_service_not_found(self):
        """Line 283: Service not found raises 404."""
        from iwa.web.routers.olas.staking import claim_rewards

        mock_config, mock_olas_config = _setup_config_mocks({})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                claim_rewards(service_key="gnosis:999")
            assert exc_info.value.status_code == 404

    def test_claim_failure_returns_400(self):
        """Lines 293: Claim returns (False, ...) raises 400."""
        from iwa.web.routers.olas.staking import claim_rewards

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_manager = MagicMock()
        mock_manager.claim_rewards.return_value = (False, 0)

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                claim_rewards(service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "Failed to claim" in exc_info.value.detail

    def test_claim_generic_exception(self):
        """Lines 297-299: Generic exception in claim raises 500."""
        from iwa.web.routers.olas.staking import claim_rewards

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                side_effect=Exception("unexpected"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                claim_rewards(service_key="gnosis:1")
            assert exc_info.value.status_code == 500


# ========================================================================
# Tests for unstake_service endpoint (lines 318, 331-337)
# ========================================================================


class TestUnstakeService:
    """Tests for the unstake_service endpoint function."""

    def test_service_not_found(self):
        """Line 318: Service not found raises 404."""
        from iwa.web.routers.olas.staking import unstake_service

        mock_config, mock_olas_config = _setup_config_mocks({})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                unstake_service(service_key="gnosis:999")
            assert exc_info.value.status_code == 404

    def test_service_not_staked(self):
        """Line 318: Service found but no staking_contract_address raises 404."""
        from iwa.web.routers.olas.staking import unstake_service

        mock_service = MagicMock()
        mock_service.staking_contract_address = None  # Not staked

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                unstake_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 404
            assert "not staked" in exc_info.value.detail

    def test_unstake_failure_returns_400(self):
        """Lines 331: Unstake returns False raises 400."""
        from iwa.web.routers.olas.staking import unstake_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_manager = MagicMock()
        mock_manager.unstake.return_value = False

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                unstake_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "Failed to unstake" in exc_info.value.detail

    def test_unstake_generic_exception(self):
        """Lines 335-337: Generic exception in unstake raises 500."""
        from iwa.web.routers.olas.staking import unstake_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                side_effect=Exception("unexpected"),
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                unstake_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 500


# ========================================================================
# Tests for restake_service endpoint (lines 352-395)
# ========================================================================


class _MockStakingState(IntEnum):
    """Mock StakingState enum for tests."""

    NOT_STAKED = 0
    STAKED = 1
    EVICTED = 2


class TestRestakeService:
    """Tests for the restake_service endpoint function."""

    def _make_service(self):
        """Create a mock service with staking contract."""
        service = MagicMock()
        service.chain_name = "gnosis"
        service.service_id = 1
        service.staking_contract_address = ADDR_STAKING
        return service

    def test_service_not_found(self):
        """Lines 360-361: Service not found raises 404."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        mock_config, mock_olas_config = _setup_config_mocks({})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:999")
            assert exc_info.value.status_code == 404

    def test_service_no_staking_contract(self):
        """Lines 360-361: Service without staking contract raises 404."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = MagicMock()
        service.staking_contract_address = None

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:1")
            assert exc_info.value.status_code == 404

    def test_service_not_evicted(self):
        """Lines 373-377: Service not in EVICTED state raises 400."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = _MockStakingState.STAKED

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch("iwa.plugins.olas.service_manager.ServiceManager"),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingState",
                _MockStakingState,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "not EVICTED" in exc_info.value.detail

    def test_unstake_fails(self):
        """Lines 381-382: Unstake step fails raises 400."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = _MockStakingState.EVICTED

        mock_manager = MagicMock()
        mock_manager.unstake.return_value = False

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingState",
                _MockStakingState,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "Failed to unstake" in exc_info.value.detail

    def test_stake_after_unstake_fails(self):
        """Lines 386-387: Unstake succeeds but stake fails raises 400."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = _MockStakingState.EVICTED

        mock_manager = MagicMock()
        mock_manager.unstake.return_value = True
        mock_manager.stake.return_value = False

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingState",
                _MockStakingState,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "stake failed" in exc_info.value.detail

    def test_restake_success(self):
        """Lines 389: Full restake succeeds."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = _MockStakingState.EVICTED

        mock_manager = MagicMock()
        mock_manager.unstake.return_value = True
        mock_manager.stake.return_value = True

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingState",
                _MockStakingState,
            ),
        ):
            result = restake_service(request=mock_request, service_key="gnosis:1")

        assert result["status"] == "success"
        assert result["staking_contract"] == ADDR_STAKING

    def test_restake_generic_exception(self):
        """Lines 393-395: Generic exception in restake raises 500."""
        from iwa.web.routers.olas.staking import restake_service

        mock_request = MagicMock(spec=Request)
        service = self._make_service()

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                side_effect=Exception("unexpected"),
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingState",
                _MockStakingState,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                restake_service(request=mock_request, service_key="gnosis:1")
            assert exc_info.value.status_code == 500


# ========================================================================
# Tests for checkpoint_service endpoint (lines 414, 427-435)
# ========================================================================


class TestCheckpointService:
    """Tests for the checkpoint_service endpoint function."""

    def test_service_not_found(self):
        """Line 414: Service not found raises 404."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_config, mock_olas_config = _setup_config_mocks({})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                checkpoint_service(service_key="gnosis:999")
            assert exc_info.value.status_code == 404

    def test_service_not_staked(self):
        """Line 414: Service without staking contract raises 404."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_service = MagicMock()
        mock_service.staking_contract_address = None

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                checkpoint_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 404

    def test_checkpoint_not_needed(self):
        """Lines 427-428: Checkpoint returns False but not needed returns skipped."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_manager = MagicMock()
        mock_manager.call_checkpoint.return_value = False

        mock_staking = MagicMock()
        mock_staking.is_checkpoint_needed.return_value = False

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
        ):
            result = checkpoint_service(service_key="gnosis:1")

        assert result["status"] == "skipped"
        assert "not needed" in result["message"]

    def test_checkpoint_failure_needed_raises_400(self):
        """Lines 429: Checkpoint returns False and is_checkpoint_needed True raises 400."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_manager = MagicMock()
        mock_manager.call_checkpoint.return_value = False

        mock_staking = MagicMock()
        mock_staking.is_checkpoint_needed.return_value = True

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch(
                "iwa.plugins.olas.contracts.staking.StakingContract",
                return_value=mock_staking,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                checkpoint_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 400
            assert "Failed to checkpoint" in exc_info.value.detail

    def test_checkpoint_generic_exception(self):
        """Lines 433-435: Generic exception in checkpoint raises 500."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                side_effect=Exception("unexpected"),
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                checkpoint_service(service_key="gnosis:1")
            assert exc_info.value.status_code == 500


# ========================================================================
# Tests for _check_availability success path (lines 143-160)
# ========================================================================


class TestCheckAvailabilitySuccess:
    """Tests for _check_availability success path."""

    def test_success_path(self):
        """Lines 143-160: Successful contract check returns full result."""
        from iwa.web.routers.olas.staking import _check_availability

        mock_interface = MagicMock()
        mock_interface.chain.name = "gnosis"

        mock_contract = MagicMock()
        mock_contract.call.return_value = [1, 2, 3]  # 3 service IDs
        mock_contract.max_num_services = 10
        mock_contract.min_staking_deposit = 100
        mock_contract.staking_token_address = ADDR_TOKEN

        mock_cache = MagicMock()
        mock_cache.get_contract.return_value = mock_contract

        with (
            patch(
                "iwa.core.contracts.cache.ContractCache",
                return_value=mock_cache,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            result = _check_availability("TestContract", ADDR_CONTRACT, mock_interface)

        assert result["name"] == "TestContract"
        assert result["address"] == ADDR_CONTRACT
        assert result["usage"]["used"] == 3
        assert result["usage"]["max"] == 10
        assert result["usage"]["available_slots"] == 7
        assert result["usage"]["available"] is True
        assert result["min_staking_deposit"] == 100
        assert result["staking_token"] == ADDR_TOKEN


# ========================================================================
# Tests for _fetch_all_contracts (lines 179-189)
# ========================================================================


class TestFetchAllContracts:
    """Tests for _fetch_all_contracts function."""

    def test_fetches_contracts_via_threadpool(self):
        """Lines 179-189: Fetch contracts using ThreadPoolExecutor."""
        from iwa.web.routers.olas.staking import _fetch_all_contracts

        mock_interface = MagicMock()
        mock_interface.chain.name = "gnosis"

        contracts = {
            "Contract A": ADDR_CONTRACT,
            "Contract B": ADDR_STAKING,
        }

        mock_result_a = {
            "name": "Contract A",
            "address": ADDR_CONTRACT,
            "usage": {"used": 2, "max": 10, "available_slots": 8, "available": True},
            "min_staking_deposit": 100,
        }
        mock_result_b = {
            "name": "Contract B",
            "address": ADDR_STAKING,
            "usage": {"used": 10, "max": 10, "available_slots": 0, "available": False},
            "min_staking_deposit": 200,
        }

        def mock_check_avail(name, addr, interface):
            if name == "Contract A":
                return mock_result_a
            return mock_result_b

        with patch(
            "iwa.web.routers.olas.staking._check_availability",
            side_effect=mock_check_avail,
        ):
            results = _fetch_all_contracts(contracts, mock_interface)

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert "Contract A" in names
        assert "Contract B" in names


# ========================================================================
# Tests for get_staking_contracts success path (lines 47-51)
# ========================================================================


class TestGetStakingContractsSuccess:
    """Tests for get_staking_contracts success path."""

    def test_success_returns_contracts_and_filter_info(self):
        """Lines 47-60: Success path returns contracts list and filter_info dict."""
        from iwa.web.routers.olas.staking import get_staking_contracts

        mock_config = MagicMock()
        mock_interface = MagicMock()
        mock_interface.chain.name = "gnosis"

        mock_result = {
            "name": "TestContract",
            "address": ADDR_CONTRACT,
            "usage": {"used": 2, "max": 10, "available_slots": 8, "available": True},
            "min_staking_deposit": 100,
            "staking_token": ADDR_TOKEN,
        }

        with (
            patch(
                "iwa.core.chain.ChainInterfaces",
            ) as mock_chains_cls,
            patch(
                "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"TestContract": ADDR_CONTRACT}},
            ),
            patch(
                "iwa.web.routers.olas.staking._get_service_filter_info",
                return_value=(None, None),
            ),
            patch(
                "iwa.web.routers.olas.staking._fetch_all_contracts",
                return_value=[mock_result],
            ),
            patch(
                "iwa.web.routers.olas.staking._filter_contracts",
                return_value=[mock_result],
            ),
        ):
            mock_chains_cls.return_value.get.return_value = mock_interface

            result = get_staking_contracts(chain="gnosis", config=mock_config)

        assert isinstance(result, dict)
        assert "contracts" in result
        assert "filter_info" in result
        assert len(result["contracts"]) == 1
        assert result["filter_info"]["total_contracts"] == 1
        assert result["filter_info"]["filtered_count"] == 1
        assert result["filter_info"]["is_filtered"] is False
        assert result["filter_info"]["service_bond"] is None

    def test_success_with_service_key_filter(self):
        """Lines 47-60: Success with service_key applies filtering metadata."""
        from iwa.web.routers.olas.staking import get_staking_contracts

        mock_config = MagicMock()
        mock_interface = MagicMock()

        mock_result = {
            "name": "TestContract",
            "address": ADDR_CONTRACT,
            "usage": {"available": True},
            "min_staking_deposit": 100,
            "staking_token": ADDR_TOKEN,
        }

        with (
            patch("iwa.core.chain.ChainInterfaces") as mock_chains_cls,
            patch(
                "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"TestContract": ADDR_CONTRACT}},
            ),
            patch(
                "iwa.web.routers.olas.staking._get_service_filter_info",
                return_value=(10**18, ADDR_TOKEN.lower()),
            ),
            patch(
                "iwa.web.routers.olas.staking._fetch_all_contracts",
                return_value=[mock_result],
            ),
            patch(
                "iwa.web.routers.olas.staking._filter_contracts",
                return_value=[mock_result],
            ),
        ):
            mock_chains_cls.return_value.get.return_value = mock_interface

            result = get_staking_contracts(
                chain="gnosis", service_key="gnosis:1", config=mock_config
            )

        assert result["filter_info"]["is_filtered"] is True
        assert result["filter_info"]["service_bond"] == 10**18
        assert result["filter_info"]["service_bond_olas"] == 1.0


# ========================================================================
# Tests for endpoint success paths (lines 257, 291, 329, 424)
# ========================================================================


class TestEndpointSuccessPaths:
    """Tests for success return paths of endpoints."""

    def test_stake_success(self):
        """Line 257: Stake service returns success."""
        from iwa.web.routers.olas.staking import stake_service

        mock_request = MagicMock(spec=Request)
        service = MagicMock()
        service.chain_name = "gnosis"

        mock_manager = MagicMock()
        mock_manager.stake.return_value = True

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            result = stake_service(
                request=mock_request,
                service_key="gnosis:1",
                staking_contract=ADDR_STAKING,
            )

        assert result["status"] == "success"

    def test_claim_success(self):
        """Line 291: Claim rewards returns success with amount."""
        from iwa.web.routers.olas.staking import claim_rewards

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_manager = MagicMock()
        mock_manager.claim_rewards.return_value = (True, 10**18)

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
        ):
            result = claim_rewards(service_key="gnosis:1")

        assert result["status"] == "success"
        assert result["amount"] == 10**18

    def test_unstake_success(self):
        """Line 329: Unstake service returns success."""
        from iwa.web.routers.olas.staking import unstake_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_manager = MagicMock()
        mock_manager.unstake.return_value = True

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            result = unstake_service(service_key="gnosis:1")

        assert result["status"] == "success"

    def test_checkpoint_success(self):
        """Line 424: Checkpoint service returns success."""
        from iwa.web.routers.olas.staking import checkpoint_service

        mock_service = MagicMock()
        mock_service.chain_name = "gnosis"
        mock_service.staking_contract_address = ADDR_STAKING

        mock_manager = MagicMock()
        mock_manager.call_checkpoint.return_value = True

        mock_config, mock_olas_config = _setup_config_mocks({"gnosis:1": mock_service})

        with (
            patch("iwa.web.routers.olas.staking.Config", return_value=mock_config),
            patch(
                "iwa.web.routers.olas.staking.OlasConfig.model_validate",
                return_value=mock_olas_config,
            ),
            patch(
                "iwa.plugins.olas.service_manager.ServiceManager",
                return_value=mock_manager,
            ),
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            result = checkpoint_service(service_key="gnosis:1")

        assert result["status"] == "success"
