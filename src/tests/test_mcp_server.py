"""Tests for the MCP server and tools."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

# --- Constants ---

ADDR_MASTER = "0x1111111111111111111111111111111111111111"
ADDR_WORKER = "0x2222222222222222222222222222222222222222"
OLAS_TOKEN = "0x3333333333333333333333333333333333333333"


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
