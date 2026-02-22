"""Tests for ServiceRegistrySubgraph."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.subgraph.client import clear_cache
from iwa.plugins.olas.subgraph.service_registry import ServiceRegistrySubgraph

GNOSIS_ENDPOINT = (
    "https://subgraph.staging.autonolas.tech"
    "/subgraphs/name/service-registry-gnosis-v0_0_1"
)

SERVICE_RAW = {
    "id": "42",
    "multisig": "0xec58bedb8dcdf77ca2baf8b2d8d31204dd3d12ce",
    "agentIds": [25],
    "creationTimestamp": "1700000000",
    "configHash": "0xabcdef",
    "creator": {"id": "0xeb2a22b27c7ad5eee424fd90b376c745e60f914e"},
}


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


class TestGetServices:
    def test_get_all(self):
        registry = ServiceRegistrySubgraph()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        # Page 1 with one service, then empty page
        mock_resp_empty = MagicMock()
        mock_resp_empty.status_code = 200
        mock_resp_empty.raise_for_status = MagicMock()

        mock_resp.json.return_value = {"data": {"services": [SERVICE_RAW]}}
        mock_resp_empty.json.return_value = {"data": {"services": []}}

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.side_effect = [mock_resp, mock_resp_empty]
            mock_session_factory.return_value = mock_session

            # Re-create to use mocked session
            registry = ServiceRegistrySubgraph()
            services = registry.get_services("gnosis")

        assert len(services) == 1
        assert services[0].service_id == 42
        assert services[0].chain == "gnosis"

    def test_get_by_agent_id(self):
        registry = ServiceRegistrySubgraph()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"services": [SERVICE_RAW]}}

        mock_resp_empty = MagicMock()
        mock_resp_empty.status_code = 200
        mock_resp_empty.raise_for_status = MagicMock()
        mock_resp_empty.json.return_value = {"data": {"services": []}}

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.side_effect = [mock_resp, mock_resp_empty]
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            services = registry.get_services("gnosis", agent_id=25)

        assert len(services) == 1
        assert services[0].agent_ids == [25]


class TestGetService:
    def test_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"service": SERVICE_RAW}}

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            svc = registry.get_service("gnosis", 42)

        assert svc is not None
        assert svc.service_id == 42

    def test_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"service": None}}

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            svc = registry.get_service("gnosis", 99999)

        assert svc is None


class TestGetServicesByCreator:
    def test_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "creators": [
                    {
                        "id": "0xeb2a22b27c7ad5eee424fd90b376c745e60f914e",
                        "services": [
                            {
                                "id": "42",
                                "multisig": "0xmultisig",
                                "agentIds": [25],
                                "creationTimestamp": "1700000000",
                                "configHash": "0xhash",
                            }
                        ],
                    }
                ],
            }
        }

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            services = registry.get_services_by_creator(
                "gnosis",
                "0xeb2a22b27c7ad5eee424fd90b376c745e60f914e",
            )

        assert len(services) == 1
        assert services[0].service_id == 42

    def test_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": {"creators": []}}

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            services = registry.get_services_by_creator("gnosis", "0xunknown")

        assert services == []


class TestGetServiceByMultisig:
    def test_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "multisigs": [
                    {
                        "id": "0xmultisig",
                        "serviceId": 42,
                        "creator": "0xcreator",
                        "agentIds": [25],
                        "creationTimestamp": "1700000000",
                    }
                ],
            }
        }

        with patch(
            "iwa.plugins.olas.subgraph.client.create_retry_session"
        ) as mock_session_factory:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_factory.return_value = mock_session

            registry = ServiceRegistrySubgraph()
            ms = registry.get_service_by_multisig("gnosis", "0xmultisig")

        assert ms is not None
        assert ms.service_id == 42


class TestInvalidChain:
    def test_raises_on_unknown_chain(self):
        registry = ServiceRegistrySubgraph()
        with pytest.raises(ValueError, match="No Service Registry endpoint"):
            registry.get_services("solana")
