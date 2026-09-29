"""Boundary and round-trip regressions from the deeper stabilization pass."""

import asyncio
import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from psych_coherence_mcp import server
from psych_coherence_mcp.coherence import compute_memory_relevance
from psych_coherence_mcp.models import MemoryEntry
from psych_coherence_mcp.schemas import (
    CreateSessionInput,
    GenerateResponseInput,
    ImportSessionInput,
    RecallInput,
    RecordResponseInput,
    SessionIdInput,
    StoreBeliefInput,
    StoreMemoryInput,
)
from psych_coherence_mcp.state import SESSIONS
from psych_coherence_mcp.utils import iso_utc_now


@pytest.fixture(autouse=True)
def clear_sessions():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


async def generate(sid="deep"):
    return json.loads(
        await server.psy_generate_response(
            GenerateResponseInput(session_id=sid, user_text="project")
        )
    )


async def record(generation_id, text, sid="deep"):
    return json.loads(
        await server.psy_record_response(
            RecordResponseInput(session_id=sid, generation_id=generation_id, response_text=text)
        )
    )


async def export(sid="deep"):
    return json.loads(await server.psy_export_session(SessionIdInput(session_id=sid)))


async def restore(snapshot, sid="restored", **kwargs):
    return json.loads(
        await server.psy_import_session(
            ImportSessionInput(snapshot=snapshot, new_session_id=sid, **kwargs)
        )
    )


async def populated_snapshot():
    await server.psy_create_session(
        CreateSessionInput(persona_id="engineer_kai", session_id="deep")
    )
    brief = await generate()
    await server.psy_store_memory(StoreMemoryInput(session_id="deep", content="project"))
    await server.psy_store_belief(
        StoreBeliefInput(session_id="deep", entity="user", attribute="city", value="Rome")
    )
    await record(brief["generation_id"], "Original answer.")
    return await export()


@pytest.mark.parametrize("separator", ["\n", "\r", "\t", "\r\n", "\u000b"])
@pytest.mark.parametrize("nested", [False, True])
def test_memory_search_uses_text_not_json_escapes(separator, nested):
    value = f"alpha{separator}beta"
    content = {"details": [{"text": value}]} if nested else {"text": value}
    memory = MemoryEntry("memory", content, "semantic", iso_utc_now(), 0.5, decay_rate=0)
    assert compute_memory_relevance(["beta"], memory) - compute_memory_relevance(
        ["unrelated"], memory
    ) == pytest.approx(0.5)


def test_memory_search_preserves_literal_escape_sequences():
    memory = MemoryEntry(
        "memory", {"text": r"alpha\nbeta"}, "semantic", iso_utc_now(), 0.5, decay_rate=0
    )
    # A literal backslash followed by n is not a word separator in the tokenizer.
    assert compute_memory_relevance(["beta"], memory) == compute_memory_relevance(
        ["unrelated"], memory
    )


async def test_response_recording_preserves_exact_text_across_restore_and_retries():
    await populated_snapshot()
    brief = await generate()
    text = "    Code indentation matters.\n"
    assert (await record(brief["generation_id"], text))["status"] == "recorded"
    before = await export()
    entry = before["session"]["response_history"][-1]
    assert entry["assistant_text"] == text
    assert before["session"]["short_term_memory"][-1]["text"] == text
    assert entry["assistant_response_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert (await restore(before))["status"] == "imported"
    assert (await record(brief["generation_id"], text, "restored"))["status"] == "already_recorded"
    assert (await record(brief["generation_id"], text.strip(), "restored"))[
        "status"
    ] == "response_conflict"
    assert (await export("restored"))["session"]["response_history"] == before["session"][
        "response_history"
    ]


@pytest.mark.parametrize("text", ["", " ", "\t\n", "\u2003"])
def test_blank_responses_still_fail_validation(text):
    with pytest.raises(ValidationError):
        RecordResponseInput(session_id="deep", generation_id="generation", response_text=text)


@pytest.mark.parametrize(
    "malformation",
    [
        "duplicate_memory",
        "future_belief",
        "missing_recorded_at",
        "empty_recorded_at",
        "boolean_version",
        "float_version",
        "numeric_created_at",
        "numeric_updated_at",
    ],
)
async def test_inconsistent_snapshot_rejected_without_replacing_session(malformation):
    snapshot = await populated_snapshot()
    original = copy.deepcopy(snapshot)
    original_session = SESSIONS["deep"]
    data = snapshot["session"]
    if malformation == "duplicate_memory":
        data["long_term_memories"].append(copy.deepcopy(data["long_term_memories"][0]))
    elif malformation == "future_belief":
        data["belief_graph"]["user"]["city"]["source_turn"] = data["turn_count"] + 1
    elif malformation == "missing_recorded_at":
        del data["response_history"][0]["assistant_recorded_at"]
    elif malformation == "empty_recorded_at":
        data["response_history"][0]["assistant_recorded_at"] = ""
    elif malformation == "boolean_version":
        snapshot["snapshot_version"] = True
    elif malformation == "float_version":
        snapshot["snapshot_version"] = 1.0
    else:
        data[malformation.removeprefix("numeric_")] = 20260101
    rejected = await restore(snapshot, "deep", overwrite=True)
    assert rejected["status"] == "invalid_snapshot"
    assert rejected["error"]
    assert SESSIONS["deep"] is original_session
    assert (await export())["session"] == original["session"]


async def test_legacy_recorded_response_without_hash_remains_protected():
    snapshot = await populated_snapshot()
    entry = snapshot["session"]["response_history"][0]
    del entry["assistant_response_hash"]
    assert (await restore(snapshot))["status"] == "imported"
    assert (await record(entry["generation_id"], "Original answer.", "restored"))[
        "status"
    ] == "response_conflict"


@pytest.mark.parametrize("operation", ["recall", "generate"])
async def test_memory_access_counter_boundary_remains_round_trippable(operation):
    snapshot = await populated_snapshot()
    snapshot["session"]["long_term_memories"][0]["access_count"] = 1_000_000_000
    assert (await restore(snapshot))["status"] == "imported"
    if operation == "recall":
        result = json.loads(
            await server.psy_recall(RecallInput(session_id="restored", query="project"))
        )
        assert len(result["results"]) == 1
    else:
        assert len((await generate("restored"))["relevant_memories"]) == 1
    after = await export("restored")
    assert after["session"]["long_term_memories"][0]["access_count"] == 1_000_000_000
    assert (await restore(after, "again"))["status"] == "imported"


async def test_turn_limit_rejects_generation_before_mutating_state():
    snapshot = await populated_snapshot()
    snapshot["session"]["turn_count"] = 999_999_999
    assert (await restore(snapshot))["status"] == "imported"
    accepted = await generate("restored")
    assert accepted["turn_number"] == 1_000_000_000
    before = await export("restored")
    result = await generate("restored")
    assert result["status"] == "limit_reached"
    assert result["error"]
    assert (await export("restored"))["session"] == before["session"]
    assert (await restore(before, "again"))["status"] == "imported"
    assert (await record(accepted["generation_id"], "Final answer.", "restored"))[
        "status"
    ] == "recorded"


async def test_concurrent_response_retries_append_once_and_preserve_winner():
    await populated_snapshot()
    brief = await generate()
    results = await asyncio.gather(
        *(record(brief["generation_id"], "Same answer.") for _ in range(20))
    )
    assert [result["status"] for result in results].count("recorded") == 1
    assert [result["status"] for result in results].count("already_recorded") == 19
    before = await export()
    assert (await record(brief["generation_id"], "Other answer."))["status"] == "response_conflict"
    assert (await export())["session"] == before["session"]
    messages = before["session"]["short_term_memory"]
    assert (
        len(
            [
                message
                for message in messages
                if message.get("generation_id") == brief["generation_id"]
            ]
        )
        == 1
    )


async def test_snapshot_mutation_matrix_remains_usable_or_rejects_atomically():
    snapshot = await populated_snapshot()
    paths = []

    def walk(value, path=()):
        if path:
            paths.append(path)
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, index))

    walk(snapshot)
    await restore(snapshot, "candidate")
    for path in paths:
        for replacement in (None, True, 0, -1, 1.5, "", "invalid", [], {}):
            candidate = copy.deepcopy(snapshot)
            target = candidate
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = replacement
            original_session = SESSIONS["candidate"]
            before = (await export("candidate"))["session"]
            result = await restore(candidate, "candidate", overwrite=True)
            context = (path, replacement, result)
            if result.get("status") == "invalid_snapshot":
                assert SESSIONS["candidate"] is original_session, context
                assert (await export("candidate"))["session"] == before, context
                continue
            assert result["status"] == "imported", context
            await server.psy_recall(RecallInput(session_id="candidate", query="project"))
            await server.psy_get_coherence_state(SessionIdInput(session_id="candidate"))
            brief = await generate("candidate")
            assert (await record(brief["generation_id"], "An answer.", "candidate"))[
                "status"
            ] == "recorded", context
            exported = await export("candidate")
            assert (await restore(exported, "again", overwrite=True))["status"] == "imported", (
                context
            )
            assert (
                json.loads(await server.psy_end_session(SessionIdInput(session_id="again")))[
                    "status"
                ]
                == "ended"
            ), context
