"""MCP tool definitions for iwa wallet operations."""

import asyncio

from fastmcp import FastMCP
from web3 import Web3


def register_tools(mcp: FastMCP) -> None:
    """Register all wallet tools on the MCP server."""
    _register_balance_tools(mcp)
    _register_chain_tools(mcp)
    _register_write_tools(mcp)
    _register_account_tools(mcp)
    _register_state_tools(mcp)
    _register_transaction_tools(mcp)
    _register_swap_query_tools(mcp)
    _register_wrap_tools(mcp)
    _register_rewards_query_tools(mcp)
    _register_rewards_detail_tools(mcp)


def _register_balance_tools(mcp: FastMCP) -> None:
    """Register balance and account query tools."""
    from iwa.core.wallet import Wallet

    @mcp.tool
    def list_accounts(
        chain: str = "gnosis",
        token_names: str = "",
    ) -> dict:
        """List all wallet accounts with optional token balances.

        Args:
            chain: Blockchain name (e.g. 'gnosis', 'ethereum', 'base').
            token_names: Comma-separated token names to fetch balances for
                         (e.g. 'native,OLAS'). Leave empty for no balances.

        Returns:
            Dictionary with account addresses, tags, and optional balances.

        """
        wallet = Wallet()
        tokens = [t.strip() for t in token_names.split(",") if t.strip()] or None
        accounts_data, token_balances = wallet.get_accounts_balances(chain, tokens)

        result = {}
        for addr, account in accounts_data.items():
            entry: dict = {"address": str(addr)}
            if hasattr(account, "tag"):
                entry["tag"] = account.tag
            if hasattr(account, "account_type"):
                entry["type"] = str(account.account_type)
            if token_balances and addr in token_balances:
                entry["balances"] = token_balances[addr]
            result[str(addr)] = entry

        return result

    @mcp.tool
    def get_balance(
        account: str,
        chain: str = "gnosis",
    ) -> dict:
        """Get native currency balance of an account.

        Args:
            account: Account address (0x...) or tag (e.g. 'master').
            chain: Blockchain name.

        Returns:
            Balance in ether (human-readable).

        """
        wallet = Wallet()
        balance = wallet.get_native_balance_eth(account, chain)
        return {"account": account, "chain": chain, "balance_eth": balance}

    @mcp.tool
    def get_token_balance(
        account: str,
        token: str,
        chain: str = "gnosis",
    ) -> dict:
        """Get ERC20 token balance of an account.

        Args:
            account: Account address or tag.
            token: Token name (e.g. 'OLAS') or contract address.
            chain: Blockchain name.

        Returns:
            Balance in ether (human-readable).

        """
        wallet = Wallet()
        balance = wallet.get_erc20_balance_eth(account, token, chain)
        return {"account": account, "token": token, "chain": chain, "balance_eth": balance}


def _register_chain_tools(mcp: FastMCP) -> None:
    """Register chain query and allowance tools."""
    from iwa.core.chain import ChainInterfaces
    from iwa.core.wallet import Wallet

    @mcp.tool
    def get_token_info(
        token: str,
        chain: str = "gnosis",
    ) -> dict:
        """Get token information (address, symbol, decimals).

        Args:
            token: Token name (e.g. 'OLAS') or contract address.
            chain: Blockchain name.

        Returns:
            Token address, symbol, and decimals.

        """
        ci = ChainInterfaces().get(chain)
        token_address = ci.get_token_address(token)

        if not token_address:
            return {"error": f"Token '{token}' not found on {chain}"}

        symbol = ci.get_token_symbol(token_address)
        decimals = ci.get_token_decimals(token_address)
        return {
            "address": str(token_address),
            "symbol": symbol,
            "decimals": decimals,
            "chain": chain,
        }

    @mcp.tool
    def get_allowance(
        owner: str,
        spender: str,
        token: str,
        chain: str = "gnosis",
    ) -> dict:
        """Get ERC20 token allowance between two accounts.

        Args:
            owner: Token owner's address or tag.
            spender: Spender's address or tag.
            token: Token name or contract address.
            chain: Blockchain name.

        Returns:
            Allowance amount in ether.

        """
        wallet = Wallet()
        allowance = wallet.get_erc20_allowance(owner, spender, token, chain)
        return {
            "owner": owner,
            "spender": spender,
            "token": token,
            "chain": chain,
            "allowance_eth": allowance,
        }


def _register_write_tools(mcp: FastMCP) -> None:
    """Register write (transaction) tools."""
    from iwa.core.wallet import Wallet

    @mcp.tool
    def send(
        from_account: str,
        to_account: str,
        amount: str,
        token: str = "native",
        chain: str = "gnosis",
    ) -> dict:
        """Send native currency or ERC20 tokens.

        Args:
            from_account: Sender's address or tag (e.g. 'master').
            to_account: Recipient's address or tag.
            amount: Amount to send in ether (human-readable, e.g. '1.5').
            token: Token name or 'native' for native currency.
            chain: Blockchain name.

        Returns:
            Transaction hash if successful.

        """
        wallet = Wallet()
        amount_wei = Web3.to_wei(float(amount), "ether")
        tx_hash = wallet.send(
            from_address_or_tag=from_account,
            to_address_or_tag=to_account,
            amount_wei=amount_wei,
            token_address_or_name=token,
            chain_name=chain,
        )
        return {"tx_hash": tx_hash, "status": "sent" if tx_hash else "failed"}

    @mcp.tool
    def approve(
        owner: str,
        spender: str,
        token: str,
        amount: str,
        chain: str = "gnosis",
    ) -> dict:
        """Approve ERC20 token allowance for a spender.

        Args:
            owner: Token owner's address or tag.
            spender: Spender's address or tag.
            token: Token name or contract address.
            amount: Amount to approve in ether (human-readable).
            chain: Blockchain name.

        Returns:
            Transaction hash if successful.

        """
        wallet = Wallet()
        amount_wei = Web3.to_wei(float(amount), "ether")
        tx_hash = wallet.approve_erc20(
            owner_address_or_tag=owner,
            spender_address_or_tag=spender,
            token_address_or_name=token,
            amount_wei=amount_wei,
            chain_name=chain,
        )
        return {"tx_hash": tx_hash, "status": "approved" if tx_hash else "failed"}

    @mcp.tool
    def swap(
        account: str,
        amount: str,
        sell_token: str,
        buy_token: str,
        chain: str = "gnosis",
    ) -> dict:
        """Swap tokens on CowSwap (decentralized exchange).

        Args:
            account: Account address or tag initiating the swap.
            amount: Amount to sell in ether (human-readable).
            sell_token: Token name to sell (e.g. 'OLAS', 'WXDAI').
            buy_token: Token name to buy.
            chain: Blockchain name (must support CowSwap).

        Returns:
            Whether the swap was successful.

        """
        wallet = Wallet()
        success = asyncio.run(
            wallet.swap(
                account_address_or_tag=account,
                amount_eth=float(amount),
                sell_token_name=sell_token,
                buy_token_name=buy_token,
                chain_name=chain,
            )
        )
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def drain(
        from_account: str,
        to_account: str = "master",
        chain: str = "gnosis",
    ) -> dict:
        """Drain all tokens and native currency from one account to another.

        Transfers all known ERC20 tokens and remaining native currency.

        Args:
            from_account: Source account address or tag.
            to_account: Destination account address or tag (default: 'master').
            chain: Blockchain name.

        Returns:
            Operation summary.

        """
        wallet = Wallet()
        result = wallet.drain(
            from_address_or_tag=from_account,
            to_address_or_tag=to_account,
            chain_name=chain,
        )
        return {"result": result, "status": "drained" if result else "failed"}


def _register_account_tools(mcp: FastMCP) -> None:
    """Register account creation tools."""

    @mcp.tool
    def create_account(tag: str) -> dict:
        """Create a new EOA (Externally Owned Account) with a unique tag.

        Args:
            tag: Unique tag/name for the new account (e.g. 'worker-1').

        Returns:
            Status of the operation.

        """
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        wallet.key_storage.generate_new_account(tag)
        return {"status": "success", "tag": tag}

    @mcp.tool
    def create_safe(
        owners: str,
        threshold: int = 1,
        tag: str = "",
        chains: str = "gnosis",
    ) -> dict:
        """Deploy a new Gnosis Safe multisig wallet.

        Args:
            owners: Comma-separated owner addresses or tags (e.g. 'master,worker-1').
            threshold: Number of required signatures (default: 1).
            tag: Tag/name for the Safe (e.g. 'team-safe').
            chains: Comma-separated chain names to deploy on (default: 'gnosis').

        Returns:
            Status of the operation.

        """
        import time

        from iwa.core.wallet import Wallet

        wallet = Wallet()
        salt_nonce = int(time.time() * 1000)
        owner_list = [o.strip() for o in owners.split(",") if o.strip()]
        chain_list = [c.strip() for c in chains.split(",") if c.strip()]

        resolved_owners = []
        for owner in owner_list:
            if owner.startswith("0x"):
                resolved_owners.append(owner)
            else:
                account = wallet.account_service.resolve_account(owner)
                if not account:
                    return {"status": "error", "error": f"Owner not found: {owner}"}
                resolved_owners.append(account.address)

        for chain_name in chain_list:
            wallet.safe_service.create_safe(
                "master",
                resolved_owners,
                threshold,
                chain_name,
                tag or None,
                salt_nonce,
            )
        return {"status": "success", "tag": tag, "chains": chain_list}

    @mcp.tool
    def transfer_from(
        from_account: str,
        sender: str,
        recipient: str,
        token: str,
        amount: str,
        chain: str = "gnosis",
    ) -> dict:
        """Transfer ERC20 tokens from a sender to a recipient using allowance.

        The from_account signs the transaction, transferring tokens from sender
        to recipient using a previously approved allowance.

        Args:
            from_account: Account signing the transaction (address or tag).
            sender: Token sender's address or tag (must have approved allowance).
            recipient: Recipient's address or tag.
            token: Token name or contract address.
            amount: Amount in ether (human-readable).
            chain: Blockchain name.

        Returns:
            Status of the operation.

        """
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        amount_wei = Web3.to_wei(float(amount), "ether")
        result = wallet.transfer_from_erc20(
            from_address_or_tag=from_account,
            sender_address_or_tag=sender,
            recipient_address_or_tag=recipient,
            token_address_or_name=token,
            amount_wei=amount_wei,
            chain_name=chain,
        )
        return {"status": "success" if result else "failed"}


def _register_state_tools(mcp: FastMCP) -> None:
    """Register app state and RPC status tools."""

    @mcp.tool
    def get_app_state() -> dict:
        """Get current application state: configured chains, tokens, and whitelist.

        Returns:
            Dictionary with chains, tokens per chain, native currencies, and whitelist.

        """
        from iwa.core.chain import ChainInterfaces
        from iwa.core.models import Config

        chain_names = []
        native_currencies = {}
        tokens = {}
        for name, interface in ChainInterfaces().items():
            chain_names.append(name)
            native_currencies[name] = interface.chain.native_currency
            tokens[name] = list(interface.tokens.keys())

        config = Config()
        whitelist = {}
        if config.core and config.core.whitelist:
            whitelist = {tag: str(addr) for tag, addr in config.core.whitelist.items()}

        return {
            "chains": chain_names,
            "tokens": tokens,
            "native_currencies": native_currencies,
            "default_chain": "gnosis",
            "whitelist": whitelist,
        }

    @mcp.tool
    def get_rpc_status() -> dict:
        """Check connectivity and sync status of RPC endpoints for all chains.

        Returns:
            Per-chain status (online/offline), current block number, and RPC URLs.

        """
        from iwa.core.chain import ChainInterfaces

        status = {}
        for name, interface in ChainInterfaces().items():
            try:
                block = interface.web3.eth.block_number
                status[name] = {"status": "online", "block": block}
            except Exception as e:
                status[name] = {"status": "offline", "error": str(e)}
        return status


def _register_transaction_tools(mcp: FastMCP) -> None:
    """Register transaction history tools."""

    @mcp.tool
    def get_transactions(chain: str = "gnosis") -> dict:
        """Get recent sent transactions (last 24 hours).

        Args:
            chain: Blockchain name to query.

        Returns:
            List of recent transactions with amounts, tokens, and status.

        """
        import datetime
        import json

        from iwa.core.db import SentTransaction

        chain = chain.lower()
        recent = (
            SentTransaction.select()
            .where(
                (SentTransaction.chain == chain)
                & (
                    SentTransaction.timestamp
                    > (datetime.datetime.now() - datetime.timedelta(hours=24))
                )
            )
            .order_by(SentTransaction.timestamp.desc())
        )

        result = []
        for tx in recent:
            amount_display = float(tx.amount_wei or 0) / 1e18
            result.append(
                {
                    "timestamp": tx.timestamp.isoformat(),
                    "chain": tx.chain,
                    "from": tx.from_tag or tx.from_address,
                    "to": tx.to_tag or tx.to_address,
                    "token": tx.token,
                    "amount": f"{amount_display:.4f}",
                    "value_eur": f"{(tx.value_eur or 0.0):.2f}",
                    "hash": tx.tx_hash,
                    "tags": json.loads(tx.tags) if tx.tags else [],
                }
            )
        return {"transactions": result, "chain": chain}


def _register_swap_query_tools(mcp: FastMCP) -> None:
    """Register swap query tools (quote, max-amount, orders)."""

    @mcp.tool
    def swap_quote(
        account: str,
        sell_token: str,
        buy_token: str,
        amount: str,
        mode: str = "sell",
        chain: str = "gnosis",
    ) -> dict:
        """Get a price quote for a potential token swap from CowSwap.

        Args:
            account: Account address or tag.
            sell_token: Token symbol to sell (e.g. 'WXDAI').
            buy_token: Token symbol to buy (e.g. 'OLAS').
            amount: Amount in human-readable units.
            mode: 'sell' (get buy amount) or 'buy' (get sell amount).
            chain: Blockchain name.

        Returns:
            Quoted amount and mode.

        """
        from concurrent.futures import ThreadPoolExecutor

        from iwa.core.chain import ChainInterfaces
        from iwa.core.wallet import Wallet
        from iwa.plugins.gnosis.cow import CowSwap

        wallet = Wallet()
        chain_interface = ChainInterfaces().get(chain)
        chain_obj = chain_interface.chain
        account_obj = wallet.account_service.resolve_account(account)
        signer = wallet.key_storage.get_signer(account_obj.address)

        if not signer:
            return {"error": "Could not get signer for account"}

        sell_token_addr = chain_obj.get_token_address(sell_token)
        buy_token_addr = chain_obj.get_token_address(buy_token)

        # Use 18 decimals as default
        amount_wei = int(float(amount) * 1e18)

        def run_quote():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                cow = CowSwap(private_key_or_signer=signer, chain=chain_obj)
                if mode == "sell":
                    return loop.run_until_complete(
                        cow.get_max_buy_amount_wei(
                            amount_wei, sell_token_addr, buy_token_addr
                        )
                    )
                else:
                    return loop.run_until_complete(
                        cow.get_max_sell_amount_wei(
                            amount_wei, sell_token_addr, buy_token_addr
                        )
                    )
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_quote)
            result_wei = future.result(timeout=30)

        result_eth = result_wei / 1e18
        return {"amount": result_eth, "mode": mode}

    @mcp.tool
    def get_swap_orders(
        account: str = "master",
        chain: str = "gnosis",
        limit: int = 5,
    ) -> dict:
        """Get recent swap orders for an account from CowSwap API.

        Args:
            account: Account address or tag.
            chain: Blockchain name.
            limit: Maximum number of orders to return.

        Returns:
            List of recent orders with status and amounts.

        """
        import requests

        from iwa.core.chain import ChainInterfaces
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        account_obj = wallet.account_service.resolve_account(account)
        address = account_obj.address

        chain_interface = ChainInterfaces().get(chain)
        chain_id = chain_interface.chain.chain_id

        api_urls = {
            100: "https://api.cow.fi/xdai",
            1: "https://api.cow.fi/mainnet",
            11155111: "https://api.cow.fi/sepolia",
        }
        api_url = api_urls.get(chain_id)
        if not api_url:
            return {"orders": []}

        url = f"{api_url}/api/v1/account/{address}/orders?limit={limit}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return {"orders": []}

        orders = response.json()
        result = []
        for order in orders[:limit]:
            sell_token_addr = order.get("sellToken", "")
            buy_token_addr = order.get("buyToken", "")
            sell_name = (
                chain_interface.chain.get_token_name(sell_token_addr)
                or sell_token_addr[:10]
            )
            buy_name = (
                chain_interface.chain.get_token_name(buy_token_addr)
                or buy_token_addr[:10]
            )
            sell_amount = float(order.get("sellAmount", "0")) / 1e18
            buy_amount = float(order.get("buyAmount", "0")) / 1e18
            result.append(
                {
                    "uid": order.get("uid", "")[:12] + "...",
                    "status": order.get("status", "unknown"),
                    "sell_token": sell_name,
                    "buy_token": buy_name,
                    "sell_amount": f"{sell_amount:.4f}",
                    "buy_amount": f"{buy_amount:.4f}",
                }
            )
        return {"orders": result}


def _register_wrap_tools(mcp: FastMCP) -> None:
    """Register wrap/unwrap tools."""

    @mcp.tool
    def wrap(
        account: str,
        amount: str,
        chain: str = "gnosis",
    ) -> dict:
        """Wrap native currency to wrapped token (e.g. xDAI to WXDAI).

        Args:
            account: Account address or tag.
            amount: Amount in ether (human-readable).
            chain: Blockchain name.

        Returns:
            Transaction hash if successful.

        """
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        amount_wei = Web3.to_wei(float(amount), "ether")
        tx_hash = wallet.transfer_service.wrap_native(
            account_address_or_tag=account,
            amount_wei=amount_wei,
            chain_name=chain,
        )
        return {
            "status": "success" if tx_hash else "failed",
            "tx_hash": tx_hash,
        }

    @mcp.tool
    def unwrap(
        account: str,
        amount: str,
        chain: str = "gnosis",
    ) -> dict:
        """Unwrap wrapped token to native currency (e.g. WXDAI to xDAI).

        Args:
            account: Account address or tag.
            amount: Amount in ether (human-readable).
            chain: Blockchain name.

        Returns:
            Transaction hash if successful.

        """
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        amount_wei = Web3.to_wei(float(amount), "ether")
        tx_hash = wallet.transfer_service.unwrap_native(
            account_address_or_tag=account,
            amount_wei=amount_wei,
            chain_name=chain,
        )
        return {
            "status": "success" if tx_hash else "failed",
            "tx_hash": tx_hash,
        }

    @mcp.tool
    def get_wrap_balance(
        account: str,
        chain: str = "gnosis",
    ) -> dict:
        """Get native and wrapped token balances for wrap/unwrap operations.

        Args:
            account: Account address or tag.
            chain: Blockchain name.

        Returns:
            Native and WXDAI balances in ether.

        """
        from iwa.core.wallet import Wallet

        wallet = Wallet()
        native_wei = wallet.get_native_balance_wei(account, chain) or 0
        wxdai_wei = wallet.get_erc20_balance_wei(account, "WXDAI", chain) or 0

        native_eth = float(Web3.from_wei(native_wei, "ether"))
        wxdai_eth = float(Web3.from_wei(wxdai_wei, "ether"))
        return {"native": native_eth, "wxdai": wxdai_eth}


def _register_rewards_query_tools(mcp: FastMCP) -> None:
    """Register rewards query tools (claims, summary)."""

    @mcp.tool
    def get_reward_claims(
        year: int = 0,
        month: int = 0,
    ) -> dict:
        """Get staking reward claim transactions for a given year and optional month.

        Args:
            year: Year to query (0 = current year).
            month: Month to filter (0 = all months, 1-12 for specific month).

        Returns:
            List of claim transactions with OLAS amounts and EUR values.

        """
        import datetime

        from iwa.core.db import SentTransaction

        if year == 0:
            year = datetime.datetime.now().year

        year_start = datetime.datetime(year, 1, 1)
        year_end = datetime.datetime(year + 1, 1, 1)

        query = SentTransaction.tags.contains("olas_claim_rewards") & (
            SentTransaction.timestamp >= year_start
        ) & (SentTransaction.timestamp < year_end)

        if month and 1 <= month <= 12:
            month_start = datetime.datetime(year, month, 1)
            month_end = (
                datetime.datetime(year + 1, 1, 1)
                if month == 12
                else datetime.datetime(year, month + 1, 1)
            )
            query = query & (SentTransaction.timestamp >= month_start) & (
                SentTransaction.timestamp < month_end
            )

        claims = SentTransaction.select().where(query).order_by(
            SentTransaction.timestamp.asc()
        )

        result = []
        for tx in claims:
            olas_amount = float(tx.amount_wei or 0) / 1e18
            result.append(
                {
                    "date": tx.timestamp.isoformat(),
                    "tx_hash": tx.tx_hash,
                    "olas_amount": round(olas_amount, 6),
                    "price_eur": round(tx.price_eur, 4) if tx.price_eur else None,
                    "value_eur": round(tx.value_eur, 2) if tx.value_eur else None,
                    "service_name": tx.to_tag or tx.to_address,
                    "chain": tx.chain,
                }
            )
        return {"claims": result, "year": year, "month": month or "all"}

    @mcp.tool
    def get_rewards_summary(year: int = 0) -> dict:
        """Get aggregated staking rewards summary by month for a given year.

        Args:
            year: Year to query (0 = current year).

        Returns:
            Monthly breakdown and yearly totals of OLAS rewards and EUR values.

        """
        import datetime
        from collections import defaultdict

        from iwa.core.db import SentTransaction

        if year == 0:
            year = datetime.datetime.now().year

        year_start = datetime.datetime(year, 1, 1)
        year_end = datetime.datetime(year + 1, 1, 1)

        claims = SentTransaction.select().where(
            SentTransaction.tags.contains("olas_claim_rewards")
            & (SentTransaction.timestamp >= year_start)
            & (SentTransaction.timestamp < year_end)
        )

        total_olas = 0.0
        total_eur = 0.0
        total_claims = 0
        monthly = defaultdict(lambda: {"olas": 0.0, "eur": 0.0, "claims": 0})

        for tx in claims:
            olas_amount = float(tx.amount_wei or 0) / 1e18
            eur_value = tx.value_eur or 0.0
            total_olas += olas_amount
            total_eur += eur_value
            total_claims += 1
            m = tx.timestamp.month
            monthly[m]["olas"] += olas_amount
            monthly[m]["eur"] += eur_value
            monthly[m]["claims"] += 1

        months = []
        for m in range(1, 13):
            data = monthly.get(m, {"olas": 0.0, "eur": 0.0, "claims": 0})
            months.append(
                {
                    "month": m,
                    "olas": round(data["olas"], 6),
                    "eur": round(data["eur"], 2),
                    "claims": data["claims"],
                }
            )

        return {
            "year": year,
            "total_olas": round(total_olas, 6),
            "total_eur": round(total_eur, 2),
            "total_claims": total_claims,
            "months": months,
        }


def _register_rewards_detail_tools(mcp: FastMCP) -> None:
    """Register rewards detail tools (by-trader breakdown)."""

    @mcp.tool
    def get_rewards_by_trader(year: int = 0) -> dict:
        """Get per-trader staking rewards breakdown with monthly detail.

        Args:
            year: Year to query (0 = current year).

        Returns:
            Per-trader breakdown with monthly OLAS/EUR totals and cumulative series.

        """
        import datetime
        from collections import defaultdict

        from iwa.core.db import SentTransaction

        if year == 0:
            year = datetime.datetime.now().year

        year_start = datetime.datetime(year, 1, 1)
        year_end = datetime.datetime(year + 1, 1, 1)

        claims = list(
            SentTransaction.select()
            .where(
                SentTransaction.tags.contains("olas_claim_rewards")
                & (SentTransaction.timestamp >= year_start)
                & (SentTransaction.timestamp < year_end)
            )
            .order_by(SentTransaction.timestamp.asc())
        )

        trader_data = defaultdict(
            lambda: {
                "total_olas": 0.0,
                "total_eur": 0.0,
                "total_claims": 0,
                "months": defaultdict(
                    lambda: {"olas": 0.0, "eur": 0.0, "claims": 0}
                ),
            }
        )

        for tx in claims:
            olas_amount = float(tx.amount_wei or 0) / 1e18
            eur_value = tx.value_eur or 0.0
            trader = tx.to_tag or tx.to_address or "unknown"
            m = tx.timestamp.month
            td = trader_data[trader]
            td["total_olas"] += olas_amount
            td["total_eur"] += eur_value
            td["total_claims"] += 1
            td["months"][m]["olas"] += olas_amount
            td["months"][m]["eur"] += eur_value
            td["months"][m]["claims"] += 1

        traders = []
        for name, td in sorted(
            trader_data.items(), key=lambda x: -x[1]["total_eur"]
        ):
            months = []
            for m in range(1, 13):
                md = td["months"].get(
                    m, {"olas": 0.0, "eur": 0.0, "claims": 0}
                )
                months.append(
                    {
                        "month": m,
                        "olas": round(md["olas"], 6),
                        "eur": round(md["eur"], 2),
                        "claims": md["claims"],
                    }
                )
            traders.append(
                {
                    "name": name,
                    "total_olas": round(td["total_olas"], 6),
                    "total_eur": round(td["total_eur"], 2),
                    "total_claims": td["total_claims"],
                    "months": months,
                }
            )

        return {"year": year, "traders": traders}
