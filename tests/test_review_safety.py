"""Controls and state invariants for the adversarial-review fixes."""

import copy
import json

import pytest
from pydantic import ValidationError

from psych_coherence_mcp import server
from psych_coherence_mcp.analysis import assess_conversational_safety, full_analysis
from psych_coherence_mcp.coherence import update_dialogue_phase
from psych_coherence_mcp.models import Session
from psych_coherence_mcp.schemas import (
    AnalyzeInputModel,
    BuildConstraintsInput,
    CreateSessionInput,
    GenerateResponseInput,
    ImportSessionInput,
    RecordResponseInput,
    SessionIdInput,
)
from psych_coherence_mcp.state import SESSIONS
from psych_coherence_mcp.utils import iso_utc_now


@pytest.fixture(autouse=True)
def clear_sessions():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


async def create():
    await server.psy_create_session(
        CreateSessionInput(session_id="review", persona_id="counselor_amara")
    )


async def generate(text="An ordinary project.", sid="review", **kwargs):
    return json.loads(
        await server.psy_generate_response(
            GenerateResponseInput(session_id=sid, user_text=text, **kwargs)
        )
    )


async def export(sid="review"):
    return json.loads(await server.psy_export_session(SessionIdInput(session_id=sid)))


async def restore(snapshot, sid="restored", **kwargs):
    return json.loads(
        await server.psy_import_session(
            ImportSessionInput(snapshot=snapshot, new_session_id=sid, **kwargs)
        )
    )


@pytest.mark.parametrize("separator", ["  ", "\t", "\n", "\r\n", "\u00a0"])
async def test_whitespace_preserves_negation_and_source_text(separator):
    text = f"I am not going to hurt{separator}myself tonight."
    assert assess_conversational_safety(text)["risk_level"] == "low"
    await create()
    brief = await generate(text)
    assert brief["user_input"] == text
    assert brief["recent_conversation"][-1]["text"] == text
    assert "priority" not in brief["generation_constraints"]
    ordinary = f"My goal is to learn{separator}gardening."
    for candidate in full_analysis(ordinary)["memory_candidates"]:
        start, end = candidate["source_span"]
        assert ordinary[start:end] == candidate["content"]


@pytest.mark.parametrize(
    ("text", "risk"),
    [
        ("I will kill the process tonight.", "none"),
        ("I will kill my server tonight.", "none"),
        ("I will shoot my family photos today.", "none"),
        ("I will not hurt my wife tonight.", "low"),
        ("I don't want to hurt my children tonight.", "low"),
        ("I will not hesitate to hurt my husband tonight.", "high"),
        ("I will hurt my partner tonight.", "high"),
    ],
)
def test_human_target_controls(text, risk):
    assert assess_conversational_safety(text)["risk_level"] == risk


@pytest.mark.parametrize(
    ("text", "emotion", "polarity"),
    [
        ("I am not happy.", "neutral", 0),
        ("I am not sad.", "neutral", 0),
        ("I am not at all happy.", "neutral", 0),
        ("I\u2019m not happy.", "neutral", 0),
        ("I am not sad, but I am happy.", "joy", 1),
        ("I am not happy. I am sad.", "sadness", -1),
        ("I am not only happy but delighted.", "joy", 1),
        ("Nobody cares. Nothing helps. I am depressed.", "sadness", -1),
    ],
)
def test_emotion_negation_stays_local(text, emotion, polarity):
    mood = full_analysis(text)["mood_state"]
    assert mood["primary_emotion"] == emotion
    assert mood["valence"] == polarity


@pytest.mark.parametrize(
    ("text", "closing"),
    [
        ("Thanks!", True),
        ("Thank you for your help!", True),
        ("That's all, thank you.", True),
        ("See you later.", True),
        ("Goodbye!", True),
        ("Later!", True),
        ("Okay, thanks.", True),
        ("I'll do that later.", False),
        ("Thanks, please explain the next step.", False),
        ("Thanks, write a deployment plan.", False),
        ("Thank you, I need help debugging this.", False),
        ("Thank you. Could you help me deploy this", False),
        ("I can see you understand the problem.", False),
    ],
)
def test_farewells_and_ongoing_requests(text, closing):
    session = Session("review", "counselor_amara", iso_utc_now())
    assert (update_dialogue_phase(session, full_analysis(text), text) == "closing") is closing


async def test_safety_floor_applies_to_alternate_session_tools():
    await create()
    await generate("I want to kill myself tonight.")
    before = await export()
    constraints = json.loads(
        await server.psy_build_constraints(
            BuildConstraintsInput(session_id="review", user_text="Yes, I have a plan.")
        )
    )
    assert constraints["priority"] == "safety_first"
    candidates = json.loads(
        await server.psy_extract_memories(
            AnalyzeInputModel(session_id="review", text="My goal is to finish it tonight.")
        )
    )
    assert candidates["candidates"] == []
    assert (await export())["session"] == before["session"]
    analysis = json.loads(
        await server.psy_analyze_input(
            AnalyzeInputModel(session_id="review", text="My goal is to finish it tonight.")
        )
    )
    assert analysis["safety_assessment"]["requires_safety_first_response"] is True
    assert analysis["memory_candidates"] == []


async def test_session_analysis_records_risk_but_preview_does_not():
    await create()
    text = "I want to hurt my wife tonight."
    await server.psy_build_constraints(BuildConstraintsInput(session_id="review", user_text=text))
    assert (await export())["session"]["safety_context"] == "none"
    await server.psy_analyze_input(AnalyzeInputModel(session_id="review", text=text))
    assert (await generate())["generation_constraints"]["priority"] == "safety_first"


async def test_explicit_resolution_round_trips_and_preserves_old_generation_risk():
    await create()
    first = await generate("I want to kill myself tonight.")
    followup = await generate("I am safe now.")
    assert followup["generation_constraints"]["priority"] == "safety_first"
    resolved = await generate(safety_context_resolved=True)
    assert "priority" not in resolved["generation_constraints"]
    assert resolved["humanization_config"]["enabled"] is True
    snapshot = await export()
    assert snapshot["session"]["safety_context"] == "none"
    assert (await restore(snapshot))["status"] == "imported"
    assert "priority" not in (await generate(sid="restored"))["generation_constraints"]
    for brief, required in [(first, True), (resolved, False)]:
        recorded = json.loads(
            await server.psy_record_response(
                RecordResponseInput(
                    session_id="restored",
                    generation_id=brief["generation_id"],
                    response_text="An ordinary answer.",
                )
            )
        )
        assert recorded["alignment"]["safety_response_required"] is required
        assert recorded["alignment"]["passes_safety_check"] is not required


async def test_resolution_never_suppresses_fresh_risk():
    await create()
    await generate("I want to kill myself tonight.")
    brief = await generate("I will hurt my children tonight.", safety_context_resolved=True)
    assert brief["generation_constraints"]["priority"] == "safety_first"
    assert (await export())["session"]["safety_context"] == "high"


async def test_safety_context_survives_history_eviction(monkeypatch):
    monkeypatch.setattr(server, "MAX_SESSION_HISTORY", 1)
    await create()
    await generate("I will hurt them tonight. I have a plan.")
    for _ in range(3):
        brief = await generate()
        assert brief["psychological_analysis"]["safety_assessment"]["risk_level"] == "imminent"
    snapshot = await export()
    assert len(snapshot["session"]["response_history"]) == 1
    await restore(snapshot)
    assert (await generate(sid="restored"))["generation_constraints"]["priority"] == "safety_first"


@pytest.mark.parametrize("legacy_risk", ["high", "imminent", "unknown", "none"])
async def test_legacy_safety_migration(legacy_risk):
    await create()
    await generate()
    await generate()
    snapshot = await export()
    del snapshot["session"]["safety_context"]
    snapshot["session"]["response_history"][0]["risk_level"] = legacy_risk
    if legacy_risk == "unknown":
        del snapshot["session"]["response_history"][0]["risk_level"]
    await restore(snapshot)
    migrated = await export("restored")
    assert migrated["session"]["safety_context"] == legacy_risk
    brief = await generate(sid="restored")
    assert (brief["generation_constraints"].get("priority") == "safety_first") is (
        legacy_risk != "none"
    )


@pytest.mark.parametrize("retained", [0, 1])
async def test_legacy_incomplete_history_is_conservative(retained):
    await create()
    await generate()
    await generate()
    snapshot = await export()
    del snapshot["session"]["safety_context"]
    snapshot["session"]["response_history"] = snapshot["session"]["response_history"][:retained]
    await restore(snapshot)
    assert (await generate(sid="restored"))["generation_constraints"]["priority"] == "safety_first"


@pytest.mark.parametrize("invalid", [None, True, 0, [], {}, "low", "moderate", "invalid"])
async def test_invalid_safety_context_rejects_overwrite_atomically(invalid):
    await create()
    await generate("I will hurt them tonight.")
    original = await export()
    snapshot = copy.deepcopy(original)
    snapshot["session"]["safety_context"] = invalid
    assert (await restore(snapshot, "review", overwrite=True))["status"] == "invalid_snapshot"
    assert (await export())["session"] == original["session"]


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", "false"])
def test_resolution_requires_a_boolean(invalid):
    with pytest.raises(ValidationError):
        GenerateResponseInput(
            session_id="review", user_text="ordinary", safety_context_resolved=invalid
        )
