"""Tests for the GraphQL client."""

import time
from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.subgraph.client import (
    _QUERY_CACHE,
    GraphQLClient,
    SubgraphError,
    clear_cache,
)

ENDPOINT = "https://example.com/subgraph"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear query cache before each test."""
    clear_cache()
    yield
    clear_cache()


class TestGraphQLClient:
    """Tests for GraphQLClient."""

    def test_query_success(self):
        client = GraphQLClient(ENDPOINT)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"services": [{"id": "1"}]}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_resp):
            result = client.query("{ services { id } }")

        assert result == {"services": [{"id": "1"}]}

    def test_query_graphql_error(self):
        client = GraphQLClient(ENDPOINT)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errors": [{"message": "Field 'foo' not found"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_resp):
            with pytest.raises(SubgraphError, match="Field 'foo' not found"):
                client.query("{ foo }")

    def test_query_http_error(self):
        from requests.exceptions import ConnectionError as ReqConnectionError

        client = GraphQLClient(ENDPOINT)
        with patch.object(
            client.session,
            "post",
            side_effect=ReqConnectionError("Connection refused"),
        ):
            with pytest.raises(SubgraphError, match="HTTP error"):
                client.query("{ services { id } }")

    def test_query_caching(self):
        client = GraphQLClient(ENDPOINT, cache_ttl=60)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"count": 42}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
            result1 = client.query("{ count }")
            result2 = client.query("{ count }")

        assert result1 == result2 == {"count": 42}
        assert mock_post.call_count == 1  # second call hit cache

    def test_query_cache_skip(self):
        client = GraphQLClient(ENDPOINT, cache_ttl=60)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"count": 42}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
            client.query("{ count }", cache_ttl=0)
            client.query("{ count }", cache_ttl=0)

        assert mock_post.call_count == 2  # no caching

    def test_query_all_pagination(self):
        client = GraphQLClient(ENDPOINT)

        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {
            "data": {"services": [{"id": "1"}, {"id": "2"}]},
        }
        page1_resp.raise_for_status = MagicMock()

        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {
            "data": {"services": [{"id": "3"}]},
        }
        page2_resp.raise_for_status = MagicMock()

        with patch.object(
            client.session,
            "post",
            side_effect=[page1_resp, page2_resp],
        ):
            result = client.query_all(
                "query($lastId: String!, $pageSize: Int!) { services(first: $pageSize, where: {id_gt: $lastId}) { id } }",
                "services",
                page_size=2,
            )

        assert len(result) == 3
        assert result[0]["id"] == "1"
        assert result[2]["id"] == "3"

    def test_query_all_empty(self):
        client = GraphQLClient(ENDPOINT)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"services": []}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client.session, "post", return_value=mock_resp):
            result = client.query_all("query { ... }", "services")

        assert result == []

    def test_clear_cache(self):
        _QUERY_CACHE["test_key"] = (time.time(), {"test": True})
        assert len(_QUERY_CACHE) == 1
        clear_cache()
        assert len(_QUERY_CACHE) == 0

    def test_cache_key_includes_endpoint(self):
        """Cache keys must differ for different endpoints with the same query.

        Regression: _cache_key previously only hashed the query text,
        so the same query sent to two different subgraph endpoints
        (e.g. Gnosis vs Base tokenomics) returned the cached result
        from whichever endpoint was queried first.
        """
        client_a = GraphQLClient("https://subgraph.example.com/gnosis", cache_ttl=60)
        client_b = GraphQLClient("https://subgraph.example.com/base", cache_ttl=60)

        resp_a = MagicMock()
        resp_a.status_code = 200
        resp_a.json.return_value = {"data": {"tokens": [{"balance": "1000"}]}}
        resp_a.raise_for_status = MagicMock()

        resp_b = MagicMock()
        resp_b.status_code = 200
        resp_b.json.return_value = {"data": {"tokens": [{"balance": "9999"}]}}
        resp_b.raise_for_status = MagicMock()

        query = "{ tokens(first: 1) { balance } }"

        with patch.object(client_a.session, "post", return_value=resp_a):
            result_a = client_a.query(query)

        with patch.object(client_b.session, "post", return_value=resp_b) as mock_b:
            result_b = client_b.query(query)

        # Must have called the network for client_b (not returned client_a's cache)
        assert mock_b.call_count == 1
        assert result_a == {"tokens": [{"balance": "1000"}]}
        assert result_b == {"tokens": [{"balance": "9999"}]}

    def test_close(self):
        client = GraphQLClient(ENDPOINT)
        with patch.object(client.session, "close") as mock_close:
            client.close()
            mock_close.assert_called_once()
