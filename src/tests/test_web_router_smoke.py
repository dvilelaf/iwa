"""Smoke tests for web API router endpoints — each returns 200 with mocked data."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock heavy dependencies BEFORE importing the app
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth, wallet
    from iwa.web.server import app


async def override_verify_auth():
    return True


app.dependency_overrides[verify_auth] = override_verify_auth


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_mocks():
    yield
    wallet.balance_service = MagicMock()
    wallet.account_service = MagicMock()
    wallet.key_storage = MagicMock()


# ---- /api/state ----


def test_state_endpoint(client):
    """GET /api/state returns 200 with chain info."""
    with patch("iwa.web.routers.state.ChainInterfaces") as mock_ci:
        mock_interface = MagicMock()
        mock_interface.chain.native_currency = "xDAI"
        mock_interface.tokens = {"OLAS": "0xAddr"}
        mock_ci.return_value.items.return_value = [("gnosis", mock_interface)]
        mock_ci.return_value.gnosis.is_tenderly = False
        with patch("iwa.web.routers.state.Config") as mock_config:
            mock_config.return_value.core = None
            resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "chains" in data
    assert "tokens" in data


# ---- /api/rpc-status ----


def test_rpc_status_endpoint(client):
    """GET /api/rpc-status returns 200."""
    with patch("iwa.web.routers.state.ChainInterfaces") as mock_ci:
        mock_interface = MagicMock()
        mock_interface.web3.eth.block_number = 12345
        mock_interface.chain.rpcs = ["https://rpc.example.com"]
        mock_ci.return_value.items.return_value = [("gnosis", mock_interface)]
        resp = client.get("/api/rpc-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "gnosis" in data
    assert data["gnosis"]["status"] == "online"


# ---- /api/accounts ----


def test_accounts_endpoint(client):
    """GET /api/accounts returns 200."""
    wallet.get_accounts_balances.return_value = (
        {"0xAddr": MagicMock(tag="master")},
        {"0xAddr": {"native": 1.0}},
    )
    with patch("iwa.web.routers.accounts.ChainInterfaces") as mock_ci:
        mock_ci.return_value.get.return_value.chain.tokens = {"OLAS": "0x1"}
        resp = client.get("/api/accounts?chain=gnosis")
    assert resp.status_code == 200


# ---- /api/transactions ----


def test_transactions_endpoint(client):
    """GET /api/transactions returns 200."""

    with patch("iwa.web.routers.transactions.SentTransaction") as mock_tx:
        # Peewee fields use operator overloading — mock timestamp
        # to support > comparison and .desc() chaining
        mock_timestamp_field = MagicMock()
        mock_timestamp_field.__gt__ = MagicMock(return_value=MagicMock())
        mock_timestamp_field.desc.return_value = MagicMock()
        mock_tx.timestamp = mock_timestamp_field

        mock_chain_field = MagicMock()
        mock_chain_field.__eq__ = MagicMock(return_value=MagicMock())
        mock_tx.chain = mock_chain_field

        mock_tx.select.return_value.where.return_value.order_by.return_value = []
        resp = client.get("/api/transactions?chain=gnosis")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---- /api/swap/wrap/balance ----


def test_swap_wrap_balance_endpoint(client):
    """GET /api/swap/wrap/balance returns 200."""
    wallet.balance_service.get_native_balance_wei.return_value = 10**18
    wallet.balance_service.get_erc20_balance_wei.return_value = 5 * 10**18
    resp = client.get("/api/swap/wrap/balance?account=master&chain=gnosis")
    assert resp.status_code == 200
    data = resp.json()
    assert "native" in data
    assert "wxdai" in data


# ---- /api/swap/max-amount ----


def test_swap_max_amount_sell_mode(client):
    """GET /api/swap/max-amount in sell mode returns max balance."""
    wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    with patch("iwa.web.routers.swap.ChainInterfaces") as mock_ci:
        mock_chain = MagicMock()
        mock_chain.chain.get_token_address.return_value = "0xTokenAddr"
        mock_ci.return_value.get.return_value = mock_chain
        with patch("iwa.web.routers.swap.get_cached_decimals", return_value=18):
            resp = client.get(
                "/api/swap/max-amount?account=master&sell_token=OLAS&buy_token=WXDAI&mode=sell"
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_amount"] == 1.0


# ---- /api/swap/orders ----


def test_swap_orders_endpoint(client):
    """GET /api/swap/orders returns 200 with mocked CowSwap API."""
    mock_account = MagicMock()
    mock_account.address = "0xAddr"
    wallet.account_service.resolve_account.return_value = mock_account

    with (
        patch("iwa.web.routers.swap.ChainInterfaces") as mock_ci,
        patch("requests.get") as mock_requests_get,
    ):
        mock_ci.return_value.get.return_value.chain.chain_id = 100
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_requests_get.return_value = mock_resp

        resp = client.get("/api/swap/orders?account=master&chain=gnosis")

    assert resp.status_code == 200
    data = resp.json()
    assert "orders" in data


# ---- /api/rewards/claims ----


def test_rewards_claims_endpoint(client):
    """GET /api/rewards/claims returns 200."""
    with patch("iwa.web.routers.rewards.SentTransaction") as mock_tx:
        mock_tx.tags.contains.return_value = MagicMock()
        mock_tx.timestamp.__ge__ = MagicMock()
        mock_tx.timestamp.__lt__ = MagicMock()
        mock_query = MagicMock()
        mock_query.__and__ = MagicMock(return_value=mock_query)
        mock_tx.select.return_value.where.return_value.order_by.return_value = []
        resp = client.get("/api/rewards/claims?year=2025")
    assert resp.status_code == 200


# ---- /api/subgraph/chains ----


def test_subgraph_chains_endpoint(client):
    """GET /api/subgraph/chains returns 200."""
    with patch("iwa.web.routers.subgraph._get_client") as mock_client:
        mock_client.return_value.api_key = "fake"
        with patch("iwa.web.routers.subgraph.get_available_chains", return_value=["gnosis"]):
            with patch("iwa.web.routers.subgraph.response_cache") as mock_cache:
                mock_cache.get_or_compute.side_effect = lambda k, fn, ttl: fn()
                resp = client.get("/api/subgraph/chains")
    assert resp.status_code == 200
