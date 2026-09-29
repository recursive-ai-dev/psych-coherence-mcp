"""Regressions for state consistency and memory retrieval."""

import json

import pytest

from psych_coherence_mcp import server
from psych_coherence_mcp.coherence import compute_memory_relevance, update_topic_state
from psych_coherence_mcp.models import MemoryEntry, Session
from psych_coherence_mcp.schemas import (
    AnalyzeInputModel,
    CreateSessionInput,
    GenerateResponseInput,
    RecallInput,
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


async def create():
    await server.psy_create_session(
        CreateSessionInput(persona_id="engineer_kai", session_id="stabilization")
    )
    return SESSIONS["stabilization"]


@pytest.mark.parametrize("word", ["café", "東京", "naïve"])
def test_memory_relevance_matches_unicode_content(word):
    memory = MemoryEntry("memory", {"text": word}, "semantic", iso_utc_now(), 0.5, decay_rate=0)
    exact_score = compute_memory_relevance([word], memory)
    unrelated_score = compute_memory_relevance(["unrelated"], memory)
    assert exact_score - unrelated_score == pytest.approx(0.5)


async def test_unicode_recall_ranks_matching_memory_first():
    await create()
    for content in ("unrelated", "café"):
        await server.psy_store_memory(StoreMemoryInput(session_id="stabilization", content=content))
    result = json.loads(
        await server.psy_recall(
            RecallInput(session_id="stabilization", query="café", max_results=1)
        )
    )
    assert result["results"][0]["content"]["text"] == "café"


def test_topic_free_turn_keeps_transition_consistent():
    session = Session("topic", "engineer_kai", iso_utc_now())
    update_topic_state(session, ["alpha"])
    update_topic_state(session, ["beta"])
    result = update_topic_state(session, [])
    assert session.topic_state.transition_type == result["transition_type"] == "continuation"
    assert session.topic_state.current_topic == "beta"
    assert session.topic_state.topic_history == ["alpha", "beta"]
    assert session.topic_state.topic_confidence == 0.5


@pytest.mark.parametrize("operation", ["analyze", "memory", "belief", "recall"])
async def test_mutations_refresh_exported_and_listed_updated_at(monkeypatch, operation):
    session = await create()
    await server.psy_store_memory(StoreMemoryInput(session_id="stabilization", content="project"))
    session.updated_at = "2020-01-01T00:00:00+00:00"
    changed_at = "2020-01-02T00:00:00+00:00"
    monkeypatch.setattr(server, "iso_utc_now", lambda: changed_at)
    if operation == "analyze":
        await server.psy_analyze_input(
            AnalyzeInputModel(session_id="stabilization", text="I enjoy creative projects.")
        )
    elif operation == "memory":
        await server.psy_store_memory(
            StoreMemoryInput(session_id="stabilization", content="another project")
        )
    elif operation == "belief":
        await server.psy_store_belief(
            StoreBeliefInput(
                session_id="stabilization", entity="user", attribute="city", value="Rome"
            )
        )
    else:
        await server.psy_recall(RecallInput(session_id="stabilization", query="project"))
    exported = json.loads(
        await server.psy_export_session(SessionIdInput(session_id="stabilization"))
    )
    listed = json.loads(await server.psy_list_sessions())
    assert exported["session"]["updated_at"] == changed_at
    assert listed["sessions"][0]["updated_at"] == changed_at


async def test_empty_recall_and_rejected_writes_preserve_updated_at(monkeypatch):
    session = await create()
    before = session.updated_at
    await server.psy_recall(RecallInput(session_id="stabilization", query="project"))
    monkeypatch.setattr(server, "MAX_MEMORIES_PER_SESSION", 0)
    monkeypatch.setattr(server, "MAX_BELIEFS_PER_SESSION", 0)
    memory = json.loads(
        await server.psy_store_memory(
            StoreMemoryInput(session_id="stabilization", content="project")
        )
    )
    belief = json.loads(
        await server.psy_store_belief(
            StoreBeliefInput(
                session_id="stabilization", entity="user", attribute="city", value="Rome"
            )
        )
    )
    assert memory["status"] == belief["status"] == "limit_reached"
    assert session.updated_at == before


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("urgent", [True, False])
async def test_humanization_config_respects_safety_priority(enabled, urgent):
    await create()
    brief = json.loads(
        await server.psy_generate_response(
            GenerateResponseInput(
                session_id="stabilization",
                user_text=(
                    "I want to kill myself tonight. I have a plan."
                    if urgent
                    else "How should I plan this project?"
                ),
                enable_humanization=enabled,
            )
        )
    )
    if urgent:
        assert brief["generation_constraints"]["priority"] == "safety_first"
    assert brief["humanization_config"]["enabled"] is (enabled and not urgent)
