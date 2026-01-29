"""Tests for ChainList RPC enrichment and quality probing."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from iwa.core.chainlist import (
    ChainlistRPC,
    RPCNode,
    _is_template_url,
    _normalize_url,
    probe_rpc,
)


@pytest.fixture(autouse=True)
def mock_chainlist_enrichment():
    """Override conftest — allow real enrichment calls in this test file."""
    yield


class TestNormalizeUrl:
    """Test URL normalization for deduplication."""

    def test_strips_trailing_slash(self):
        assert _normalize_url("https://rpc.example.com/") == "https://rpc.example.com"

    def test_lowercases(self):
        assert _normalize_url("https://RPC.Example.COM") == "https://rpc.example.com"

    def test_no_change_needed(self):
        assert _normalize_url("https://rpc.example.com") == "https://rpc.example.com"


class TestIsTemplateUrl:
    """Test template URL detection."""

    def test_dollar_brace(self):
        assert _is_template_url("https://rpc.example.com/${API_KEY}") is True

    def test_plain_brace(self):
        assert _is_template_url("https://rpc.example.com/{api_key}") is True

    def test_no_template(self):
        assert _is_template_url("https://rpc.example.com") is False


class TestProbeRpc:
    """Test single RPC probing."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for probe_rpc tests."""
        with patch("iwa.core.chainlist.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            # Make it work as context manager too
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            yield mock_session

    def test_success(self, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "0x1A4B5C", "id": 1}
        mock_session.post.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com")

        assert result is not None
        url, latency, block = result
        assert url == "https://rpc.example.com"
        assert latency > 0
        assert block == 0x1A4B5C
        # Verify session was closed
        mock_session.close.assert_called_once()

    def test_timeout_returns_none(self, mock_session):
        mock_session.post.side_effect = requests.exceptions.Timeout("timed out")

        result = probe_rpc("https://slow.example.com")
        assert result is None
        # Session still closed on error
        mock_session.close.assert_called_once()

    def test_connection_error_returns_none(self, mock_session):
        mock_session.post.side_effect = requests.exceptions.ConnectionError("refused")

        result = probe_rpc("https://dead.example.com")
        assert result is None
        mock_session.close.assert_called_once()

    def test_zero_block_returns_none(self, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "0x0", "id": 1}
        mock_session.post.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com")
        assert result is None

    def test_null_result_returns_none(self, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": None, "id": 1}
        mock_session.post.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com")
        assert result is None

    def test_error_response_returns_none(self, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request"},
            "id": 1,
        }
        mock_session.post.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com")
        assert result is None

    def test_uses_provided_session(self):
        """When a session is provided, use it instead of creating one."""
        provided_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "0x100", "id": 1}
        provided_session.post.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com", session=provided_session)

        assert result is not None
        provided_session.post.assert_called_once()
        # Should NOT close provided session (caller's responsibility)
        provided_session.close.assert_not_called()


class TestGetValidatedRpcs:
    """Test ChainlistRPC.get_validated_rpcs()."""

    def _make_node(self, url, tracking="none"):
        return RPCNode(url=url, is_working=True, tracking=tracking)

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_filters_template_urls(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("https://rpc.example.com/${API_KEY}"),
            self._make_node("https://good.example.com"),
        ]
        mock_probe.return_value = ("https://good.example.com", 50.0, 1000)

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        assert result == ["https://good.example.com"]

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_filters_non_https(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("http://insecure.example.com"),
            self._make_node("wss://ws.example.com"),
            self._make_node("https://good.example.com"),
        ]
        mock_probe.return_value = ("https://good.example.com", 50.0, 1000)

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        assert result == ["https://good.example.com"]

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_deduplicates_existing(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("https://already.configured.com"),
            self._make_node("https://new.example.com"),
        ]
        mock_probe.return_value = ("https://new.example.com", 50.0, 1000)

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(
            100, existing_rpcs=["https://already.configured.com/"]
        )

        assert result == ["https://new.example.com"]

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_filters_stale_rpcs(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("https://fresh.example.com"),
            self._make_node("https://stale.example.com"),
            self._make_node("https://also-fresh.example.com"),
        ]
        # fresh=1000, stale=900 (100 blocks behind), also-fresh=999
        mock_probe.side_effect = [
            ("https://fresh.example.com", 50.0, 1000),
            ("https://stale.example.com", 30.0, 900),
            ("https://also-fresh.example.com", 60.0, 999),
        ]

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        # Stale RPC (900) is 100 blocks behind median (999) > MAX_BLOCK_LAG
        assert "https://stale.example.com" not in result
        assert "https://fresh.example.com" in result
        assert "https://also-fresh.example.com" in result

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_sorts_by_latency(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("https://slow.example.com"),
            self._make_node("https://fast.example.com"),
            self._make_node("https://medium.example.com"),
        ]
        mock_probe.side_effect = [
            ("https://slow.example.com", 200.0, 1000),
            ("https://fast.example.com", 10.0, 1000),
            ("https://medium.example.com", 80.0, 1000),
        ]

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        assert result == [
            "https://fast.example.com",
            "https://medium.example.com",
            "https://slow.example.com",
        ]

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_respects_max_results(self, mock_probe, mock_get_rpcs):
        nodes = [self._make_node(f"https://rpc{i}.example.com") for i in range(10)]
        mock_get_rpcs.return_value = nodes
        mock_probe.side_effect = [
            (f"https://rpc{i}.example.com", float(i * 10), 1000) for i in range(10)
        ]

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[], max_results=3)

        assert len(result) == 3

    @patch.object(ChainlistRPC, "get_rpcs")
    def test_returns_empty_on_no_rpcs(self, mock_get_rpcs):
        mock_get_rpcs.return_value = []

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        assert result == []

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("iwa.core.chainlist.probe_rpc")
    def test_returns_empty_when_all_probes_fail(self, mock_probe, mock_get_rpcs):
        mock_get_rpcs.return_value = [
            self._make_node("https://dead1.example.com"),
            self._make_node("https://dead2.example.com"),
        ]
        mock_probe.return_value = None

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])

        assert result == []


class TestEnrichFromChainlist:
    """Test ChainInterface._enrich_rpcs_from_chainlist().

    The conftest fixture is overridden in this file so the real
    enrichment method runs during __init__.
    """

    @patch("iwa.core.chain.interface.Web3")
    def test_skipped_for_tenderly(self, mock_web3):
        from iwa.core.chain.interface import ChainInterface
        from iwa.core.chain.models import SupportedChain

        chain = MagicMock(spec=SupportedChain)
        chain.name = "TestChain"
        chain.rpcs = ["https://virtual.tenderly.co/test"]
        chain.rpc = "https://virtual.tenderly.co/test"
        chain.chain_id = 100

        with patch("iwa.core.chainlist.ChainlistRPC") as mock_cl_cls:
            ci = ChainInterface(chain)

        # is_tenderly=True → enrichment skipped → ChainlistRPC never called
        assert "tenderly" in ci.current_rpc.lower()
        mock_cl_cls.assert_not_called()

    @patch("iwa.core.chain.interface.Web3")
    def test_enriches_non_tenderly(self, mock_web3):
        from iwa.core.chain.interface import ChainInterface
        from iwa.core.chain.models import SupportedChain

        chain = MagicMock(spec=SupportedChain)
        chain.name = "TestChain"
        chain.rpcs = ["https://rpc1.example.com"]
        chain.rpc = "https://rpc1.example.com"
        chain.chain_id = 100

        with patch("iwa.core.chainlist.ChainlistRPC") as mock_cl_cls:
            mock_cl = mock_cl_cls.return_value
            mock_cl.get_validated_rpcs.return_value = [
                "https://extra1.example.com",
                "https://extra2.example.com",
            ]
            ChainInterface(chain)

        assert len(chain.rpcs) == 3
        assert "https://extra1.example.com" in chain.rpcs
        assert "https://extra2.example.com" in chain.rpcs
        # Original RPC stays first
        assert chain.rpcs[0] == "https://rpc1.example.com"

    @patch("iwa.core.chain.interface.Web3")
    def test_survives_fetch_failure(self, mock_web3):
        from iwa.core.chain.interface import ChainInterface
        from iwa.core.chain.models import SupportedChain

        chain = MagicMock(spec=SupportedChain)
        chain.name = "TestChain"
        chain.rpcs = ["https://rpc1.example.com"]
        chain.rpc = "https://rpc1.example.com"
        chain.chain_id = 100

        with patch("iwa.core.chainlist.ChainlistRPC") as mock_cl_cls:
            mock_cl_cls.side_effect = Exception("network error")
            ChainInterface(chain)

        # Should still work with original RPCs
        assert chain.rpcs == ["https://rpc1.example.com"]

    @patch("iwa.core.chain.interface.Web3")
    def test_respects_max_rpcs(self, mock_web3):
        from iwa.core.chain.interface import ChainInterface
        from iwa.core.chain.models import SupportedChain

        chain = MagicMock(spec=SupportedChain)
        chain.name = "TestChain"
        chain.rpcs = [f"https://rpc{i}.example.com" for i in range(20)]
        chain.rpc = "https://rpc0.example.com"
        chain.chain_id = 100

        with patch("iwa.core.chainlist.ChainlistRPC") as mock_cl_cls:
            ChainInterface(chain)

        # Already at MAX_RPCS=20, ChainlistRPC should not be called
        mock_cl_cls.assert_not_called()
