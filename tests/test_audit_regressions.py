"""Regression coverage for all seven codebase audit findings."""

import asyncio
import copy
import json

import pytest

import psych_coherence_mcp.server as server
from psych_coherence_mcp.analysis import assess_conversational_safety, assess_response_safety
from psych_coherence_mcp.coherence import recall_beliefs, update_topic_state
from psych_coherence_mcp.constants import MAX_TOPIC_HISTORY, MAX_TOPIC_LABEL_LENGTH
from psych_coherence_mcp.schemas import (
    CreateSessionInput,
    GenerateResponseInput,
    ImportSessionInput,
    RecordResponseInput,
    SessionIdInput,
    StoreBeliefInput,
)
from psych_coherence_mcp.state import SESSIONS


@pytest.fixture(autouse=True)
def clear_sessions():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


async def create(sid="audit"):
    await server.psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id=sid))


async def generate(text="ordinary project", sid="audit", **kwargs):
    return json.loads(
        await server.psy_generate_response(
            GenerateResponseInput(session_id=sid, user_text=text, **kwargs)
        )
    )


async def record(generation_id, text="A useful answer to the question.", sid="audit"):
    return json.loads(
        await server.psy_record_response(
            RecordResponseInput(session_id=sid, generation_id=generation_id, response_text=text)
        )
    )


async def export(sid="audit"):
    return json.loads(await server.psy_export_session(SessionIdInput(session_id=sid)))


async def restore(snapshot, sid="restored", **kwargs):
    return json.loads(
        await server.psy_import_session(
            ImportSessionInput(snapshot=snapshot, new_session_id=sid, **kwargs)
        )
    )


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("I will hurt them tonight. I have a plan. I am safe now.", "imminent"),
        ("I have no plan but I will kill myself tonight.", "high"),
        ("I am not going to hurt myself. I will kill them tonight.", "high"),
        ("I am not going to hurt myself and I will kill them tonight.", "high"),
        ("I will hurt them tonight and I am not going to hurt myself.", "high"),
        ("I will not hesitate to kill myself tonight.", "high"),
        ("I am not safe and will hurt them tonight.", "high"),
        ("I will kill myself tonight. They are safe now.", "high"),
        ("I have thoughts of suicide, but I am safe now and have no plan.", "low"),
        ("I am not going to kill myself tonight.", "low"),
        ("I will hurt them. I am safe now.", "moderate"),
        ("I want to kill myself. I am safe now.", "moderate"),
        ("I have thoughts of suicide but I do not have a plan.", "moderate"),
    ],
)
def test_protection_does_not_override_active_threat(text, level):
    result = assess_conversational_safety(text)
    assert result["risk_level"] == level
    assert result["requires_safety_first_response"] == (level in {"high", "imminent"})


def test_mixed_subjects_are_assessed_separately():
    result = assess_conversational_safety(
        "I am not going to hurt myself. I will hurt them tonight. I have a plan."
    )
    assert result["category_risk_levels"] == {
        "self_harm_or_suicide": "low",
        "harm_to_others": "imminent",
    }


@pytest.mark.parametrize(
    "text",
    [
        "This unsafe design is a callback problem.",
        "Are you safe? Don't call emergency services or contact a trusted person.",
        "Are you safe? Never call a crisis line.",
        "Are you safe? Avoid contacting a trusted person.",
        "Emergency crisis safe call nearby.",
        "You are safe. Call emergency services.",
        "Are you safe? Calling for help is unnecessary.",
    ],
)
def test_safety_response_rejects_substrings_and_negation(text):
    assert assess_response_safety(text)["passes"] is False


@pytest.mark.parametrize(
    "text",
    [
        "Are you safe right now? Please call emergency services or contact a trusted person.",
        "Are you in immediate danger? Reach out to a trusted friend.",
        "Can you stay safe? Call a crisis line.",
    ],
)
def test_safety_response_requires_both_elements(text):
    result = assess_response_safety(text)
    assert result["passes"] is True
    assert all(result["elements"].values())
    assert result["assessment_type"] == "limited_rule_based_heuristic"


async def test_import_capacity_and_concurrent_create_import(monkeypatch):
    await create()
    snapshot = await export()
    monkeypatch.setattr(server, "MAX_ACTIVE_SESSIONS", 3)
    results = await asyncio.gather(
        *(restore(snapshot, f"imported-{i}") for i in range(5)),
        *(
            server.psy_create_session(
                CreateSessionInput(persona_id="engineer_kai", session_id=f"created-{i}")
            )
            for i in range(5)
        ),
    )
    assert len(SESSIONS) == 3
    statuses = [r["status"] if isinstance(r, dict) else json.loads(r)["status"] for r in results]
    assert statuses.count("limit_reached") == 8
    assert (await restore(snapshot, "audit", overwrite=True))["status"] == "imported"
    assert (await restore(snapshot, "new", overwrite=True))["status"] == "limit_reached"
    assert len(SESSIONS) == 3


async def test_long_topics_and_sustained_changes_round_trip():
    await create()
    for index in range(MAX_TOPIC_HISTORY + 2):
        update_topic_state(SESSIONS["audit"], [f"topic{index}"])
    await generate("x" * 501)
    before = await export()
    topic = before["session"]["topic_state"]
    assert len(topic["topic_history"]) == MAX_TOPIC_HISTORY
    assert len(topic["topic_keywords"]) == MAX_TOPIC_HISTORY
    assert len(topic["current_topic"]) == MAX_TOPIC_LABEL_LENGTH
    assert topic["current_topic"] in topic["topic_keywords"]
    assert (await restore(before))["status"] == "imported"
    assert (await export("restored"))["session"]["topic_state"] == topic


async def test_topic_continuations_preserve_current_topic_and_bounds():
    await create()
    state = SESSIONS["audit"].topic_state
    update_topic_state(SESSIONS["audit"], ["original"])
    for index in range(MAX_TOPIC_HISTORY + 2):
        update_topic_state(SESSIONS["audit"], [f"associated{index}", "original"])
    assert state.current_topic == "original"
    assert "original" in state.topic_keywords
    assert len(state.topic_keywords) == MAX_TOPIC_HISTORY
    assert (await restore(await export()))["status"] == "imported"


async def test_legacy_topic_repair_is_explicit_and_preserves_input():
    await create()
    snapshot = await export()
    topic = snapshot["session"]["topic_state"]
    long_label = "x" * 600
    topic.update(
        current_topic=long_label,
        topic_history=[long_label] * 1001,
        topic_keywords={long_label: [long_label], **{f"t{i}": [] for i in range(1001)}},
    )
    original = copy.deepcopy(snapshot)
    assert (await restore(snapshot))["status"] == "invalid_snapshot"
    result = await restore(snapshot, repair_topics=True)
    assert result["status"] == "imported"
    assert result["topic_state_repaired"] is True
    assert snapshot == original
    repaired = await export("restored")
    assert (
        repaired["session"]["topic_state"]["current_topic"]
        in repaired["session"]["topic_state"]["topic_keywords"]
    )
    assert (await restore(repaired, "again"))["status"] == "imported"


async def test_delayed_responses_retries_and_conflicts():
    await create()
    first = await generate("I will hurt them tonight. I have a plan. I am safe now.")
    # A different risk context now requires explicit resolution by the client.
    second = await generate(safety_context_resolved=True)
    assert first["generation_constraints"]["priority"] == "safety_first"
    response2 = await record(second["generation_id"])
    response1 = await record(first["generation_id"], "This unsafe design is a callback problem.")
    assert response2["turn"] == 2
    assert response2["alignment"]["safety_response_required"] is False
    assert response1["turn"] == 1
    assert response1["alignment"]["safety_response_required"] is True
    assert response1["alignment"]["passes_safety_check"] is False
    before = await export()
    assert (await record(first["generation_id"], "This unsafe design is a callback problem."))[
        "status"
    ] == "already_recorded"
    assert (await record(first["generation_id"], "A different response."))[
        "status"
    ] == "response_conflict"
    assert (await record("unknown"))["status"] == "generation_not_found"
    assert (await export())["session"] == before["session"]
    assert [e["turn"] for e in SESSIONS["audit"].short_term_memory if e["role"] == "assistant"] == [
        2,
        1,
    ]
    assert (await restore(before))["status"] == "imported"
    assert (
        await record(
            first["generation_id"], "This unsafe design is a callback problem.", "restored"
        )
    )["status"] == "already_recorded"


async def test_expired_generation_and_long_response_retries(monkeypatch):
    await create()
    monkeypatch.setattr(server, "MAX_SESSION_HISTORY", 1)
    first = await generate()
    second = await generate()
    assert (await record(first["generation_id"]))["status"] == "generation_not_found"
    text = "word " * 150
    await record(second["generation_id"], text)
    assert (await record(second["generation_id"], text))["status"] == "already_recorded"
    assert (await record(second["generation_id"], text + "different"))[
        "status"
    ] == "response_conflict"


@pytest.mark.parametrize("risk", [[], {}, None, "unexpected"])
async def test_malformed_risk_rejected_atomically(risk):
    await create()
    brief = await generate()
    original_session = SESSIONS["audit"]
    snapshot = await export()
    snapshot["session"]["response_history"][0]["risk_level"] = risk
    assert (await restore(snapshot, "audit", overwrite=True))["status"] == "invalid_snapshot"
    assert SESSIONS["audit"] is original_session
    assert (await record(brief["generation_id"]))["status"] == "recorded"


async def test_legacy_missing_risk_and_generation_id_migrate_conservatively():
    await create()
    await generate()
    snapshot = await export()
    entry = snapshot["session"]["response_history"][0]
    del entry["risk_level"]
    del entry["generation_id"]
    assert (await restore(snapshot))["status"] == "imported"
    history = (await export("restored"))["session"]["response_history"]
    assert history[0]["risk_level"] == "unknown"
    result = await record(history[0]["generation_id"], sid="restored")
    assert result["alignment"]["safety_response_required"] is True
    assert result["alignment"]["passes_safety_check"] is False


async def test_generation_recalls_current_beliefs_after_restore():
    await create()
    for value in ("UniqueCity123", "NewCity456"):
        await server.psy_store_belief(
            StoreBeliefInput(
                session_id="audit", entity="user", attribute="city", value=value, confidence=0.9
            )
        )
        brief = await generate("What city do I live in?")
        belief = brief["relevant_beliefs"][0]
        assert belief["value"] == value
        assert belief["confidence"] == 0.9
        assert belief["provenance"]["timestamp"]
    assert (await restore(await export()))["status"] == "imported"
    brief = await generate("What city do I live in?", "restored")
    assert brief["relevant_beliefs"][0]["value"] == "NewCity456"
    for i in range(10):
        await server.psy_store_belief(
            StoreBeliefInput(
                session_id="audit", entity="user", attribute=f"detail{i}", value="fact"
            )
        )
    assert len(recall_beliefs(SESSIONS["audit"], "my details")) == 5
    assert recall_beliefs(SESSIONS["audit"], "unrelated topic") == []
