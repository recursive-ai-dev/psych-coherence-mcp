"""Lifetime statistics must survive bounded history and snapshot migration."""

import copy
import json

import pytest

from psych_coherence_mcp import (
    CreateSessionInput,
    GenerateResponseInput,
    ImportSessionInput,
    SessionIdInput,
    StoreBeliefInput,
    psy_create_session,
    psy_end_session,
    psy_export_session,
    psy_generate_response,
    psy_get_coherence_state,
    psy_import_session,
    psy_store_belief,
)
from psych_coherence_mcp.coherence import compute_coherence_score
from psych_coherence_mcp.state import SESSIONS, _restore_session, _session_snapshot


@pytest.fixture(autouse=True)
def clear_sessions():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


async def test_lifetime_contradictions_survive_eviction_and_restore(monkeypatch):
    monkeypatch.setattr("psych_coherence_mcp.coherence.MAX_SESSION_HISTORY", 2)
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="count"))
    params = SessionIdInput(session_id="count")
    for index in range(10):
        await psy_generate_response(
            GenerateResponseInput(session_id="count", user_text="Project planning")
        )
        await psy_store_belief(
            StoreBeliefInput(session_id="count", entity="user", attribute="city", value=str(index))
        )
    state = json.loads(await psy_get_coherence_state(params))
    assert state["belief_stats"]["total_contradictions"] == 9
    assert state["belief_stats"]["retained_contradictions"] == 2
    assert state["belief_stats"]["contradiction_count_complete"] is True
    assert state["coherence_scores"]["belief_coherence"] == 0.0

    snapshot = json.loads(await psy_export_session(params))
    imported = json.loads(
        await psy_import_session(ImportSessionInput(snapshot=snapshot, overwrite=True))
    )
    assert imported["status"] == "imported"
    await psy_store_belief(
        StoreBeliefInput(session_id="count", entity="user", attribute="city", value="last")
    )
    summary = json.loads(await psy_end_session(params))
    assert summary["total_contradictions"] == 10
    assert summary["retained_contradictions"] == 2
    assert summary["contradiction_count_complete"] is True


@pytest.mark.parametrize("retained,complete", [(0, True), (1, True), (1000, False)])
async def test_legacy_contradiction_migration(retained, complete):
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="legacy"))
    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="legacy")))
    snapshot["session"].pop("contradiction_count", None)
    snapshot["session"].pop("contradiction_count_complete", None)
    snapshot["session"]["contradiction_log"] = [{} for _ in range(retained)]
    restored = _restore_session(snapshot)
    assert restored.total_contradictions == retained
    assert restored.contradiction_count_complete is complete
    # Migration metadata remains stable across subsequent exports and imports.
    assert _restore_session(_session_snapshot(restored)).contradiction_count_complete is complete


@pytest.mark.parametrize(
    "field,value",
    [
        ("contradiction_count", -1),
        ("contradiction_count", True),
        ("contradiction_count", 1.5),
        ("contradiction_count", "1"),
        ("contradiction_count", None),
        ("contradiction_count_complete", "true"),
        ("contradiction_count_complete", 1),
        ("contradiction_count_complete", None),
    ],
)
async def test_invalid_counter_rejects_overwrite_atomically(field, value):
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="atomic"))
    params = SessionIdInput(session_id="atomic")
    snapshot = json.loads(await psy_export_session(params))
    malformed = copy.deepcopy(snapshot)
    malformed["session"][field] = value
    result = json.loads(
        await psy_import_session(ImportSessionInput(snapshot=malformed, overwrite=True))
    )
    assert result["status"] == "invalid_snapshot"
    assert json.loads(await psy_export_session(params))["session"] == snapshot["session"]


async def test_counter_cannot_be_less_than_retained_history():
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="invalid"))
    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="invalid")))
    snapshot["session"]["contradiction_log"] = [{}, {}]
    snapshot["session"]["contradiction_count"] = 1
    result = json.loads(await psy_import_session(ImportSessionInput(snapshot=snapshot)))
    assert result["status"] == "invalid_snapshot"


async def test_large_imported_counter_remains_usable():
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="large"))
    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="large")))
    snapshot["session"]["turn_count"] = 1
    snapshot["session"]["contradiction_count"] = 10**400
    restored = _restore_session(snapshot)
    assert compute_coherence_score(restored)["belief_coherence"] == 0.0
    assert _restore_session(_session_snapshot(restored)).total_contradictions == 10**400


async def test_missing_counter_does_not_upgrade_explicitly_incomplete_history():
    await psy_create_session(CreateSessionInput(persona_id="engineer_kai", session_id="partial"))
    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="partial")))
    del snapshot["session"]["contradiction_count"]
    snapshot["session"]["contradiction_count_complete"] = False
    assert _restore_session(snapshot).contradiction_count_complete is False
