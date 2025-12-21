"""Tests for Olas models and OlasConfig."""

from iwa.plugins.olas.models import OlasConfig, Service, StakingStatus


class TestOlasConfig:
    """Tests for OlasConfig class."""

    def test_add_service(self):
        """Test add_service adds service to dict."""
        config = OlasConfig()
        service = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=456,
            agent_ids=[25],
            service_owner_address="0x1234567890123456789012345678901234567890",
        )

        config.add_service(service)

        assert "gnosis:456" in config.services
        assert config.services["gnosis:456"] == service

    def test_remove_service_success(self):
        """Test remove_service removes existing service."""
        config = OlasConfig()
        service = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=789,
            agent_ids=[25],
            service_owner_address="0x1234567890123456789012345678901234567890",
        )
        config.services["gnosis:789"] = service

        result = config.remove_service("gnosis:789")

        assert result is True
        assert "gnosis:789" not in config.services

    def test_remove_service_not_found(self):
        """Test remove_service returns False when not found."""
        config = OlasConfig()
        result = config.remove_service("gnosis:999")
        assert result is False

    def test_get_service(self):
        """Test get_service by chain and id."""
        config = OlasConfig()
        service = Service(
            service_name="test",
            chain_name="ethereum",
            service_id=200,
            agent_ids=[25],
            service_owner_address="0x1234567890123456789012345678901234567890",
        )
        config.services["ethereum:200"] = service

        result = config.get_service("ethereum", 200)
        assert result is not None
        assert result.service_id == 200

    def test_get_service_not_found(self):
        """Test get_service returns None when not found."""
        config = OlasConfig()
        result = config.get_service("base", 999)
        assert result is None


class TestStakingStatus:
    """Tests for StakingStatus model."""

    def test_staking_status_defaults(self):
        """Test StakingStatus default values."""
        status = StakingStatus(
            is_staked=False,
            staking_state="NOT_STAKED",
        )

        assert status.is_staked is False
        assert status.staking_state == "NOT_STAKED"
        assert status.mech_requests_this_epoch == 0
        assert status.required_mech_requests == 0
        assert status.remaining_mech_requests == 0
        assert status.has_enough_requests is False
        assert status.liveness_ratio_passed is False
        assert status.accrued_reward_wei == 0

    def test_staking_status_staked(self):
        """Test StakingStatus when staked."""
        status = StakingStatus(
            is_staked=True,
            staking_state="STAKED",
            staking_contract_address="0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C",
            mech_requests_this_epoch=5,
            required_mech_requests=3,
            remaining_mech_requests=0,
            has_enough_requests=True,
            liveness_ratio_passed=True,
            accrued_reward_wei=1000000000000000000,
        )

        assert status.is_staked is True
        assert status.staking_contract_address == "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
        assert status.has_enough_requests is True


class TestService:
    """Tests for Service model."""

    def test_service_key_property(self):
        """Test Service key property generates correct key."""
        service = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=123,
            agent_ids=[25],
            service_owner_address="0x1234567890123456789012345678901234567890",
        )

        assert service.key == "gnosis:123"

    def test_service_with_optional_fields(self):
        """Test Service with optional fields set."""
        # Use valid Ethereum addresses (these are random but valid checksums)
        # multisig_addr = "0x3f9Dd7c0e0D4D5f9f2F29F3f8A4c5D6e7F890123"  # Corrected invalid chars
        staking_addr = "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
        token_addr = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"

        service = Service(
            service_name="test",
            chain_name="gnosis",
            service_id=456,
            agent_ids=[25],
            service_owner_address="0x1234567890123456789012345678901234567890",
            staking_contract_address=staking_addr,
            token_address=token_addr,
        )

        # These should be set correctly
        assert service.staking_contract_address is not None
        assert service.token_address is not None
        assert service.key == "gnosis:456"
