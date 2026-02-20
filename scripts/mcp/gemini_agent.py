#!/usr/bin/env python3
"""Integrate iwa MCP server with Google Gemini (Google AI Python SDK).

Usage:
    # 1. Start the iwa MCP server:
    #    iwa mcp --transport sse --port 18080

    # 2. Install dependencies and set API key:
    #    pip install google-generativeai
    #    export GOOGLE_API_KEY=AIza...

    # 3. Run:
    #    python scripts/mcp/gemini_agent.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.client import DEFAULT_MCP_BASE, MCPClient

MODEL = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = (
    "You are an autonomous crypto wallet agent powered by iwa.\n"
    "You have access to tools to query balances, manage Olas services, and execute transactions.\n"
    "Always check balances before sending funds. Report results clearly to the user.\n"
    "The 'master' account tag refers to the primary wallet."
)


# ---------------------------------------------------------------------------
# Schema conversion
# ---------------------------------------------------------------------------

# Gemini uses uppercase type names in its schema format
_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _convert_schema(schema: dict) -> dict:
    """Recursively convert a JSON Schema dict to Gemini's schema format."""
    result = dict(schema)
    if "type" in result:
        result["type"] = _TYPE_MAP.get(result["type"], result["type"].upper())
    if "properties" in result:
        result["properties"] = {k: _convert_schema(v) for k, v in result["properties"].items()}
    if "items" in result:
        result["items"] = _convert_schema(result["items"])
    return result


def to_gemini_tool(mcp_tools: list[dict]):
    """Convert MCP tool schemas to a single Gemini Tool object."""
    try:
        import google.generativeai as genai
        from google.generativeai.types import FunctionDeclaration, Tool
    except ImportError:
        raise SystemExit(
            "Install the Google AI SDK: pip install google-generativeai"
        )

    declarations = [
        FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=_convert_schema(
                t.get("inputSchema", {"type": "object", "properties": {}})
            ),
        )
        for t in mcp_tools
    ]
    return Tool(function_declarations=declarations)


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent(mcp: MCPClient, user_message: str) -> None:
    """Run a Gemini agent that calls iwa MCP tools until it has an answer."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise SystemExit("Install the Google AI SDK: pip install google-generativeai")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("Set GOOGLE_API_KEY before running")

    genai.configure(api_key=api_key)

    mcp_raw = mcp.list_tools()
    gemini_tool = to_gemini_tool(mcp_raw)
    print(f"[agent] Loaded {len(mcp_raw)} tools from MCP server")
    print(f"\n[user] {user_message}\n")

    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[gemini_tool],
    )

    chat = model.start_chat()
    response = chat.send_message(user_message)

    while True:
        if response.text:
            print(f"[gemini] {response.text}")

        fn_calls = []
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if part.function_call.name:
                    fn_calls.append(part.function_call)

        if not fn_calls:
            break

        function_responses = []
        for call in fn_calls:
            args = dict(call.args)
            print(f"[tool]   {call.name}({json.dumps(args)})")
            result = mcp.call_tool(call.name, args)
            result_str = json.dumps(result) if not isinstance(result, str) else result
            print(f"[result] {result_str[:200]}{'...' if len(result_str) > 200 else ''}")
            function_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=call.name,
                        response={"result": result_str},
                    )
                )
            )

        response = chat.send_message(function_responses)


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

    print("IWA MCP + Google Gemini Agent")
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
