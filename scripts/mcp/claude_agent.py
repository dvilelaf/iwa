#!/usr/bin/env python3
"""Integrate iwa MCP server with Claude (Anthropic SDK).

Usage:
    # 1. Start the iwa MCP server:
    #    iwa mcp --transport sse --port 18080

    # 2. Install dependencies and set API key:
    #    pip install anthropic
    #    export ANTHROPIC_API_KEY=sk-ant-...

    # 3. Run:
    #    python scripts/mcp/claude_agent.py
"""

import json
import os
import sys
from pathlib import Path

# Allow running from the repo root: python scripts/mcp/claude_agent.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.client import DEFAULT_MCP_BASE, MCPClient

MODEL = "claude-opus-4-5"

SYSTEM_PROMPT = (
    "You are an autonomous crypto wallet agent powered by iwa.\n"
    "You have access to tools to query balances, manage Olas services, and execute transactions.\n"
    "Always check balances before sending funds. Report results clearly to the user.\n"
    "The 'master' account tag refers to the primary wallet."
)


# ---------------------------------------------------------------------------
# Schema conversion
# ---------------------------------------------------------------------------


def to_anthropic_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP tool schemas to Anthropic tool_use format."""
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
        }
        for t in mcp_tools
    ]


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent(mcp: MCPClient, user_message: str) -> None:
    """Run a Claude agent that calls iwa MCP tools until it has an answer."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit("Install the Anthropic SDK: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running")

    client = anthropic.Anthropic(api_key=api_key)

    mcp_tools = mcp.list_tools()
    tools = to_anthropic_tools(mcp_tools)
    print(f"[agent] Loaded {len(tools)} tools from MCP server")
    print(f"\n[user] {user_message}\n")

    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        assistant_content = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                print(f"[claude] {block.text}")
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                print(f"[tool]   {block.name}({json.dumps(block.input)})")
                assistant_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
                tool_calls.append(block)

        messages.append({"role": "assistant", "content": assistant_content})

        if not tool_calls or response.stop_reason == "end_turn":
            break

        tool_results = []
        for call in tool_calls:
            result = mcp.call_tool(call.name, call.input)
            result_str = json.dumps(result) if not isinstance(result, str) else result
            print(f"[result] {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
            tool_results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": result_str}
            )

        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

EXAMPLE_PROMPTS = [
    "What are my current wallet balances on Gnosis Chain? Show native xDAI and OLAS.",
    "List all my Olas services and their staking status.",
    "What is the current price of OLAS in EUR?",
    "List available staking contracts on Gnosis Chain with their names and addresses.",
]

if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else EXAMPLE_PROMPTS[0]

    print("IWA MCP + Claude Agent")
    print("=" * 50)

    mcp = MCPClient(DEFAULT_MCP_BASE)
    print(f"Connecting to {DEFAULT_MCP_BASE}...")
    if not mcp.connect():
        raise SystemExit(
            "Could not connect. Start the server with: iwa mcp --transport sse --port 18080"
        )

    print("Connected.\n")
    run_agent(mcp, prompt)
    mcp.close()
