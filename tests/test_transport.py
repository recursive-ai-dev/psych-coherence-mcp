"""End-to-end smoke test for the real MCP stdio transport."""

import copy
import hashlib
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


async def test_audit_fixes_over_stdio() -> None:
    # Lower only the registry cap in the child process to exercise the production
    # locking and tool validation paths without retaining 1,000 sessions.
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "import psych_coherence_mcp.server as s; s.MAX_ACTIVE_SESSIONS = 2; s.main()"],
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        async def call(name: str, **params) -> dict:
            result = await session.call_tool(name, arguments={"params": params})
            assert not result.isError, result.content
            assert isinstance(result.content[0], TextContent)
            return json.loads(result.content[0].text)

        assert (await call("psy_create_session", persona_id="engineer_kai", session_id="wire"))[
            "status"
        ] == "active"
        first = await call(
            "psy_generate_response",
            session_id="wire",
            user_text="I will hurt them tonight. I have a plan. I am safe now.",
        )
        assert first["generation_constraints"]["priority"] == "safety_first"
        second = await call(
            "psy_generate_response", session_id="wire", user_text="ordinary project"
        )
        response = "This unsafe design is a callback problem."
        second_record = await call(
            "psy_record_response",
            session_id="wire",
            generation_id=second["generation_id"],
            response_text=response,
        )
        assert second_record["turn"] == 2
        delayed = await call(
            "psy_record_response",
            session_id="wire",
            generation_id=first["generation_id"],
            response_text=response,
        )
        assert delayed["turn"] == 1
        assert delayed["alignment"]["safety_response_required"] is True
        assert delayed["alignment"]["passes_safety_check"] is False
        assert (
            await call(
                "psy_record_response",
                session_id="wire",
                generation_id=first["generation_id"],
                response_text=response,
            )
        )["status"] == "already_recorded"
        assert (
            await call(
                "psy_record_response",
                session_id="wire",
                generation_id="unknown",
                response_text=response,
            )
        )["status"] == "generation_not_found"
        missing_id = await session.call_tool(
            "psy_record_response",
            arguments={"params": {"session_id": "wire", "response_text": response}},
        )
        assert missing_id.isError is True

        pending = await call(
            "psy_generate_response", session_id="wire", user_text="project planning"
        )
        snapshot = await call("psy_export_session", session_id="wire")
        for risk in ([], {}, None, "invalid"):
            invalid = copy.deepcopy(snapshot)
            invalid["session"]["response_history"][-1]["risk_level"] = risk
            rejected = await call("psy_import_session", snapshot=invalid, overwrite=True)
            assert rejected["status"] == "invalid_snapshot"
        # Rejected overwrites leave the original generation usable.
        assert (
            await call(
                "psy_record_response",
                session_id="wire",
                generation_id=pending["generation_id"],
                response_text=response,
            )
        )["status"] == "recorded"
        legacy = copy.deepcopy(snapshot)
        del legacy["session"]["response_history"][-1]["risk_level"]
        assert (await call("psy_import_session", snapshot=legacy, new_session_id="legacy"))[
            "status"
        ] == "imported"
        migrated = await call(
            "psy_record_response",
            session_id="legacy",
            generation_id=pending["generation_id"],
            response_text=response,
        )
        assert migrated["alignment"]["safety_response_required"] is True
        assert (await call("psy_import_session", snapshot=snapshot, new_session_id="overflow"))[
            "status"
        ] == "limit_reached"
        assert (
            await call(
                "psy_import_session", snapshot=snapshot, new_session_id="legacy", overwrite=True
            )
        )["status"] == "imported"
        await call("psy_end_session", session_id="legacy")

        # Both topic retention and long-token limits run through actual MCP calls.
        for index in range(1001):
            # The tokenizer drops digits, so encode unique topics alphabetically.
            suffix = chr(97 + index // 676) + chr(97 + index // 26 % 26) + chr(97 + index % 26)
            await call("psy_generate_response", session_id="wire", user_text="topic" + suffix)
        await call("psy_generate_response", session_id="wire", user_text="x" * 501)
        await call(
            "psy_store_belief",
            session_id="wire",
            entity="user",
            attribute="city",
            value="UniqueCity123",
        )
        snapshot = await call("psy_export_session", session_id="wire")
        topic = snapshot["session"]["topic_state"]
        assert len(topic["topic_history"]) == len(topic["topic_keywords"]) == 1000
        assert len(topic["current_topic"]) == 500
        assert (await call("psy_import_session", snapshot=snapshot, new_session_id="restored"))[
            "status"
        ] == "imported"
        restored = await call("psy_export_session", session_id="restored")
        assert restored["session"]["topic_state"] == topic
        brief = await call(
            "psy_generate_response", session_id="restored", user_text="What city do I live in?"
        )
        assert brief["relevant_beliefs"][0]["value"] == "UniqueCity123"


async def test_deep_stabilization_fixes_over_stdio() -> None:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "psych_coherence_mcp"])
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        async def call(name: str, **params) -> dict:
            result = await session.call_tool(name, arguments={"params": params})
            assert not result.isError, result.content
            assert isinstance(result.content[0], TextContent)
            return json.loads(result.content[0].text)

        await call("psy_create_session", persona_id="engineer_kai", session_id="deep-wire")
        for content in ("unrelated", "alpha\nbeta"):
            await call("psy_store_memory", session_id="deep-wire", content=content)
        recalled = await call("psy_recall", session_id="deep-wire", query="beta", max_results=1)
        assert recalled["results"][0]["content"]["text"] == "alpha\nbeta"

        brief = await call("psy_generate_response", session_id="deep-wire", user_text="beta")
        text = "    Preserve this indentation.\n"
        recorded = await call(
            "psy_record_response",
            session_id="deep-wire",
            generation_id=brief["generation_id"],
            response_text=text,
        )
        assert recorded["status"] == "recorded"
        snapshot = await call("psy_export_session", session_id="deep-wire")
        entry = snapshot["session"]["response_history"][0]
        assert entry["assistant_text"] == text
        assert entry["assistant_response_hash"] == hashlib.sha256(text.encode()).hexdigest()
        malformed = copy.deepcopy(snapshot)
        del malformed["session"]["response_history"][0]["assistant_recorded_at"]
        assert (await call("psy_import_session", snapshot=malformed, overwrite=True))[
            "status"
        ] == "invalid_snapshot"
        assert (await call("psy_export_session", session_id="deep-wire"))["session"] == snapshot[
            "session"
        ]

        await call("psy_import_session", snapshot=snapshot, new_session_id="restored-wire")
        for response, expected in ((text, "already_recorded"), (text.strip(), "response_conflict")):
            result = await call(
                "psy_record_response",
                session_id="restored-wire",
                generation_id=brief["generation_id"],
                response_text=response,
            )
            assert result["status"] == expected
