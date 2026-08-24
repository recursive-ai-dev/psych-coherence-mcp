"""Unit tests for memory, beliefs, topics, and coherence scoring."""

from datetime import timedelta

from psych_coherence_mcp import (
    BeliefEntry,
    MemoryEntry,
    Session,
    compute_coherence_score,
    compute_memory_relevance,
    detect_contradiction,
    update_topic_state,
)
from psych_coherence_mcp.utils import iso_utc_now, utc_now


def make_session() -> Session:
    return Session(session_id="unit", persona_id="engineer_kai", created_at=iso_utc_now())


def test_memory_relevance_is_bounded_and_tolerates_bad_timestamp() -> None:
    memory = MemoryEntry(
        id="memory",
        content={"text": "A Python release project"},
        memory_type="semantic",
        timestamp="not-a-timestamp",
        importance=0.8,
        tags=["python"],
    )
    score = compute_memory_relevance(["python", "project"], memory)
    assert 0 < score <= 1
    assert compute_memory_relevance([], memory) == 0


def test_memory_recency_uses_entry_decay_rate() -> None:
    timestamp = (utc_now() - timedelta(hours=24)).isoformat()
    slow = MemoryEntry("slow", {"text": "topic"}, "semantic", timestamp, 0.5, decay_rate=0)
    fast = MemoryEntry("fast", {"text": "topic"}, "semantic", timestamp, 0.5, decay_rate=1)
    assert compute_memory_relevance(["topic"], slow) > compute_memory_relevance(["topic"], fast)


def test_topic_history_records_shifts_and_returns_without_duplicate_shift_entries() -> None:
    session = make_session()
    assert update_topic_state(session, ["alpha"])["transition_type"] == "opening"
    assert update_topic_state(session, ["beta"])["transition_type"] == "shift"
    assert session.topic_state.topic_history == ["alpha", "beta"]
    assert update_topic_state(session, ["alpha"])["transition_type"] == "return"
    assert session.topic_state.topic_history == ["alpha", "beta", "alpha"]


def test_belief_contradictions_are_logged() -> None:
    session = make_session()
    session.belief_graph["user"]["city"] = BeliefEntry(
        "user", "city", "Paris", 0.9, iso_utc_now(), 0
    )
    contradiction = detect_contradiction(session, "user", "city", "Rome", 0.8)
    assert contradiction is not None
    assert contradiction["previous_value"] == "Paris"
    assert len(session.contradiction_log) == 1


def test_coherence_scores_stay_bounded() -> None:
    session = make_session()
    session.turn_count = 1
    session.contradiction_log.extend([{}, {}])
    scores = compute_coherence_score(session)
    assert set(scores) == {
        "topic_coherence",
        "memory_coherence",
        "belief_coherence",
        "profile_stability",
        "overall",
    }
    assert all(0 <= score <= 1 for score in scores.values())
