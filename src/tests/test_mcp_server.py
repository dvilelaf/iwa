"""Tests for the MCP server and tools."""

import asyncio
import datetime
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

# --- Constants ---

ADDR_MASTER = "0x1111111111111111111111111111111111111111"
ADDR_WORKER = "0x2222222222222222222222222222222222222222"
OLAS_TOKEN = "0x3333333333333333333333333333333333333333"
ADDR_SAFE = "0x4444444444444444444444444444444444444444"


# --- Helpers ---


def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract a tool function from the MCP server by name."""
    tool = asyncio.run(mcp.get_tool(name))
    if tool is None:
        raise ValueError(f"Tool '{name}' not found")
    return tool.fn


def _make_mcp(mock_wallet=None, mock_ci=None) -> FastMCP:
    """Create a test MCP server with mocked dependencies."""
    from iwa.mcp.tools import register_tools

    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


def _mock_peewee_field():
    """Create a MagicMock whose comparisons return MagicMock (like peewee Fields)."""
    field = MagicMock()
    for op in ("__ge__", "__gt__", "__le__", "__lt__"):
        setattr(type(field), op, lambda self, other: MagicMock())
    return field


# --- Fixtures ---


@pytest.fixture
def mock_wallet():
    with patch("iwa.core.wallet.Wallet") as mock_cls:
        wallet = MagicMock()
        mock_cls.return_value = wallet
        yield wallet


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.chain.ChainInterfaces") as mock_cls:
        ci = MagicMock()
        mock_cls.return_value = ci
        yield ci


# --- Server creation ---


class TestServerCreation:
    def test_create_server(self, mock_wallet):
        from iwa.mcp.server import create_mcp_server

        server = create_mcp_server()
        assert server is not None
        assert server.name == "iwa"

    def test_server_has_tools(self, mock_wallet):
        from iwa.mcp.server import create_mcp_server

        server = create_mcp_server()
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        assert "list_accounts" in tool_names
        assert "send" in tool_names
        assert "swap" in tool_names
        assert "drain" in tool_names


# --- Read tools ---


class TestListAccounts:
    def test_list_accounts_no_balances(self, mock_wallet):
        mcp = _make_mcp()

        master = MagicMock()
        master.tag = "master"
        master.account_type = "EOA"
        mock_wallet.get_accounts_balances.return_value = (
            {ADDR_MASTER: master},
            None,
        )

        tool_fn = _get_tool_fn(mcp, "list_accounts")
        result = tool_fn(chain="gnosis", token_names="")
        assert ADDR_MASTER in result
        assert result[ADDR_MASTER]["tag"] == "master"
        assert "balances" not in result[ADDR_MASTER]

    def test_list_accounts_with_balances(self, mock_wallet):
        mcp = _make_mcp()

        master = MagicMock()
        master.tag = "master"
        master.account_type = "EOA"
        mock_wallet.get_accounts_balances.return_value = (
            {ADDR_MASTER: master},
            {ADDR_MASTER: {"native": 1.5, "OLAS": 100.0}},
        )

        tool_fn = _get_tool_fn(mcp, "list_accounts")
        result = tool_fn(chain="gnosis", token_names="native,OLAS")

        assert result[ADDR_MASTER]["balances"] == {"native": 1.5, "OLAS": 100.0}
        mock_wallet.get_accounts_balances.assert_called_once_with(
            "gnosis", ["native", "OLAS"]
        )


class TestGetBalance:
    def test_get_balance(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.get_native_balance_eth.return_value = 42.5

        tool_fn = _get_tool_fn(mcp, "get_balance")
        result = tool_fn(account="master", chain="gnosis")

        assert result["balance_eth"] == 42.5
        assert result["account"] == "master"
        mock_wallet.get_native_balance_eth.assert_called_once_with("master", "gnosis")


class TestGetTokenBalance:
    def test_get_token_balance(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.get_erc20_balance_eth.return_value = 500.0

        tool_fn = _get_tool_fn(mcp, "get_token_balance")
        result = tool_fn(account="master", token="OLAS", chain="gnosis")

        assert result["balance_eth"] == 500.0
        assert result["token"] == "OLAS"


class TestGetTokenInfo:
    def test_get_token_info(self, mock_chain_interfaces):
        mcp = _make_mcp()
        ci = mock_chain_interfaces.get.return_value
        ci.get_token_address.return_value = OLAS_TOKEN
        ci.get_token_symbol.return_value = "OLAS"
        ci.get_token_decimals.return_value = 18

        tool_fn = _get_tool_fn(mcp, "get_token_info")
        result = tool_fn(token="OLAS", chain="gnosis")

        assert result["symbol"] == "OLAS"
        assert result["decimals"] == 18
        assert result["address"] == OLAS_TOKEN

    def test_get_token_info_not_found(self, mock_chain_interfaces):
        mcp = _make_mcp()
        ci = mock_chain_interfaces.get.return_value
        ci.get_token_address.return_value = None

        tool_fn = _get_tool_fn(mcp, "get_token_info")
        result = tool_fn(token="FAKE", chain="gnosis")

        assert "error" in result


class TestGetAllowance:
    def test_get_allowance(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.get_erc20_allowance.return_value = 1000.0

        tool_fn = _get_tool_fn(mcp, "get_allowance")
        result = tool_fn(owner="master", spender=ADDR_WORKER, token="OLAS")

        assert result["allowance_eth"] == 1000.0


# --- Write tools ---


class TestSend:
    def test_send_native(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.send.return_value = "0xabcdef"

        tool_fn = _get_tool_fn(mcp, "send")
        result = tool_fn(from_account="master", to_account=ADDR_WORKER, amount="1.5")

        assert result["tx_hash"] == "0xabcdef"
        assert result["status"] == "sent"
        # Verify wei conversion (1.5 ether = 1.5e18 wei)
        call_args = mock_wallet.send.call_args
        assert call_args.kwargs["amount_wei"] == 1_500_000_000_000_000_000

    def test_send_erc20(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.send.return_value = "0x123"

        tool_fn = _get_tool_fn(mcp, "send")
        result = tool_fn(
            from_account="master", to_account=ADDR_WORKER, amount="100", token="OLAS"
        )

        assert result["status"] == "sent"
        assert mock_wallet.send.call_args.kwargs["token_address_or_name"] == "OLAS"

    def test_send_failed(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.send.return_value = None

        tool_fn = _get_tool_fn(mcp, "send")
        result = tool_fn(from_account="master", to_account=ADDR_WORKER, amount="1")

        assert result["status"] == "failed"


class TestApprove:
    def test_approve(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.approve_erc20.return_value = "0xaaa"

        tool_fn = _get_tool_fn(mcp, "approve")
        result = tool_fn(
            owner="master", spender=ADDR_WORKER, token="OLAS", amount="500"
        )

        assert result["status"] == "approved"
        assert result["tx_hash"] == "0xaaa"


class TestSwap:
    def test_swap_success(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.swap = AsyncMock(return_value=True)

        tool_fn = _get_tool_fn(mcp, "swap")
        result = tool_fn(
            account="master", amount="10", sell_token="OLAS", buy_token="WXDAI"
        )

        assert result["status"] == "success"

    def test_swap_failed(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.swap = AsyncMock(return_value=False)

        tool_fn = _get_tool_fn(mcp, "swap")
        result = tool_fn(
            account="master", amount="10", sell_token="OLAS", buy_token="WXDAI"
        )

        assert result["status"] == "failed"


class TestDrain:
    def test_drain(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.drain.return_value = "drained 3 tokens"

        tool_fn = _get_tool_fn(mcp, "drain")
        result = tool_fn(from_account=ADDR_WORKER)

        assert result["status"] == "drained"
        assert result["result"] == "drained 3 tokens"
        mock_wallet.drain.assert_called_once_with(
            from_address_or_tag=ADDR_WORKER,
            to_address_or_tag="master",
            chain_name="gnosis",
        )

    def test_drain_custom_destination(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.drain.return_value = "ok"

        tool_fn = _get_tool_fn(mcp, "drain")
        tool_fn(from_account=ADDR_WORKER, to_account=ADDR_MASTER)

        assert mock_wallet.drain.call_args.kwargs["to_address_or_tag"] == ADDR_MASTER


# --- Account tools ---


class TestCreateAccount:
    def test_create_account(self, mock_wallet):
        mcp = _make_mcp()
        tool_fn = _get_tool_fn(mcp, "create_account")
        result = tool_fn(tag="worker-1")

        assert result["status"] == "success"
        assert result["tag"] == "worker-1"
        mock_wallet.key_storage.generate_new_account.assert_called_once_with("worker-1")


class TestCreateSafe:
    def test_create_safe_with_tags(self, mock_wallet):
        mcp = _make_mcp()
        account_obj = MagicMock()
        account_obj.address = ADDR_MASTER
        mock_wallet.account_service.resolve_account.return_value = account_obj

        tool_fn = _get_tool_fn(mcp, "create_safe")
        result = tool_fn(owners="master", threshold=1, tag="my-safe", chains="gnosis")

        assert result["status"] == "success"
        mock_wallet.safe_service.create_safe.assert_called_once()

    def test_create_safe_with_addresses(self, mock_wallet):
        mcp = _make_mcp()
        tool_fn = _get_tool_fn(mcp, "create_safe")
        result = tool_fn(owners=ADDR_MASTER, threshold=1, tag="safe2")

        assert result["status"] == "success"
        call_args = mock_wallet.safe_service.create_safe.call_args
        assert ADDR_MASTER in call_args[0][1]

    def test_create_safe_owner_not_found(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.account_service.resolve_account.return_value = None

        tool_fn = _get_tool_fn(mcp, "create_safe")
        result = tool_fn(owners="unknown-tag", threshold=1, tag="bad-safe")

        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestTransferFrom:
    def test_transfer_from_success(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.transfer_from_erc20.return_value = "0xabc"

        tool_fn = _get_tool_fn(mcp, "transfer_from")
        result = tool_fn(
            from_account="master",
            sender=ADDR_WORKER,
            recipient=ADDR_MASTER,
            token="OLAS",
            amount="100",
        )

        assert result["status"] == "success"
        mock_wallet.transfer_from_erc20.assert_called_once()

    def test_transfer_from_failed(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.transfer_from_erc20.return_value = None

        tool_fn = _get_tool_fn(mcp, "transfer_from")
        result = tool_fn(
            from_account="master",
            sender=ADDR_WORKER,
            recipient=ADDR_MASTER,
            token="OLAS",
            amount="50",
        )

        assert result["status"] == "failed"


# --- State tools ---


class TestGetAppState:
    def test_get_app_state(self, mock_chain_interfaces):
        mcp = _make_mcp()

        # Setup chain interfaces mock
        mock_interface = MagicMock()
        mock_interface.chain.native_currency = "xDAI"
        mock_interface.tokens = {"OLAS": OLAS_TOKEN, "WXDAI": ADDR_SAFE}
        mock_chain_interfaces.items.return_value = [("gnosis", mock_interface)]

        with patch("iwa.core.models.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core.whitelist = {}
            mock_config_cls.return_value = mock_config

            tool_fn = _get_tool_fn(mcp, "get_app_state")
            result = tool_fn()

        assert "gnosis" in result["chains"]
        assert result["native_currencies"]["gnosis"] == "xDAI"
        assert "OLAS" in result["tokens"]["gnosis"]


class TestGetRpcStatus:
    def test_rpc_online(self, mock_chain_interfaces):
        mcp = _make_mcp()

        mock_interface = MagicMock()
        mock_interface.web3.eth.block_number = 12345
        mock_chain_interfaces.items.return_value = [("gnosis", mock_interface)]

        tool_fn = _get_tool_fn(mcp, "get_rpc_status")
        result = tool_fn()

        assert result["gnosis"]["status"] == "online"
        assert result["gnosis"]["block"] == 12345

    def test_rpc_offline(self, mock_chain_interfaces):
        mcp = _make_mcp()

        mock_interface = MagicMock()
        mock_interface.web3.eth.block_number = property(
            lambda self: (_ for _ in ()).throw(ConnectionError("timeout"))
        )
        type(mock_interface.web3.eth).block_number = property(
            lambda self: (_ for _ in ()).throw(ConnectionError("timeout"))
        )
        mock_chain_interfaces.items.return_value = [("gnosis", mock_interface)]

        tool_fn = _get_tool_fn(mcp, "get_rpc_status")
        result = tool_fn()

        assert result["gnosis"]["status"] == "offline"


# --- Transaction tools ---


class TestGetTransactions:
    @patch("iwa.core.db.SentTransaction")
    def test_get_transactions(self, mock_tx_cls, mock_wallet):
        mcp = _make_mcp()

        # Create mock transaction
        mock_tx = MagicMock()
        mock_tx.amount_wei = 1_000_000_000_000_000_000  # 1 ETH
        mock_tx.timestamp = datetime.datetime(2025, 6, 15, 10, 30)
        mock_tx.chain = "gnosis"
        mock_tx.from_tag = "master"
        mock_tx.from_address = ADDR_MASTER
        mock_tx.to_tag = "worker"
        mock_tx.to_address = ADDR_WORKER
        mock_tx.token = "native"
        mock_tx.value_eur = 1.50
        mock_tx.tx_hash = "0xabc123"
        mock_tx.tags = '["send"]'

        mock_tx_cls.select.return_value.where.return_value.order_by.return_value = [
            mock_tx
        ]
        mock_tx_cls.chain = _mock_peewee_field()
        mock_tx_cls.timestamp = _mock_peewee_field()

        tool_fn = _get_tool_fn(mcp, "get_transactions")
        result = tool_fn(chain="gnosis")

        assert result["chain"] == "gnosis"
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["from"] == "master"
        assert result["transactions"][0]["hash"] == "0xabc123"


# --- Swap query tools ---


class TestSwapQuote:
    def test_swap_quote_sell(self, mock_wallet, mock_chain_interfaces):
        mcp = _make_mcp()

        # Mock chain interface
        mock_ci = mock_chain_interfaces.get.return_value
        mock_chain = MagicMock()
        mock_chain.get_token_address.side_effect = lambda t: (
            OLAS_TOKEN if t == "OLAS" else ADDR_SAFE
        )
        mock_ci.chain = mock_chain

        # Mock wallet account/signer
        account_obj = MagicMock()
        account_obj.address = ADDR_MASTER
        mock_wallet.account_service.resolve_account.return_value = account_obj
        mock_wallet.key_storage.get_signer.return_value = MagicMock()

        # Mock CowSwap
        with patch("iwa.plugins.gnosis.cow.CowSwap") as mock_cow_cls:
            mock_cow = MagicMock()
            mock_cow.get_max_buy_amount_wei = AsyncMock(
                return_value=500_000_000_000_000_000_000
            )
            mock_cow_cls.return_value = mock_cow

            tool_fn = _get_tool_fn(mcp, "swap_quote")
            result = tool_fn(
                account="master",
                sell_token="OLAS",
                buy_token="WXDAI",
                amount="100",
                mode="sell",
            )

        assert result["amount"] == 500.0
        assert result["mode"] == "sell"

    def test_swap_quote_no_signer(self, mock_wallet, mock_chain_interfaces):
        mcp = _make_mcp()
        mock_ci = mock_chain_interfaces.get.return_value
        mock_ci.chain = MagicMock()
        account_obj = MagicMock()
        account_obj.address = ADDR_MASTER
        mock_wallet.account_service.resolve_account.return_value = account_obj
        mock_wallet.key_storage.get_signer.return_value = None

        tool_fn = _get_tool_fn(mcp, "swap_quote")
        result = tool_fn(
            account="master", sell_token="OLAS", buy_token="WXDAI", amount="10"
        )

        assert "error" in result


class TestGetSwapOrders:
    def test_get_orders(self, mock_wallet, mock_chain_interfaces):
        mcp = _make_mcp()

        account_obj = MagicMock()
        account_obj.address = ADDR_MASTER
        mock_wallet.account_service.resolve_account.return_value = account_obj

        mock_ci = mock_chain_interfaces.get.return_value
        mock_ci.chain.chain_id = 100
        mock_ci.chain.get_token_name.side_effect = lambda addr: (
            "OLAS" if addr == OLAS_TOKEN else "WXDAI"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "uid": "0x" + "a" * 40 + "abc",
                "status": "fulfilled",
                "sellToken": OLAS_TOKEN,
                "buyToken": ADDR_SAFE,
                "sellAmount": "1000000000000000000",
                "buyAmount": "2000000000000000000",
            }
        ]

        with patch("requests.get", return_value=mock_response):
            tool_fn = _get_tool_fn(mcp, "get_swap_orders")
            result = tool_fn(account="master", chain="gnosis", limit=5)

        assert len(result["orders"]) == 1
        assert result["orders"][0]["status"] == "fulfilled"

    def test_get_orders_unsupported_chain(self, mock_wallet, mock_chain_interfaces):
        mcp = _make_mcp()
        account_obj = MagicMock()
        account_obj.address = ADDR_MASTER
        mock_wallet.account_service.resolve_account.return_value = account_obj
        mock_ci = mock_chain_interfaces.get.return_value
        mock_ci.chain.chain_id = 999  # Unsupported

        tool_fn = _get_tool_fn(mcp, "get_swap_orders")
        result = tool_fn(account="master")

        assert result["orders"] == []


# --- Wrap tools ---


class TestWrap:
    def test_wrap_success(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.transfer_service.wrap_native.return_value = "0xwrap"

        tool_fn = _get_tool_fn(mcp, "wrap")
        result = tool_fn(account="master", amount="10")

        assert result["status"] == "success"
        assert result["tx_hash"] == "0xwrap"

    def test_wrap_failed(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.transfer_service.wrap_native.return_value = None

        tool_fn = _get_tool_fn(mcp, "wrap")
        result = tool_fn(account="master", amount="10")

        assert result["status"] == "failed"


class TestUnwrap:
    def test_unwrap_success(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.transfer_service.unwrap_native.return_value = "0xunwrap"

        tool_fn = _get_tool_fn(mcp, "unwrap")
        result = tool_fn(account="master", amount="5")

        assert result["status"] == "success"
        assert result["tx_hash"] == "0xunwrap"


class TestGetWrapBalance:
    def test_get_wrap_balance(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.get_native_balance_wei.return_value = 2_000_000_000_000_000_000
        mock_wallet.get_erc20_balance_wei.return_value = 3_000_000_000_000_000_000

        tool_fn = _get_tool_fn(mcp, "get_wrap_balance")
        result = tool_fn(account="master")

        assert result["native"] == 2.0
        assert result["wxdai"] == 3.0

    def test_get_wrap_balance_none(self, mock_wallet):
        mcp = _make_mcp()
        mock_wallet.get_native_balance_wei.return_value = None
        mock_wallet.get_erc20_balance_wei.return_value = None

        tool_fn = _get_tool_fn(mcp, "get_wrap_balance")
        result = tool_fn(account="master")

        assert result["native"] == 0.0
        assert result["wxdai"] == 0.0


# --- Rewards tools ---


def _make_claim_tx(amount_wei, ts, to_tag="trader-1", price_eur=0.50, value_eur=5.0):
    """Helper to create mock claim transaction."""
    tx = MagicMock()
    tx.amount_wei = amount_wei
    tx.timestamp = ts
    tx.to_tag = to_tag
    tx.to_address = ADDR_WORKER
    tx.tx_hash = "0xclaim"
    tx.price_eur = price_eur
    tx.value_eur = value_eur
    tx.chain = "gnosis"
    tx.tags = '["olas_claim_rewards"]'
    return tx


class TestGetRewardClaims:
    @patch("iwa.core.db.SentTransaction")
    def test_get_claims(self, mock_tx_cls, mock_wallet):
        mcp = _make_mcp()

        claim = _make_claim_tx(
            10_000_000_000_000_000_000,
            datetime.datetime(2025, 6, 15, 12, 0),
        )

        mock_tx_cls.tags.contains.return_value = MagicMock()
        mock_tx_cls.timestamp = _mock_peewee_field()
        mock_tx_cls.select.return_value.where.return_value.order_by.return_value = [
            claim
        ]

        tool_fn = _get_tool_fn(mcp, "get_reward_claims")
        result = tool_fn(year=2025)

        assert result["year"] == 2025
        assert len(result["claims"]) == 1
        assert result["claims"][0]["olas_amount"] == 10.0

    @patch("iwa.core.db.SentTransaction")
    def test_get_claims_default_year(self, mock_tx_cls, mock_wallet):
        mcp = _make_mcp()
        mock_tx_cls.tags.contains.return_value = MagicMock()
        mock_tx_cls.timestamp = _mock_peewee_field()
        mock_tx_cls.select.return_value.where.return_value.order_by.return_value = []

        tool_fn = _get_tool_fn(mcp, "get_reward_claims")
        result = tool_fn()

        assert result["year"] == datetime.datetime.now().year


class TestGetRewardsSummary:
    @patch("iwa.core.db.SentTransaction")
    def test_summary(self, mock_tx_cls, mock_wallet):
        mcp = _make_mcp()

        claims = [
            _make_claim_tx(
                5_000_000_000_000_000_000,
                datetime.datetime(2025, 3, 10),
                value_eur=2.50,
            ),
            _make_claim_tx(
                15_000_000_000_000_000_000,
                datetime.datetime(2025, 3, 20),
                value_eur=7.50,
            ),
        ]

        mock_tx_cls.tags.contains.return_value = MagicMock()
        mock_tx_cls.timestamp = _mock_peewee_field()
        mock_tx_cls.select.return_value.where.return_value = claims

        tool_fn = _get_tool_fn(mcp, "get_rewards_summary")
        result = tool_fn(year=2025)

        assert result["year"] == 2025
        assert result["total_olas"] == 20.0
        assert result["total_eur"] == 10.0
        assert result["total_claims"] == 2
        # March (index 2) should have the data
        march = result["months"][2]
        assert march["month"] == 3
        assert march["olas"] == 20.0


class TestGetRewardsByTrader:
    @patch("iwa.core.db.SentTransaction")
    def test_by_trader(self, mock_tx_cls, mock_wallet):
        mcp = _make_mcp()

        claims = [
            _make_claim_tx(
                10_000_000_000_000_000_000,
                datetime.datetime(2025, 1, 15),
                to_tag="trader-A",
                value_eur=5.0,
            ),
            _make_claim_tx(
                20_000_000_000_000_000_000,
                datetime.datetime(2025, 1, 20),
                to_tag="trader-B",
                value_eur=10.0,
            ),
        ]

        mock_tx_cls.tags.contains.return_value = MagicMock()
        mock_tx_cls.timestamp = _mock_peewee_field()
        mock_tx_cls.select.return_value.where.return_value.order_by.return_value = (
            claims
        )

        tool_fn = _get_tool_fn(mcp, "get_rewards_by_trader")
        result = tool_fn(year=2025)

        assert result["year"] == 2025
        assert len(result["traders"]) == 2
        # Sorted by total_eur desc, so trader-B first
        assert result["traders"][0]["name"] == "trader-B"
        assert result["traders"][0]["total_olas"] == 20.0


# --- Tool count integration ---


class TestToolCount:
    def test_all_core_tools_registered(self, mock_wallet):
        mcp = _make_mcp()
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}

        expected = {
            # Original 9
            "list_accounts", "get_balance", "get_token_balance",
            "get_token_info", "get_allowance",
            "send", "approve", "swap", "drain",
            # New 14
            "create_account", "create_safe", "transfer_from",
            "get_app_state", "get_rpc_status", "get_transactions",
            "swap_quote", "get_swap_orders",
            "wrap", "unwrap", "get_wrap_balance",
            "get_reward_claims", "get_rewards_summary", "get_rewards_by_trader",
        }
        assert expected.issubset(tool_names), f"Missing: {expected - tool_names}"
        assert len(tools) >= 23


# --- Server entry points ---


class TestServerEntryPoints:
    @patch("iwa.mcp.server.create_mcp_server")
    def test_run_server(self, mock_create):
        from iwa.mcp.server import run_server

        mock_mcp = MagicMock()
        mock_create.return_value = mock_mcp

        run_server(transport="stdio", host="0.0.0.0", port=9000)

        mock_mcp.run.assert_called_once_with(
            transport="stdio", host="0.0.0.0", port=9000
        )

    @patch("iwa.mcp.server.run_server")
    def test_main_default(self, mock_run):
        from iwa.mcp.server import main

        with patch.object(sys, "argv", ["iwa-mcp"]):
            main()

        mock_run.assert_called_once_with(
            transport="stdio", host="127.0.0.1", port=8000
        )

    @patch("iwa.mcp.server.run_server")
    def test_main_with_args(self, mock_run):
        from iwa.mcp.server import main

        with patch.object(
            sys, "argv", ["iwa-mcp", "-t", "http", "--host", "0.0.0.0", "-p", "9000"]
        ):
            main()

        mock_run.assert_called_once_with(
            transport="http", host="0.0.0.0", port=9000
        )
