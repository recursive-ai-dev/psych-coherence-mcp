"""Validation and resource-limit regression tests."""

import json

import pytest
from pydantic import ValidationError

import psych_coherence_mcp.server as server_module
from psych_coherence_mcp import (
    CreateSessionInput,
    HumanizeInput,
    StoreBeliefInput,
    StoreMemoryInput,
    psy_create_session,
    psy_humanize_text,
    psy_store_belief,
    psy_store_memory,
)
from psych_coherence_mcp.state import SESSIONS


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    SESSIONS.clear()
    yield
    SESSIONS.clear()


def test_session_ids_reject_control_and_path_characters() -> None:
    for invalid in ("../traversal", "<script>", "white space", "null\x00byte"):
        with pytest.raises(ValidationError):
            CreateSessionInput(persona_id="engineer_kai", session_id=invalid)


async def test_active_session_limit_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "MAX_ACTIVE_SESSIONS", 1)
    first = json.loads(
        await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="first"))
    )
    second = json.loads(
        await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="second"))
    )
    assert first["status"] == "active"
    assert second["status"] == "limit_reached"


async def test_memory_and_belief_limits_return_structured_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="limited"))
    monkeypatch.setattr(server_module, "MAX_MEMORIES_PER_SESSION", 1)
    monkeypatch.setattr(server_module, "MAX_BELIEFS_PER_SESSION", 1)

    await psy_store_memory(StoreMemoryInput(session_id="limited", content="first"))
    memory_limit = json.loads(
        await psy_store_memory(StoreMemoryInput(session_id="limited", content="second"))
    )
    assert memory_limit["status"] == "limit_reached"

    await psy_store_belief(
        StoreBeliefInput(session_id="limited", entity="user", attribute="city", value="Paris")
    )
    belief_limit = json.loads(
        await psy_store_belief(
            StoreBeliefInput(
                session_id="limited", entity="user", attribute="role", value="Engineer"
            )
        )
    )
    assert belief_limit["status"] == "limit_reached"

    # Updating an existing belief remains possible at the cap.
    update = json.loads(
        await psy_store_belief(
            StoreBeliefInput(session_id="limited", entity="user", attribute="city", value="Rome")
        )
    )
    assert update["status"] == "stored"
    assert update["contradiction_detected"] is True


async def test_zero_emotion_intensity_is_not_replaced_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_mood: dict = {}

    def capture_humanization(text: str, persona: dict, mood: dict, level: float) -> dict:
        captured_mood.update(mood)
        return {"humanized_text": text, "modifications": [], "prosody_hints": []}

    monkeypatch.setattr(server_module, "humanize_text", capture_humanization)
    result = json.loads(
        await psy_humanize_text(
            HumanizeInput(
                text="A sufficiently long sentence for humanization behavior.",
                persona_id="engineer_kai",
                emotional_context="anxiety",
                emotion_intensity=0,
                disfluency_level=0,
            )
        )
    )
    assert result["humanized_text"]
    assert captured_mood["emotion_intensity"] == 0.0
