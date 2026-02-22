"""Tests for subgraph endpoint resolution."""

from iwa.plugins.olas.subgraph.endpoints import (
    ALL_CHAINS,
    SubgraphType,
    get_available_chains,
    get_endpoint,
)

API_KEY = "test-api-key-123"


class TestGetEndpoint:
    def test_proxy_gnosis_registry(self):
        url = get_endpoint("gnosis", SubgraphType.SERVICE_REGISTRY)
        assert url is not None
        assert "service-registry-gnosis" in url

    def test_proxy_mode_registry(self):
        url = get_endpoint("mode", SubgraphType.SERVICE_REGISTRY)
        assert url is not None
        assert "service-registry-mode" in url

    def test_proxy_ethereum_protocol(self):
        url = get_endpoint("ethereum", SubgraphType.PROTOCOL_REGISTRY)
        assert url is not None
        assert "autonolas" in url

    def test_thegraph_with_key(self):
        url = get_endpoint("ethereum", SubgraphType.SERVICE_REGISTRY, api_key=API_KEY)
        assert url is not None
        assert API_KEY in url
        assert "gateway.thegraph.com" in url

    def test_thegraph_without_key(self):
        url = get_endpoint("ethereum", SubgraphType.SERVICE_REGISTRY)
        # Ethereum registry has no proxy, and no key provided
        assert url is None

    def test_unknown_chain(self):
        url = get_endpoint("solana", SubgraphType.SERVICE_REGISTRY)
        assert url is None

    def test_case_insensitive(self):
        url = get_endpoint("Gnosis", SubgraphType.SERVICE_REGISTRY)
        assert url is not None

    def test_proxy_preferred_over_thegraph(self):
        # Gnosis registry has a proxy endpoint
        url_no_key = get_endpoint("gnosis", SubgraphType.SERVICE_REGISTRY)
        url_with_key = get_endpoint("gnosis", SubgraphType.SERVICE_REGISTRY, api_key=API_KEY)
        # Both should return the proxy (free) endpoint
        assert url_no_key == url_with_key
        assert "gateway.thegraph.com" not in url_no_key


class TestGetAvailableChains:
    def test_registry_no_key(self):
        chains = get_available_chains(SubgraphType.SERVICE_REGISTRY)
        assert "gnosis" in chains
        assert "mode" in chains

    def test_registry_with_key(self):
        chains = get_available_chains(SubgraphType.SERVICE_REGISTRY, api_key=API_KEY)
        assert "gnosis" in chains
        assert "ethereum" in chains
        assert "base" in chains

    def test_staking_no_key(self):
        chains = get_available_chains(SubgraphType.STAKING)
        assert "mode" in chains

    def test_staking_with_key(self):
        chains = get_available_chains(SubgraphType.STAKING, api_key=API_KEY)
        assert len(chains) >= 3  # at least mode, ethereum, gnosis


class TestAllChains:
    def test_all_chains_not_empty(self):
        assert len(ALL_CHAINS) >= 8

    def test_all_chains_sorted(self):
        assert ALL_CHAINS == sorted(ALL_CHAINS)
