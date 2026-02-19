"""Additional tests for swap router — targeting missing coverage lines.

Covers: validators (SwapRequest, WrapRequest), get_cached_decimals,
swap_tokens (fulfilled/other status, HTTPException re-raise, None return),
get_swap_quote (buy mode, result conversion), get_swap_max_amount (buy mode,
NoLiquidity), wrap_native, unwrap_native, get_wrap_balances,
get_recent_orders (unsupported chain, non-200, exception),
_process_order_for_frontend (invalid date, non-open status, decimal errors,
amount conversion errors).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Patch Wallet + init_db + ChainInterfaces + auth BEFORE importing the app
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth
    from iwa.web.server import app


# Override auth for all tests
async def _override_verify_auth():
    return True


app.dependency_overrides[verify_auth] = _override_verify_auth


ADDR_ALICE = "0x1111111111111111111111111111111111111111"
ADDR_BOB = "0x2222222222222222222222222222222222222222"
ADDR_SELL = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
ADDR_BUY = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


@pytest.fixture
def client():
    """TestClient for FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Pydantic validators – SwapRequest
# ---------------------------------------------------------------------------


class TestSwapRequestValidation:
    """Cover lines 67, 77, 79, 87, 91 — SwapRequest field validators."""

    def test_empty_account_raises(self):
        """Line 67: empty account → ValueError."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Account cannot be empty"):
            SwapRequest(
                account="",
                sell_token="WXDAI",
                buy_token="OLAS",
                order_type="sell",
            )

    def test_invalid_account_hex_length(self):
        """Line 68-69: 0x prefix but wrong length."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Invalid account format"):
            SwapRequest(
                account="0xDEAD",
                sell_token="WXDAI",
                buy_token="OLAS",
                order_type="sell",
            )

    def test_empty_sell_token_raises(self):
        """Line 77: empty sell_token → ValueError."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Token cannot be empty"):
            SwapRequest(
                account="master",
                sell_token="",
                buy_token="OLAS",
                order_type="sell",
            )

    def test_invalid_token_hex_length(self):
        """Line 79: token starts with 0x but wrong length."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Invalid token address"):
            SwapRequest(
                account="master",
                sell_token="0xBAD",
                buy_token="OLAS",
                order_type="sell",
            )

    def test_amount_none_is_ok(self):
        """Line 87: None amount passes through."""
        from iwa.web.routers.swap import SwapRequest

        req = SwapRequest(
            account="master",
            sell_token="WXDAI",
            buy_token="OLAS",
            order_type="sell",
            amount_eth=None,
        )
        assert req.amount_eth is None

    def test_amount_too_large(self):
        """Line 91: amount > 1e18."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Amount too large"):
            SwapRequest(
                account="master",
                sell_token="WXDAI",
                buy_token="OLAS",
                order_type="sell",
                amount_eth=2e18,
            )


# ---------------------------------------------------------------------------
# Pydantic validators – WrapRequest
# ---------------------------------------------------------------------------


class TestWrapRequestValidation:
    """Cover lines 371-375, 381-385, 391-393 — WrapRequest field validators."""

    def test_empty_account_raises(self):
        """Line 371: empty account → ValueError."""
        from iwa.web.routers.swap import WrapRequest

        with pytest.raises(ValidationError, match="Account cannot be empty"):
            WrapRequest(account="", amount_eth=1.0)

    def test_invalid_account_hex_length(self):
        """Lines 373-374."""
        from iwa.web.routers.swap import WrapRequest

        with pytest.raises(ValidationError, match="Invalid account format"):
            WrapRequest(account="0xBEEF", amount_eth=1.0)

    def test_negative_amount(self):
        """Line 381: amount <= 0."""
        from iwa.web.routers.swap import WrapRequest

        with pytest.raises(ValidationError, match="Amount must be greater than 0"):
            WrapRequest(account="master", amount_eth=-1.0)

    def test_amount_too_large(self):
        """Lines 383-384: amount > 1e18."""
        from iwa.web.routers.swap import WrapRequest

        with pytest.raises(ValidationError, match="Amount too large"):
            WrapRequest(account="master", amount_eth=2e18)

    def test_invalid_chain(self):
        """Lines 391-392."""
        from iwa.web.routers.swap import WrapRequest

        with pytest.raises(ValidationError, match="Invalid chain name"):
            WrapRequest(account="master", amount_eth=1.0, chain="bad!chain")


# ---------------------------------------------------------------------------
# get_cached_decimals
# ---------------------------------------------------------------------------


class TestGetCachedDecimals:
    """Cover line 34: success path (and default 18 on error)."""

    def test_success_returns_decimals(self):
        """Line 34: returns contract.decimals on success."""
        from iwa.web.routers.swap import get_cached_decimals

        # Clear lru_cache for deterministic tests
        get_cached_decimals.cache_clear()

        mock_contract = MagicMock()
        mock_contract.decimals = 6

        with patch("iwa.core.contracts.erc20.ERC20Contract", return_value=mock_contract):
            result = get_cached_decimals("0xABCD1234567890ABCDEF1234567890ABCDEF1234", "gnosis")
            assert result == 6

        get_cached_decimals.cache_clear()

    def test_error_returns_18(self):
        """Fallback: returns 18 on error."""
        from iwa.web.routers.swap import get_cached_decimals

        get_cached_decimals.cache_clear()

        with patch("iwa.core.contracts.erc20.ERC20Contract", side_effect=Exception("rpc fail")):
            result = get_cached_decimals("0xDEAD1234567890ABCDEF1234567890ABCDEF1234", "gnosis")
            assert result == 18

        get_cached_decimals.cache_clear()


# ---------------------------------------------------------------------------
# POST /api/swap — additional swap_tokens branches
# ---------------------------------------------------------------------------


class TestSwapTokensBranches:
    """Cover lines 154-176, 178."""

    def test_fulfilled_status(self, client):
        """Lines 154-167: status == 'fulfilled' branch."""
        with patch(
            "iwa.web.routers.swap.wallet.transfer_service.swap",
            new_callable=AsyncMock,
        ) as mock_swap:
            mock_swap.return_value = {
                "status": "fulfilled",
                "uid": "0xabc123",
                "executedSellAmount": "1000000000000000000",
                "executedBuyAmount": "950000000000000000",
            }

            response = client.post(
                "/api/swap",
                json={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount_eth": 1.0,
                    "order_type": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "executed" in data["message"].lower()
            assert "analytics" in data
            assert data["analytics"]["executed_sell_amount"] == 1e18
            assert data["analytics"]["executed_buy_amount"] == 9.5e17

    def test_other_status(self, client):
        """Lines 168-174: unexpected status like 'expired'."""
        with patch(
            "iwa.web.routers.swap.wallet.transfer_service.swap",
            new_callable=AsyncMock,
        ) as mock_swap:
            mock_swap.return_value = {
                "status": "expired",
                "uid": "0xdef456",
            }

            response = client.post(
                "/api/swap",
                json={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount_eth": 1.0,
                    "order_type": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "expired" in data["message"]

    def test_none_order_data(self, client):
        """Lines 175-176: order_data is None → 400."""
        with patch(
            "iwa.web.routers.swap.wallet.transfer_service.swap",
            new_callable=AsyncMock,
        ) as mock_swap:
            mock_swap.return_value = None

            response = client.post(
                "/api/swap",
                json={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount_eth": 1.0,
                    "order_type": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "Failed to place swap order" in response.json()["detail"]

    def test_httpexception_reraised(self, client):
        """Line 178: HTTPException is re-raised without wrapping."""
        with patch(
            "iwa.web.routers.swap.wallet.transfer_service.swap",
            new_callable=AsyncMock,
        ) as mock_swap:
            mock_swap.side_effect = HTTPException(status_code=403, detail="Forbidden")

            response = client.post(
                "/api/swap",
                json={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount_eth": 1.0,
                    "order_type": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "Forbidden"


# ---------------------------------------------------------------------------
# GET /api/swap/quote — buy mode + result conversion
# ---------------------------------------------------------------------------


class TestSwapQuoteBuyMode:
    """Cover lines 238, 253-258."""

    def _setup_mocks(self):
        """Create common mock objects."""
        mock_wallet = MagicMock()
        mock_account = MagicMock()
        mock_account.address = ADDR_ALICE
        mock_wallet.account_service.resolve_account.return_value = mock_account
        mock_wallet.key_storage.get_signer.return_value = "fake_signer"

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.side_effect = lambda t: (
            ADDR_SELL if t == "WXDAI" else ADDR_BUY
        )

        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_chain_interfaces_cls = MagicMock()
        mock_chain_interfaces_cls.return_value.get.return_value = mock_chain_interface

        return mock_wallet, mock_chain_interfaces_cls

    def test_sell_mode_returns_buy_amount(self, client):
        """Lines 253-254: sell mode → convert result with buy_decimals."""
        mock_wallet, mock_ci = self._setup_mocks()

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
            patch("iwa.web.routers.swap.CowSwap") as mock_cow_cls,
        ):
            mock_cow = MagicMock()
            mock_cow.get_max_buy_amount_wei = AsyncMock(
                return_value=2_000_000_000_000_000_000
            )
            mock_cow_cls.return_value = mock_cow

            response = client.get(
                "/api/swap/quote",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount": "1.0",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["mode"] == "sell"
            assert data["amount"] == 2.0

    def test_buy_mode_returns_sell_amount(self, client):
        """Lines 238, 255-258: buy mode → calls get_max_sell_amount_wei, converts with sell_decimals."""
        mock_wallet, mock_ci = self._setup_mocks()

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
            patch("iwa.web.routers.swap.CowSwap") as mock_cow_cls,
        ):
            mock_cow = MagicMock()
            mock_cow.get_max_sell_amount_wei = AsyncMock(
                return_value=3_000_000_000_000_000_000
            )
            mock_cow_cls.return_value = mock_cow

            response = client.get(
                "/api/swap/quote",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount": "1.0",
                    "mode": "buy",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["mode"] == "buy"
            assert data["amount"] == 3.0


# ---------------------------------------------------------------------------
# GET /api/swap/max-amount — buy mode with CowSwap quote
# ---------------------------------------------------------------------------


class TestSwapMaxAmountBuyMode:
    """Cover lines 308-344, 353."""

    def _build_mocks(self, sell_balance_wei=5_000_000_000_000_000_000):
        mock_wallet = MagicMock()
        mock_account = MagicMock()
        mock_account.address = ADDR_ALICE
        mock_wallet.account_service.resolve_account.return_value = mock_account
        mock_wallet.key_storage.get_signer.return_value = "fake_signer"
        mock_wallet.balance_service.get_erc20_balance_wei.return_value = sell_balance_wei

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.side_effect = lambda t: (
            ADDR_SELL if t == "WXDAI" else ADDR_BUY
        )

        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci_cls = MagicMock()
        mock_ci_cls.return_value.get.return_value = mock_chain_interface

        return mock_wallet, mock_ci_cls

    def test_buy_mode_returns_max_buy(self, client):
        """Lines 308-344: buy mode CowSwap path."""
        mock_wallet, mock_ci = self._build_mocks()

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
            patch("iwa.web.routers.swap.CowSwap") as mock_cow_cls,
        ):
            mock_cow = MagicMock()
            mock_cow.get_max_buy_amount_wei = AsyncMock(
                return_value=10_000_000_000_000_000_000
            )
            mock_cow_cls.return_value = mock_cow

            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "buy",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["mode"] == "buy"
            assert data["max_amount"] == 10.0
            assert "sell_balance" in data

    def test_no_liquidity_error(self, client):
        """Line 353: NoLiquidity error in max-amount."""
        mock_wallet, mock_ci = self._build_mocks()

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
            patch("iwa.web.routers.swap.CowSwap") as mock_cow_cls,
        ):
            mock_cow = MagicMock()
            mock_cow.get_max_buy_amount_wei = AsyncMock(
                side_effect=Exception("NoLiquidity: no route found")
            )
            mock_cow_cls.return_value = mock_cow

            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "buy",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "No liquidity" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/swap/wrap — wrap_native
# ---------------------------------------------------------------------------


class TestWrapNative:
    """Cover lines 404-421."""

    def test_wrap_success(self, client):
        """Lines 404-416: successful wrap."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.wrap_native.return_value = "0xtxhash123"

            response = client.post(
                "/api/swap/wrap",
                json={"account": "master", "amount_eth": 1.5, "chain": "gnosis"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "1.5000" in data["message"]
            assert data["hash"] == "0xtxhash123"

    def test_wrap_returns_none(self, client):
        """Lines 417-418: wrap returns None → 400."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.wrap_native.return_value = None

            response = client.post(
                "/api/swap/wrap",
                json={"account": "master", "amount_eth": 1.0, "chain": "gnosis"},
            )
            assert response.status_code == 400
            assert "Wrap transaction failed" in response.json()["detail"]

    def test_wrap_exception(self, client):
        """Lines 419-421: wrap raises exception."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.wrap_native.side_effect = Exception("RPC fail")

            response = client.post(
                "/api/swap/wrap",
                json={"account": "master", "amount_eth": 1.0, "chain": "gnosis"},
            )
            assert response.status_code == 400
            assert "RPC fail" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/swap/unwrap — unwrap_native
# ---------------------------------------------------------------------------


class TestUnwrapNative:
    """Cover lines 432-449."""

    def test_unwrap_success(self, client):
        """Lines 432-444: successful unwrap."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.unwrap_native.return_value = "0xtxhash456"

            response = client.post(
                "/api/swap/unwrap",
                json={"account": "master", "amount_eth": 2.5, "chain": "gnosis"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "2.5000" in data["message"]
            assert data["hash"] == "0xtxhash456"

    def test_unwrap_returns_none(self, client):
        """Lines 445-446: unwrap returns None → 400."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.unwrap_native.return_value = None

            response = client.post(
                "/api/swap/unwrap",
                json={"account": "master", "amount_eth": 1.0, "chain": "gnosis"},
            )
            assert response.status_code == 400
            assert "Unwrap transaction failed" in response.json()["detail"]

    def test_unwrap_exception(self, client):
        """Lines 447-449: unwrap raises exception."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.transfer_service.unwrap_native.side_effect = Exception("No gas")

            response = client.post(
                "/api/swap/unwrap",
                json={"account": "master", "amount_eth": 1.0, "chain": "gnosis"},
            )
            assert response.status_code == 400
            assert "No gas" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/swap/wrap/balance — get_wrap_balances
# ---------------------------------------------------------------------------


class TestGetWrapBalances:
    """Cover lines 463-476."""

    def test_balances_success(self, client):
        """Lines 463-473: success path."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.balance_service.get_native_balance_wei.return_value = (
                2_000_000_000_000_000_000
            )
            mock_wallet.balance_service.get_erc20_balance_wei.return_value = (
                3_000_000_000_000_000_000
            )

            response = client.get(
                "/api/swap/wrap/balance",
                params={"account": "master", "chain": "gnosis"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["native"] == 2.0
            assert data["wxdai"] == 3.0

    def test_balances_none_values(self, client):
        """Lines 467-468: None balances default to 0."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.balance_service.get_native_balance_wei.return_value = None
            mock_wallet.balance_service.get_erc20_balance_wei.return_value = None

            response = client.get(
                "/api/swap/wrap/balance",
                params={"account": "master", "chain": "gnosis"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["native"] == 0.0
            assert data["wxdai"] == 0.0

    def test_balances_exception(self, client):
        """Lines 474-476: exception → 400."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.balance_service.get_native_balance_wei.side_effect = Exception(
                "connection error"
            )

            response = client.get(
                "/api/swap/wrap/balance",
                params={"account": "master", "chain": "gnosis"},
            )
            assert response.status_code == 400
            assert "connection error" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/swap/orders — edge cases
# ---------------------------------------------------------------------------


class TestGetRecentOrdersEdgeCases:
    """Cover lines 511, 518, 533-535."""

    def test_unsupported_chain_id(self, client):
        """Line 511: chain_id not in api_urls → empty orders."""
        with (
            patch("iwa.web.routers.swap.wallet") as mock_wallet,
            patch("iwa.web.routers.swap.ChainInterfaces") as mock_ci,
        ):
            mock_account = MagicMock()
            mock_account.address = ADDR_ALICE
            mock_wallet.account_service.resolve_account.return_value = mock_account

            mock_chain = MagicMock()
            mock_chain.chain.chain_id = 999  # not in api_urls
            mock_ci.return_value.get.return_value = mock_chain

            response = client.get(
                "/api/swap/orders", params={"account": "master", "chain": "gnosis"}
            )
            assert response.status_code == 200
            assert response.json() == {"orders": []}

    def test_non_200_response(self, client):
        """Line 518: API returns non-200 → empty orders."""
        with (
            patch("iwa.web.routers.swap.wallet") as mock_wallet,
            patch("iwa.web.routers.swap.ChainInterfaces") as mock_ci,
            patch("requests.get") as mock_get,
        ):
            mock_account = MagicMock()
            mock_account.address = ADDR_ALICE
            mock_wallet.account_service.resolve_account.return_value = mock_account

            mock_chain = MagicMock()
            mock_chain.chain.chain_id = 100
            mock_ci.return_value.get.return_value = mock_chain

            mock_get.return_value.status_code = 500

            response = client.get(
                "/api/swap/orders", params={"account": "master", "chain": "gnosis"}
            )
            assert response.status_code == 200
            assert response.json() == {"orders": []}

    def test_exception_returns_empty(self, client):
        """Lines 533-535: any exception → empty orders."""
        with patch("iwa.web.routers.swap.wallet") as mock_wallet:
            mock_wallet.account_service.resolve_account.side_effect = Exception(
                "account error"
            )

            response = client.get(
                "/api/swap/orders", params={"account": "master", "chain": "gnosis"}
            )
            assert response.status_code == 200
            assert response.json() == {"orders": []}


# ---------------------------------------------------------------------------
# _process_order_for_frontend — unit tests
# ---------------------------------------------------------------------------


class TestProcessOrderForFrontend:
    """Cover lines 556-557, 564, 584-585, 589-590, 598-601."""

    def _get_fn(self):
        from iwa.web.routers.swap import _process_order_for_frontend

        return _process_order_for_frontend

    def _make_chain_interface(self, token_name="TOKEN"):
        ci = MagicMock()
        ci.chain.get_token_name.return_value = token_name
        return ci

    def test_invalid_creation_date(self):
        """Lines 556-557: ValueError on date parsing → fallback."""
        fn = self._get_fn()
        ci = self._make_chain_interface()

        order = {
            "uid": "0x" + "a" * 60,
            "status": "open",
            "creationDate": "NOT-A-DATE",
            "validTo": 9999999999,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "1000000000000000000",
            "buyAmount": "900000000000000000",
        }

        with patch("iwa.web.routers.swap.get_cached_decimals", return_value=18):
            result = fn(order, ci, "gnosis", 1000000000)

        assert result["status"] == "open"
        assert result["progressPct"] >= 0

    def test_non_open_status_time_remaining_zero(self):
        """Line 564: non-open/non-presignaturePending → time_remaining = 0."""
        fn = self._get_fn()
        ci = self._make_chain_interface()

        order = {
            "uid": "0x" + "b" * 60,
            "status": "fulfilled",
            "creationDate": "2023-01-01T00:00:00Z",
            "validTo": 9999999999,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "1000000000000000000",
            "buyAmount": "900000000000000000",
        }

        with patch("iwa.web.routers.swap.get_cached_decimals", return_value=18):
            result = fn(order, ci, "gnosis", 1000000000)

        assert result["status"] == "fulfilled"
        # For non-open status, the function computes timeRemaining as max(0, validTo - current)
        # but progress_pct should be 0 (the else branch at line 564)
        assert result["progressPct"] == 0

    def test_get_cached_decimals_sell_exception(self):
        """Lines 584-585: sell_decimals lookup raises → falls back to 18."""
        fn = self._get_fn()
        ci = self._make_chain_interface()

        order = {
            "uid": "0x" + "c" * 60,
            "status": "fulfilled",
            "creationDate": "2023-06-01T00:00:00Z",
            "validTo": 1700000000,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "1000000000000000000",
            "buyAmount": "900000000000000000",
        }

        def cached_decimals_side_effect(addr, chain):
            if addr == ADDR_SELL:
                raise Exception("sell decimals error")
            return 18

        with patch(
            "iwa.web.routers.swap.get_cached_decimals",
            side_effect=cached_decimals_side_effect,
        ):
            result = fn(order, ci, "gnosis", 1000000000)

        # Even with sell decimals error, it falls back to 18 and succeeds
        assert float(result["sellAmount"]) == 1.0

    def test_get_cached_decimals_buy_exception(self):
        """Lines 589-590: buy_decimals lookup raises → falls back to 18."""
        fn = self._get_fn()
        ci = self._make_chain_interface()

        order = {
            "uid": "0x" + "d" * 60,
            "status": "fulfilled",
            "creationDate": "2023-06-01T00:00:00Z",
            "validTo": 1700000000,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "1000000000000000000",
            "buyAmount": "900000000000000000",
        }

        def cached_decimals_side_effect(addr, chain):
            if addr == ADDR_BUY:
                raise Exception("buy decimals error")
            return 18

        with patch(
            "iwa.web.routers.swap.get_cached_decimals",
            side_effect=cached_decimals_side_effect,
        ):
            result = fn(order, ci, "gnosis", 1000000000)

        assert float(result["buyAmount"]) == 0.9

    def test_amount_conversion_exception(self):
        """Lines 598-601: exception in amount conversion → 0.0."""
        fn = self._get_fn()
        ci = self._make_chain_interface()

        order = {
            "uid": "0x" + "e" * 60,
            "status": "fulfilled",
            "creationDate": "2023-06-01T00:00:00Z",
            "validTo": 1700000000,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "not_a_number",  # Will cause float() to raise
            "buyAmount": "also_not_a_number",
        }

        with patch("iwa.web.routers.swap.get_cached_decimals", return_value=18):
            result = fn(order, ci, "gnosis", 1000000000)

        assert result["sellAmount"] == "0.0000"
        assert result["buyAmount"] == "0.0000"

    def test_token_name_fallback(self):
        """Lines 569-574: token name is None → use truncated address."""
        fn = self._get_fn()
        ci = MagicMock()
        ci.chain.get_token_name.return_value = None  # name not found

        order = {
            "uid": "0x" + "f" * 60,
            "status": "fulfilled",
            "creationDate": "2023-06-01T00:00:00Z",
            "validTo": 1700000000,
            "sellToken": ADDR_SELL,
            "buyToken": ADDR_BUY,
            "sellAmount": "1000000000000000000",
            "buyAmount": "900000000000000000",
        }

        with patch("iwa.web.routers.swap.get_cached_decimals", return_value=18):
            result = fn(order, ci, "gnosis", 1000000000)

        # Should use truncated address format "0xAAAA..." as fallback
        assert "..." in result["sellToken"]
        assert "..." in result["buyToken"]


# ---------------------------------------------------------------------------
# Additional edge cases for remaining uncovered lines
# ---------------------------------------------------------------------------


class TestSwapRequestNegativeAmount:
    """Cover line 89: negative amount_eth in SwapRequest."""

    def test_negative_amount_eth(self):
        """Line 89: amount_eth <= 0."""
        from iwa.web.routers.swap import SwapRequest

        with pytest.raises(ValidationError, match="Amount must be greater than 0"):
            SwapRequest(
                account="master",
                sell_token="WXDAI",
                buy_token="OLAS",
                order_type="sell",
                amount_eth=-5.0,
            )


class TestSwapQuoteNoSigner:
    """Cover line 206: signer is None in get_swap_quote."""

    def test_no_signer(self, client):
        """Line 206: key_storage.get_signer returns None → 400."""
        mock_wallet = MagicMock()
        mock_account = MagicMock()
        mock_account.address = ADDR_ALICE
        mock_wallet.account_service.resolve_account.return_value = mock_account
        mock_wallet.key_storage.get_signer.return_value = None

        mock_chain_obj = MagicMock()
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci = MagicMock()
        mock_ci.return_value.get.return_value = mock_chain_interface

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
        ):
            response = client.get(
                "/api/swap/quote",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount": "1.0",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "signer" in response.json()["detail"].lower()


class TestSwapQuoteNoLiquidity:
    """Cover line 263: NoLiquidity error in get_swap_quote."""

    def test_no_liquidity(self, client):
        """Line 263: NoLiquidity error → specific message."""
        mock_wallet = MagicMock()
        mock_account = MagicMock()
        mock_account.address = ADDR_ALICE
        mock_wallet.account_service.resolve_account.return_value = mock_account
        mock_wallet.key_storage.get_signer.return_value = "fake_signer"

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.return_value = ADDR_SELL
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci = MagicMock()
        mock_ci.return_value.get.return_value = mock_chain_interface

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
            patch("iwa.web.routers.swap.CowSwap") as mock_cow_cls,
        ):
            mock_cow = MagicMock()
            mock_cow.get_max_buy_amount_wei = AsyncMock(
                side_effect=Exception("NoLiquidity for pair")
            )
            mock_cow_cls.return_value = mock_cow

            response = client.get(
                "/api/swap/quote",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "amount": "1.0",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "No liquidity" in response.json()["detail"]


class TestSwapMaxAmountSellMode:
    """Cover lines 294, 299: sell mode and zero balance in get_swap_max_amount."""

    def _build_mocks(self, sell_balance_wei):
        mock_wallet = MagicMock()
        mock_wallet.balance_service.get_erc20_balance_wei.return_value = sell_balance_wei

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.return_value = ADDR_SELL
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci = MagicMock()
        mock_ci.return_value.get.return_value = mock_chain_interface

        return mock_wallet, mock_ci

    def test_zero_balance_returns_zero(self, client):
        """Line 294: balance is 0 → max_amount: 0.0."""
        mock_wallet, mock_ci = self._build_mocks(0)

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
        ):
            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            assert response.json()["max_amount"] == 0.0

    def test_none_balance_returns_zero(self, client):
        """Line 294: balance is None → max_amount: 0.0."""
        mock_wallet, mock_ci = self._build_mocks(None)

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
        ):
            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            assert response.json()["max_amount"] == 0.0

    def test_sell_mode_returns_balance(self, client):
        """Line 299: sell mode with positive balance."""
        mock_wallet, mock_ci = self._build_mocks(5_000_000_000_000_000_000)

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
        ):
            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["max_amount"] == 5.0
            assert data["mode"] == "sell"


class TestSwapMaxAmountNoSigner:
    """Cover line 306: signer is None in get_swap_max_amount buy mode."""

    def test_no_signer(self, client):
        """Line 306: key_storage.get_signer returns None → 400."""
        mock_wallet = MagicMock()
        mock_account = MagicMock()
        mock_account.address = ADDR_ALICE
        mock_wallet.account_service.resolve_account.return_value = mock_account
        mock_wallet.key_storage.get_signer.return_value = None
        mock_wallet.balance_service.get_erc20_balance_wei.return_value = (
            5_000_000_000_000_000_000
        )

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.return_value = ADDR_SELL
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci = MagicMock()
        mock_ci.return_value.get.return_value = mock_chain_interface

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
        ):
            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "buy",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "signer" in response.json()["detail"].lower()


class TestSwapMaxAmountGenericError:
    """Cover line 357: generic (non-NoLiquidity) error in get_swap_max_amount."""

    def test_generic_error(self, client):
        """Line 357: generic exception → 400 with error message."""
        mock_wallet = MagicMock()
        mock_wallet.balance_service.get_erc20_balance_wei.side_effect = Exception(
            "unexpected failure"
        )

        mock_chain_obj = MagicMock()
        mock_chain_obj.get_token_address.return_value = ADDR_SELL
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain = mock_chain_obj

        mock_ci = MagicMock()
        mock_ci.return_value.get.return_value = mock_chain_interface

        with (
            patch("iwa.web.routers.swap.wallet", mock_wallet),
            patch("iwa.web.routers.swap.ChainInterfaces", mock_ci),
            patch("iwa.web.routers.swap.get_cached_decimals", return_value=18),
        ):
            response = client.get(
                "/api/swap/max-amount",
                params={
                    "account": "master",
                    "sell_token": "WXDAI",
                    "buy_token": "OLAS",
                    "mode": "sell",
                    "chain": "gnosis",
                },
            )
            assert response.status_code == 400
            assert "unexpected failure" in response.json()["detail"]
