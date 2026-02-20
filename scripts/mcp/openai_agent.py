#!/usr/bin/env python3
"""Integrate iwa MCP server with OpenAI GPT (OpenAI Python SDK).

Usage:
    # 1. Start the iwa MCP server:
    #    iwa mcp --transport sse --port 18080

    # 2. Install dependencies and set API key:
    #    pip install openai
    #    export OPENAI_API_KEY=sk-...

    # 3. Run:
    #    python scripts/mcp/openai_agent.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.client import DEFAULT_MCP_BASE, MCPClient

MODEL = "gpt-4o"

SYSTEM_PROMPT = (
    "You are an autonomous crypto wallet agent powered by iwa.\n"
    "You have access to tools to query balances, manage Olas services, and execute transactions.\n"
    "Always check balances before sending funds. Report results clearly to the user.\n"
    "The 'master' account tag refers to the primary wallet."
)


# ---------------------------------------------------------------------------
# Schema conversion
# ---------------------------------------------------------------------------


def to_openai_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP tool schemas to OpenAI function_call format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for t in mcp_tools
    ]


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent(mcp: MCPClient, user_message: str) -> None:
    """Run an OpenAI GPT agent that calls iwa MCP tools until it has an answer."""
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("Install the OpenAI SDK: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY before running")

    client = OpenAI(api_key=api_key)

    mcp_tools = mcp.list_tools()
    tools = to_openai_tools(mcp_tools)
    print(f"[agent] Loaded {len(tools)} tools from MCP server")
    print(f"\n[user] {user_message}\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        msg = choice.message

        if msg.content:
            print(f"[gpt]  {msg.content}")

        messages.append(msg)

        if not msg.tool_calls or choice.finish_reason == "stop":
            break

        tool_results = []
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            print(f"[tool]   {call.function.name}({json.dumps(args)})")
            result = mcp.call_tool(call.function.name, args)
            result_str = json.dumps(result) if not isinstance(result, str) else result
            print(f"[result] {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
            tool_results.append(
                {"role": "tool", "tool_call_id": call.id, "content": result_str}
            )

        messages.extend(tool_results)


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

    print("IWA MCP + OpenAI GPT Agent")
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
