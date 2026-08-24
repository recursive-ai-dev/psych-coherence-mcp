"""Integration tests for public tool functions and portable session state."""

import asyncio
import json

import pytest

from psych_coherence_mcp import (
    CreateSessionInput,
    GenerateResponseInput,
    ImportSessionInput,
    RecallInput,
    RecordResponseInput,
    SessionIdInput,
    StoreBeliefInput,
    StoreMemoryInput,
    psy_create_session,
    psy_end_session,
    psy_export_session,
    psy_generate_response,
    psy_get_coherence_state,
    psy_import_session,
    psy_recall,
    psy_record_response,
    psy_store_belief,
    psy_store_memory,
)
from psych_coherence_mcp.state import SESSIONS


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    SESSIONS.clear()
    yield
    SESSIONS.clear()


async def create(session_id: str = "integration") -> dict:
    return json.loads(
        await psy_create_session(
            CreateSessionInput(persona_id="engineer_kai", session_id=session_id)
        )
    )


@pytest.mark.asyncio
async def test_complete_session_lifecycle() -> None:
    assert (await create())["status"] == "active"

    brief = json.loads(
        await psy_generate_response(
            GenerateResponseInput(
                session_id="integration", user_text="How should I plan this project?"
            )
        )
    )
    assert brief["turn_number"] == 1
    assert brief["generation_constraints"]["persona_name"] == "Kai"

    recorded = json.loads(
        await psy_record_response(
            RecordResponseInput(
                session_id="integration",
                response_text="Let's break this down into a small sequence of verifiable steps.",
            )
        )
    )
    assert recorded["status"] == "recorded"

    ended = json.loads(await psy_end_session(SessionIdInput(session_id="integration")))
    assert ended["status"] == "ended"
    assert ended["total_turns"] == 1

    repeated = json.loads(await psy_end_session(SessionIdInput(session_id="integration")))
    assert repeated["status"] == "not_found"


@pytest.mark.asyncio
async def test_memory_access_count_changes_only_for_selected_results() -> None:
    await create()
    for index in range(3):
        await psy_store_memory(
            StoreMemoryInput(
                session_id="integration",
                content=f"Python project detail {index}",
                tags=["python", "project"],
            )
        )

    recalled = json.loads(
        await psy_recall(
            RecallInput(session_id="integration", query="python project", max_results=1)
        )
    )
    assert len(recalled["results"]) == 1
    assert sum(memory.access_count for memory in SESSIONS["integration"].long_term_memories) == 1


@pytest.mark.asyncio
async def test_concurrent_belief_updates_are_serialized() -> None:
    await create()
    await asyncio.gather(
        *(
            psy_store_belief(
                StoreBeliefInput(
                    session_id="integration",
                    entity="counter",
                    attribute="value",
                    value=str(index),
                )
            )
            for index in range(20)
        )
    )
    state = json.loads(await psy_get_coherence_state(SessionIdInput(session_id="integration")))
    assert state["belief_stats"]["total_beliefs"] == 1
    assert state["belief_stats"]["total_contradictions"] == 19
    assert len(state["contradictions_detected"]) == 5


@pytest.mark.asyncio
async def test_snapshot_round_trip() -> None:
    await create()
    await psy_store_memory(
        StoreMemoryInput(session_id="integration", content="The release is Friday.")
    )
    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="integration")))
    restored = json.loads(
        await psy_import_session(ImportSessionInput(snapshot=snapshot, new_session_id="restored"))
    )
    assert restored["status"] == "imported"
    assert restored["memories_restored"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"snapshot_version": 999, "session": {}},
        {"snapshot_version": 1, "session": []},
        {
            "snapshot_version": 1,
            "session": {
                "session_id": "bad",
                "persona_id": "engineer_kai",
                "turn_count": "many",
            },
        },
        {
            "snapshot_version": 1,
            "session": {
                "session_id": "bad-memory",
                "persona_id": "engineer_kai",
                "long_term_memories": ["not-an-object"],
            },
        },
    ],
)
async def test_invalid_snapshots_return_structured_errors(snapshot: dict) -> None:
    result = json.loads(await psy_import_session(ImportSessionInput(snapshot=snapshot)))
    assert result["status"] == "invalid_snapshot"
    assert result["error"]


@pytest.mark.asyncio
async def test_safety_brief_and_response_recording() -> None:
    await create()
    brief = json.loads(
        await psy_generate_response(
            GenerateResponseInput(
                session_id="integration",
                user_text="I want to kill myself tonight. I have a plan and can't stop myself.",
            )
        )
    )
    assert brief["generation_constraints"]["priority"] == "safety_first"

    assessment = json.loads(
        await psy_record_response(
            RecordResponseInput(
                session_id="integration",
                response_text=(
                    "Are you in immediate danger, and are you safe? Call emergency services "
                    "or a crisis line and contact a trusted person nearby."
                ),
            )
        )
    )
    assert assessment["alignment"]["passes_safety_check"] is True
