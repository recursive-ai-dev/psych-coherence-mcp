"""Exercise every public MCP tool from an installed package outside the checkout."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


@pytest.mark.parametrize("launcher", ["module", "console", "legacy"])
async def test_all_tools_from_unrelated_working_directory(launcher, tmp_path):
    command = sys.executable
    args = ["-m", "psych_coherence_mcp"]
    if launcher == "console":
        command = str(
            Path(sys.executable).with_name(
                "psych-coherence-mcp" + (".exe" if os.name == "nt" else "")
            )
        )
        args = []
    elif launcher == "legacy":
        args = [str(Path(__file__).resolve().parents[1] / "server.py")]
    parameters = StdioServerParameters(command=command, args=args, cwd=str(tmp_path))
    await asyncio.wait_for(exercise_tools(parameters), timeout=60)


async def exercise_tools(parameters):
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as client,
    ):
        await client.initialize()
        await client.send_ping()
        registered = {tool.name for tool in (await client.list_tools()).tools}
        called = set()

        async def call(name, **params):
            result = await client.call_tool(name, arguments={"params": params} if params else {})
            assert not result.isError, result.content
            assert isinstance(result.content[0], TextContent)
            called.add(name)
            return json.loads(result.content[0].text)

        assert len(await call("psy_list_personas")) == 4
        assert (await call("psy_get_persona", persona_id="engineer_kai"))["name"] == "Kai"
        assert (await call("psy_create_session", persona_id="engineer_kai", session_id="release"))[
            "status"
        ] == "active"
        assert (
            await call("psy_analyze_input", text="I enjoy building tools", session_id="release")
        )["session_profile_updated"]
        assert (await call("psy_store_memory", session_id="release", content="I live in Paris"))[
            "status"
        ] == "stored"
        assert (await call("psy_recall", session_id="release", query="Paris"))["results"]
        for city in ("Paris", "Rome"):
            assert (
                await call(
                    "psy_store_belief",
                    session_id="release",
                    entity="user",
                    attribute="city",
                    value=city,
                )
            )["status"] == "stored"
        brief = await call(
            "psy_generate_response", session_id="release", user_text="What city do I live in?"
        )
        assert brief["relevant_beliefs"][0]["value"] == "Rome"
        assert await call("psy_build_constraints", session_id="release", user_text="Help me plan")
        assert (
            await call(
                "psy_humanize_text", text="Let us work through this.", persona_id="engineer_kai"
            )
        )["humanized_text"]
        assert (await call("psy_assess_safety", text="I enjoy building tools"))[
            "risk_level"
        ] == "none"
        assert (await call("psy_extract_memories", text="I like gardening"))["stored"] is False
        assert (
            await call(
                "psy_record_response",
                session_id="release",
                generation_id=brief["generation_id"],
                response_text="You live in Rome.",
            )
        )["status"] == "recorded"
        assert (await call("psy_list_sessions"))["count"] == 1
        state = await call("psy_get_coherence_state", session_id="release")
        assert state["belief_stats"]["total_contradictions"] == 1
        assert state["belief_stats"]["contradiction_count_complete"] is True
        snapshot = await call("psy_export_session", session_id="release")
        assert (await call("psy_import_session", snapshot=snapshot, new_session_id="restored"))[
            "status"
        ] == "imported"
        assert (await call("psy_end_session", session_id="release"))["status"] == "ended"
        assert (await call("psy_end_session", session_id="restored"))["status"] == "ended"
        assert (await call("psy_list_sessions"))["count"] == 0
        assert called == registered
        assert len(registered) == 18

        # Malformed requests and missing resources must not kill the transport.
        for name, arguments in (
            ("unknown_tool", {}),
            ("psy_generate_response", {"params": {"session_id": "missing", "user_text": "hello"}}),
            ("psy_create_session", {"params": {"persona_id": "invalid"}}),
            ("psy_generate_response", {"params": {"session_id": "missing", "user_text": " "}}),
        ):
            assert (await client.call_tool(name, arguments=arguments)).isError
        await client.send_ping()
