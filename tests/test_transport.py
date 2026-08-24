"""End-to-end smoke test for the real MCP stdio transport."""

import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


async def test_stdio_server_lists_and_calls_tools() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "psych_coherence_mcp"],
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert len(names) == 18
        assert {
            "psy_list_personas",
            "psy_generate_response",
            "psy_import_session",
        } <= names

        result = await session.call_tool("psy_list_personas", arguments={})
        assert result.isError is False
        assert result.content

        created = await session.call_tool(
            "psy_create_session",
            arguments={
                "params": {
                    "persona_id": "engineer_kai",
                    "session_id": "transport-test",
                }
            },
        )
        assert created.isError is False
        assert isinstance(created.content[0], TextContent)
        created_payload = json.loads(created.content[0].text)
        assert created_payload["status"] == "active"

        generated = await session.call_tool(
            "psy_generate_response",
            arguments={
                "params": {
                    "session_id": "transport-test",
                    "user_text": "How should I test this release?",
                }
            },
        )
        assert generated.isError is False
        assert isinstance(generated.content[0], TextContent)
        generated_payload = json.loads(generated.content[0].text)
        assert generated_payload["turn_number"] == 1
