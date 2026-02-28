"""Tests for rewards router endpoints."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth
    from iwa.web.server import app


async def override_verify_auth():
    return True


app.dependency_overrides[verify_auth] = override_verify_auth


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


def _make_mock_tx(
    tx_hash="0xabc123",
    amount_wei="10000000000000000000",
    price_eur=1.50,
    value_eur=15.0,
    timestamp=None,
    tags='["olas_claim_rewards", "staking_reward"]',
    chain="gnosis",
    to_tag="test_trader",
):
    tx = MagicMock()
    tx.tx_hash = tx_hash
    tx.amount_wei = amount_wei
    tx.price_eur = price_eur
    tx.value_eur = value_eur
    tx.timestamp = timestamp or datetime.datetime(2026, 1, 15, 10, 30, 0)
    tx.tags = tags
    tx.chain = chain
    tx.to_tag = to_tag
    tx.to_address = "0x2222222222222222222222222222222222222222"
    return tx


def test_get_claims(client):
    mock_txs = [
        _make_mock_tx(tx_hash="0x111", timestamp=datetime.datetime(2026, 1, 10)),
        _make_mock_tx(tx_hash="0x222", timestamp=datetime.datetime(2026, 2, 20)),
    ]

    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs):
        response = client.get("/api/rewards/claims?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["tx_hash"] == "0x111"
    assert data[0]["olas_amount"] == 10.0
    assert data[0]["price_eur"] == 1.5
    assert data[0]["value_eur"] == 15.0
    assert data[0]["service_name"] == "test_trader"
    assert "gnosisscan.io" in data[0]["explorer_url"]


def test_get_claims_with_month_filter(client):
    mock_txs = [_make_mock_tx(tx_hash="0x333", timestamp=datetime.datetime(2026, 3, 5))]

    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs) as mock_query:
        response = client.get("/api/rewards/claims?year=2026&month=3")

    assert response.status_code == 200
    mock_query.assert_called_once_with(2026, 3)


def test_get_claims_invalid_year(client):
    response = client.get("/api/rewards/claims?year=1900")
    assert response.status_code == 400


def test_get_claims_invalid_month(client):
    response = client.get("/api/rewards/claims?year=2026&month=13")
    assert response.status_code == 400


def test_get_summary(client):
    mock_txs = [
        _make_mock_tx(
            tx_hash="0xA", timestamp=datetime.datetime(2026, 1, 10), amount_wei="5000000000000000000",
            price_eur=1.0, value_eur=5.0,
        ),
        _make_mock_tx(
            tx_hash="0xB", timestamp=datetime.datetime(2026, 1, 20), amount_wei="3000000000000000000",
            price_eur=1.2, value_eur=3.6,
        ),
        _make_mock_tx(
            tx_hash="0xC", timestamp=datetime.datetime(2026, 3, 15), amount_wei="10000000000000000000",
            price_eur=1.5, value_eur=15.0,
        ),
    ]

    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs):
        response = client.get("/api/rewards/summary?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert data["year"] == 2026
    assert data["total_claims"] == 3
    assert data["total_olas"] == pytest.approx(18.0, abs=0.01)
    assert data["total_eur"] == pytest.approx(23.6, abs=0.01)

    # Net profit fields present (no costs in mock, so net ≈ gross - tax)
    assert "total_costs" in data
    assert "total_tax" in data
    assert "total_net" in data
    assert "effective_tax_rate" in data
    assert "total_eure_withdrawn" in data
    assert data["total_costs"] >= 0
    # With 0 costs, net = gross - tax
    assert data["total_net"] == pytest.approx(
        data["total_eur"] - data["total_tax"], abs=0.01
    )

    # January should have 2 claims
    jan = data["months"][0]
    assert jan["month"] == 1
    assert jan["claims"] == 2
    assert jan["olas"] == pytest.approx(8.0, abs=0.01)
    # Monthly net profit fields
    assert "costs" in jan
    assert "tax" in jan
    assert "net" in jan

    # March should have 1 claim
    mar = data["months"][2]
    assert mar["month"] == 3
    assert mar["claims"] == 1

    # February should be empty
    feb = data["months"][1]
    assert feb["claims"] == 0
    assert feb["net"] == 0.0


def test_export_csv(client):
    mock_txs = [
        _make_mock_tx(tx_hash="0xExport1", timestamp=datetime.datetime(2026, 2, 14)),
    ]

    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs):
        response = client.get("/api/rewards/export?year=2026")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert 'olas_rewards_2026.csv' in response.headers["content-disposition"]

    content = response.text
    assert "Date" in content  # Header row
    assert "0xExport1" in content
    assert "gnosisscan.io" in content
    assert "10.000000" in content  # OLAS amount


def test_export_csv_with_month(client):
    with patch("iwa.web.routers.rewards._query_claims", return_value=[]) as mock_query:
        response = client.get("/api/rewards/export?year=2026&month=5")

    assert response.status_code == 200
    assert 'olas_rewards_2026_05.csv' in response.headers["content-disposition"]
    mock_query.assert_called_once_with(2026, 5)


def test_get_summary_empty_year(client):
    with patch("iwa.web.routers.rewards._query_claims", return_value=[]):
        response = client.get("/api/rewards/summary?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert data["total_claims"] == 0
    assert data["total_olas"] == 0.0
    assert data["total_eur"] == 0.0
    assert data["total_costs"] == 0.0
    assert data["total_tax"] == 0.0
    assert data["total_net"] == 0.0
    assert data["effective_tax_rate"] == 0.0
    assert data["total_eure_withdrawn"] == 0.0
    assert len(data["months"]) == 12


def test_get_summary_with_costs(client):
    """Test summary includes mech request costs and gas."""
    mock_claims = [
        _make_mock_tx(
            tx_hash="0xR1", timestamp=datetime.datetime(2026, 2, 10),
            amount_wei="50000000000000000000", price_eur=0.05, value_eur=2.5,
        ),
    ]

    # Mech costs: 1.0 EUR total, all in February
    with (
        patch("iwa.web.routers.rewards._query_claims", return_value=mock_claims),
        patch("iwa.web.routers.rewards._calculate_mech_costs", return_value=(1.0, {2: 1.0})),
        patch("iwa.web.routers.rewards._query_gas_costs", return_value=0.1),
    ):
        response = client.get("/api/rewards/summary?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert data["total_eur"] == pytest.approx(2.5, abs=0.01)
    assert data["total_costs"] == pytest.approx(1.1, abs=0.01)  # 1.0 mech + 0.1 gas
    # Profit = 2.5 - 1.1 = 1.4, tax at 19% = 0.266
    assert data["total_tax"] == pytest.approx(0.27, abs=0.01)
    assert data["total_net"] == pytest.approx(1.13, abs=0.01)
    assert data["effective_tax_rate"] == pytest.approx(19.0, abs=0.1)


def test_savings_tax_brackets():
    """Test IRPF progressive tax calculation."""
    from iwa.web.routers.rewards import _calculate_savings_tax

    # Below first bracket: 19%
    tax, rate = _calculate_savings_tax(1000)
    assert tax == pytest.approx(190, abs=0.01)
    assert rate == pytest.approx(0.19, abs=0.001)

    # Zero profit: no tax
    tax, rate = _calculate_savings_tax(0)
    assert tax == 0.0
    assert rate == 0.0

    # Negative profit: no tax
    tax, rate = _calculate_savings_tax(-500)
    assert tax == 0.0
    assert rate == 0.0

    # Crosses into second bracket: 6000*0.19 + 4000*0.21 = 1140+840 = 1980
    tax, rate = _calculate_savings_tax(10000)
    assert tax == pytest.approx(1980, abs=0.01)


def test_by_trader_breakdown(client):
    """Test per-trader breakdown with multiple traders."""
    mock_txs = [
        _make_mock_tx(
            tx_hash="0xT1A", to_tag="trader_alpha",
            timestamp=datetime.datetime(2026, 1, 5),
            amount_wei="8000000000000000000", price_eur=1.0, value_eur=8.0,
        ),
        _make_mock_tx(
            tx_hash="0xT2A", to_tag="trader_beta",
            timestamp=datetime.datetime(2026, 1, 10),
            amount_wei="5000000000000000000", price_eur=1.2, value_eur=6.0,
        ),
        _make_mock_tx(
            tx_hash="0xT1B", to_tag="trader_alpha",
            timestamp=datetime.datetime(2026, 3, 20),
            amount_wei="12000000000000000000", price_eur=1.5, value_eur=18.0,
        ),
    ]

    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs):
        response = client.get("/api/rewards/by-trader?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert data["year"] == 2026

    # trader_alpha has more EUR, so sorted first
    traders = data["traders"]
    assert len(traders) == 2
    assert traders[0]["name"] == "trader_alpha"
    assert traders[0]["total_claims"] == 2
    assert traders[0]["total_olas"] == pytest.approx(20.0, abs=0.01)
    assert traders[0]["total_eur"] == pytest.approx(26.0, abs=0.01)
    assert traders[0]["avg_price_eur"] == pytest.approx(1.25, abs=0.01)

    assert traders[1]["name"] == "trader_beta"
    assert traders[1]["total_claims"] == 1
    assert traders[1]["total_olas"] == pytest.approx(5.0, abs=0.01)

    # trader_alpha January data
    alpha_jan = traders[0]["months"][0]
    assert alpha_jan["month"] == 1
    assert alpha_jan["claims"] == 1
    assert alpha_jan["olas"] == pytest.approx(8.0, abs=0.01)

    # Cumulative series
    cum = data["cumulative"]
    assert len(cum) == 3
    assert cum[0]["olas"] == pytest.approx(8.0, abs=0.01)
    assert cum[0]["trader"] == "trader_alpha"
    assert cum[1]["olas"] == pytest.approx(13.0, abs=0.01)  # 8 + 5
    assert cum[2]["olas"] == pytest.approx(25.0, abs=0.01)  # 8 + 5 + 12
    assert cum[2]["eur"] == pytest.approx(32.0, abs=0.01)   # 8 + 6 + 18


def test_by_trader_empty(client):
    """Test per-trader breakdown with no data."""
    with patch("iwa.web.routers.rewards._query_claims", return_value=[]):
        response = client.get("/api/rewards/by-trader?year=2026")

    assert response.status_code == 200
    data = response.json()
    assert data["traders"] == []
    assert data["cumulative"] == []


def test_export_csv_includes_service(client):
    """Test CSV export includes Service column."""
    mock_txs = [
        _make_mock_tx(tx_hash="0xSvc1", to_tag="trader_alpha",
                      timestamp=datetime.datetime(2026, 4, 1)),
    ]
    with patch("iwa.web.routers.rewards._query_claims", return_value=mock_txs):
        response = client.get("/api/rewards/export?year=2026")

    assert response.status_code == 200
    content = response.text
    assert "Service" in content  # Header row
    assert "trader_alpha" in content


# --- EURe withdrawal tests ---

MASTER_ADDR = "0x1111111111111111111111111111111111111111"
OTHER_ADDR = "0x2222222222222222222222222222222222222222"
EURE_BRIDGED = "0xcB444e90D8198415266c6a2724b7900fb12FC56E"
EURE_MONERIUM = "0x420CA0f9B9b604cE0fd9C18EF134C705e5Fa3430"


def _make_eure_tx(
    tx_hash="0xEURE1",
    from_address=MASTER_ADDR,
    token="EURE",
    amount_wei="100000000000000000000",  # 100 EURE
    timestamp=None,
):
    """Create a mock EURe withdrawal transaction."""
    tx = MagicMock()
    tx.tx_hash = tx_hash
    tx.from_address = from_address
    tx.token = token
    tx.amount_wei = amount_wei
    tx.timestamp = timestamp or datetime.datetime(2026, 2, 15)
    tx.tags = '["erc20-transfer", "safe-transaction"]'
    return tx


def _run_query_eure_withdrawn(mock_txs, year=2026, month=None):
    """Helper to run _query_eure_withdrawn with mocked DB."""
    from iwa.web.routers.rewards import _query_eure_withdrawn

    with (
        patch("iwa.web.routers.rewards.wallet") as mock_wallet,
        patch("iwa.web.routers.rewards.SentTransaction.select") as mock_select,
    ):
        mock_wallet.master_account.address = MASTER_ADDR
        mock_select.return_value.where.return_value = mock_txs

        return _query_eure_withdrawn(year, month)


def test_query_eure_withdrawn_by_symbol():
    """Test _query_eure_withdrawn matches token='EURE'."""
    mock_txs = [
        _make_eure_tx(token="EURE", amount_wei="50000000000000000000"),  # 50
        _make_eure_tx(tx_hash="0xE2", token="EURE", amount_wei="25000000000000000000"),  # 25
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(75.0, abs=0.01)


def test_query_eure_withdrawn_by_bridged_contract():
    """Test _query_eure_withdrawn matches bridged EURe contract address."""
    mock_txs = [
        _make_eure_tx(token=EURE_BRIDGED, amount_wei="30000000000000000000"),
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(30.0, abs=0.01)


def test_query_eure_withdrawn_by_monerium_contract():
    """Test _query_eure_withdrawn matches Monerium native EURe contract."""
    mock_txs = [
        _make_eure_tx(token=EURE_MONERIUM, amount_wei="20000000000000000000"),
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(20.0, abs=0.01)


def test_query_eure_withdrawn_ignores_other_tokens():
    """Test _query_eure_withdrawn skips non-EURE tokens."""
    mock_txs = [
        _make_eure_tx(token="EURE", amount_wei="50000000000000000000"),
        _make_eure_tx(tx_hash="0xOLAS", token="OLAS", amount_wei="999000000000000000000"),
        _make_eure_tx(tx_hash="0xDAI", token="WXDAI", amount_wei="999000000000000000000"),
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(50.0, abs=0.01)


def test_query_eure_withdrawn_ignores_non_master():
    """Test _query_eure_withdrawn only counts transfers from master."""
    mock_txs = [
        _make_eure_tx(from_address=MASTER_ADDR, amount_wei="50000000000000000000"),
        _make_eure_tx(
            tx_hash="0xOther", from_address=OTHER_ADDR,
            amount_wei="200000000000000000000",
        ),
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(50.0, abs=0.01)


def test_query_eure_withdrawn_empty():
    """Test _query_eure_withdrawn returns 0 with no matching transactions."""
    assert _run_query_eure_withdrawn([]) == 0.0


def test_query_eure_withdrawn_with_month_filter():
    """Test _query_eure_withdrawn applies month filter."""
    mock_txs = [
        _make_eure_tx(token="EURE", amount_wei="40000000000000000000"),
    ]
    result = _run_query_eure_withdrawn(mock_txs, year=2026, month=2)
    assert result == pytest.approx(40.0, abs=0.01)


def test_query_eure_withdrawn_with_december_filter():
    """Test _query_eure_withdrawn handles December (month=12) edge case."""
    mock_txs = [
        _make_eure_tx(token="EURE", amount_wei="15000000000000000000"),
    ]
    result = _run_query_eure_withdrawn(mock_txs, year=2026, month=12)
    assert result == pytest.approx(15.0, abs=0.01)


def test_query_eure_withdrawn_case_insensitive():
    """Test _query_eure_withdrawn handles mixed-case token and addresses."""
    mock_txs = [
        _make_eure_tx(token="eure", amount_wei="10000000000000000000"),
        _make_eure_tx(
            tx_hash="0xE2", token=EURE_BRIDGED.upper(),
            amount_wei="10000000000000000000",
        ),
    ]
    assert _run_query_eure_withdrawn(mock_txs) == pytest.approx(20.0, abs=0.01)


def test_get_summary_with_eure_withdrawn(client):
    """Test summary endpoint includes EURe withdrawal total."""
    mock_claims = [
        _make_mock_tx(
            tx_hash="0xW1", timestamp=datetime.datetime(2026, 2, 10),
            amount_wei="50000000000000000000", price_eur=1.0, value_eur=50.0,
        ),
    ]

    with (
        patch("iwa.web.routers.rewards._query_claims", return_value=mock_claims),
        patch("iwa.web.routers.rewards._calculate_mech_costs", return_value=(10.0, {2: 10.0})),
        patch("iwa.web.routers.rewards._query_gas_costs", return_value=0.5),
        patch("iwa.web.routers.rewards._query_eure_withdrawn", return_value=38.75),
    ):
        response = client.get("/api/rewards/summary?year=2026")

    assert response.status_code == 200
    data = response.json()
    # Pre-tax profit: 50.0 - 10.5 = 39.5
    pre_tax = data["total_eur"] - data["total_costs"]
    assert pre_tax == pytest.approx(39.5, abs=0.01)
    # EURe withdrawn should be close to pre-tax
    assert data["total_eure_withdrawn"] == pytest.approx(38.75, abs=0.01)
