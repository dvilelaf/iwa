# MCP Server

The iwa MCP server exposes all wallet and Olas operations as [Model Context Protocol](https://modelcontextprotocol.io) (MCP) tools, allowing AI agents to interact with the blockchain directly.

## Starting the Server

```bash
# SSE transport (recommended for local AI agent development)
iwa mcp --transport sse --port 18080

# stdio transport (for MCP Desktop clients like Claude Desktop)
iwa mcp --transport stdio
```

## Connecting from AI Clients

### Claude Desktop

Add this to your Claude Desktop configuration (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "iwa": {
      "command": "iwa",
      "args": ["mcp", "--transport", "stdio"],
      "env": {
        "IWA_CONFIG": "/path/to/your/data/config.yaml",
        "IWA_SECRETS": "/path/to/your/secrets.env"
      }
    }
  }
}
```

### Python Agent Examples

Ready-to-run example scripts are in `scripts/mcp/`. They all share a common MCP client (`scripts/mcp/client.py`) and use an agentic loop to handle tool calls automatically.

**Claude (Anthropic SDK)**

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/mcp/claude_agent.py
```

**OpenAI GPT**

```bash
pip install openai
export OPENAI_API_KEY=sk-...
python scripts/mcp/openai_agent.py
```

**Google Gemini**

```bash
pip install google-generativeai
export GOOGLE_API_KEY=AIza...
python scripts/mcp/gemini_agent.py
```

All three scripts follow the same pattern using the shared `MCPClient`:

1. Connect to the MCP server via SSE (`client.py`)
2. Fetch the tool list (40 tools)
3. Convert schemas to the provider's format
4. Run an agentic loop where the model calls tools and receives results

You can also pass a custom prompt as a command-line argument:

```bash
python scripts/mcp/claude_agent.py "What is the balance of my master account?"
```

### Any MCP-compatible Client (SSE)

Connect to `http://localhost:18080/sse` for the SSE event stream, then POST requests to `/messages/?session_id=<id>`.

## Tool Reference

### Wallet Tools (23)

#### Balance & Query

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_accounts` | List all wallet accounts with optional token balances | `chain`, `token_names` |
| `get_balance` | Get native currency balance for an account | `account`, `chain` |
| `get_token_balance` | Get ERC20 token balance | `account`, `token`, `chain` |
| `get_token_info` | Get token contract metadata | `token`, `chain` |
| `get_allowance` | Get ERC20 allowance between two accounts | `owner`, `spender`, `token`, `chain` |
| `get_app_state` | Get configured chains, tokens, and accounts | — |
| `get_rpc_status` | Check RPC connectivity and current block for each chain | — |
| `get_transactions` | Get recent transaction history | `chain` |

#### Write Operations

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `send` | Send native or ERC20 tokens | `from_account`, `to_account`, `amount`, `token`, `chain` |
| `approve` | Approve ERC20 allowance for a spender | `owner`, `spender`, `token`, `amount`, `chain` |
| `swap` | Execute a token swap via CowSwap | `account`, `sell_token`, `buy_token`, `amount`, `chain` |
| `drain` | Drain all tokens and native currency from one account to another | `from_account`, `to_account`, `chain` |
| `wrap` | Wrap native currency to its wrapped ERC20 form | `account`, `amount`, `chain` |
| `unwrap` | Unwrap ERC20 back to native currency | `account`, `amount`, `chain` |

#### Account Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_account` | Create a new EOA with a unique tag | `tag` |
| `create_safe` | Create a Safe multisig wallet | `tag`, `owners`, `threshold`, `chain` |
| `transfer_from` | Execute a Safe transaction to transfer tokens | `safe_tag`, `to`, `amount`, `token`, `chain` |

#### Swap & Rewards Query

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `swap_quote` | Get a quote for a token swap | `account`, `sell_token`, `buy_token`, `amount`, `chain` |
| `get_swap_orders` | Get recent CowSwap orders | `account`, `chain` |
| `get_wrap_balance` | Get wrapped token balance | `account`, `chain` |
| `get_reward_claims` | Get OLAS staking reward claim history | `year`, `month` |
| `get_rewards_summary` | Get aggregated reward statistics | `year` |
| `get_rewards_by_trader` | Get rewards grouped by trader | `year` |

---

### Olas Plugin Tools (17)

#### Service Management

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `olas_list_services` | List all configured Olas services | `chain` |
| `olas_service_details` | Get service state, staking info, and balances | `service_key` |
| `olas_create_service` | Create and deploy a new Olas service | `service_name`, `chain`, `staking_contract`, `stake_on_create` |
| `olas_deploy_service` | Deploy an existing PRE_REGISTRATION service | `service_key`, `staking_contract` |

#### Service Lifecycle (step by step)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `olas_activate_service` | Activate registration (step 1) | `service_key` |
| `olas_register_agent` | Register agent (step 2) | `service_key` |
| `olas_deploy_step` | Deploy Safe multisig (step 3) | `service_key` |
| `olas_terminate_service` | Wind down: unstake → terminate → unbond | `service_key` |

#### Staking

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `olas_list_staking_contracts` | List available staking contracts | `chain` |
| `olas_stake_service` | Stake a service into a staking contract | `service_key`, `staking_contract` |
| `olas_unstake_service` | Unstake a service (checks epoch lock) | `service_key` |
| `olas_restake_service` | Restake an evicted service | `service_key` |
| `olas_checkpoint` | Trigger a checkpoint to update liveness | `service_key` |
| `olas_claim_rewards` | Claim accrued staking rewards | `service_key` |

#### Funding & Info

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `olas_fund_service` | Fund service agent and/or safe accounts | `service_key`, `agent_amount_eth`, `safe_amount_eth` |
| `olas_drain_service` | Drain all service funds to master account | `service_key` |
| `olas_get_price` | Get OLAS/EUR price from CoinGecko | — |

## Account Tags

All tools that accept account addresses also accept **tags** — human-readable aliases defined in your key storage. The reserved tag `master` always refers to the primary wallet account.

```python
# These are equivalent:
send(from_account="master", to_account="0xABCD...")
send(from_account="master", to_account="trader_alpha_agent")
```

## Service Keys

Olas services are identified by `chain:service_id` keys:

```
gnosis:2679    # Service ID 2679 on Gnosis Chain
ethereum:42    # Service ID 42 on Ethereum
```

## Common Workflows

### Create and stake a new Olas service

```python
# 1. List available staking contracts to pick one
contracts = olas_list_staking_contracts(chain="gnosis")

# 2. Create service with correct bond amount and stake immediately
result = olas_create_service(
    service_name="my_agent",
    chain="gnosis",
    staking_contract="0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C",
    stake_on_create=True,
)
# result: {"status": "success", "service_key": "gnosis:2679", "staked": true}
```

### Check status and collect rewards

```python
details = olas_service_details(service_key="gnosis:2679")
# details.staking.accrued_reward_olas shows pending rewards

rewards = olas_claim_rewards(service_key="gnosis:2679")
# rewards: {"status": "claimed", "amount_olas": 12.5}
# or:      {"status": "nothing_to_claim", "amount_olas": 0}
```

### Full wind-down

```python
# Unstake (respects epoch lock — returns error with unlock time if too early)
unstake = olas_unstake_service(service_key="gnosis:2679")

# Terminate and unbond
terminate = olas_terminate_service(service_key="gnosis:2679")

# Drain remaining funds back to master
drain = olas_drain_service(service_key="gnosis:2679")
```
