"""In-memory session registry and portable snapshot serialization."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .constants import (
    MAX_SNAPSHOT_ITEMS,
    PERSONAS,
    SESSION_ID_PATTERN,
    SNAPSHOT_VERSION,
)
from .models import BeliefEntry, MemoryEntry, PersonalityProfile, Session, TopicState
from .utils import iso_utc_now, parse_timestamp

SESSIONS: dict[str, Session] = {}
SESSIONS_LOCK = asyncio.Lock()


class _SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _MemorySnapshot(_SnapshotModel):
    id: str = Field(min_length=1, max_length=100)
    content: dict[str, Any]
    memory_type: Literal["episodic", "semantic", "procedural", "emotional"]
    timestamp: str = Field(min_length=1, max_length=64)
    importance: float = Field(ge=0.0, le=1.0)
    access_count: int = Field(default=0, ge=0, le=1_000_000_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    decay_rate: float = Field(default=0.0289, ge=0.0, le=1.0)
    associations: list[str] = Field(default_factory=list, max_length=100)


class _ProfileSnapshot(_SnapshotModel):
    openness: float = Field(default=0.5, ge=0.0, le=1.0)
    conscientiousness: float = Field(default=0.5, ge=0.0, le=1.0)
    extraversion: float = Field(default=0.5, ge=0.0, le=1.0)
    agreeableness: float = Field(default=0.5, ge=0.0, le=1.0)
    neuroticism: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class _BeliefSnapshot(_SnapshotModel):
    entity: str = Field(min_length=1, max_length=200)
    attribute: str = Field(min_length=1, max_length=200)
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: str = Field(min_length=1, max_length=64)
    source_turn: int = Field(ge=0, le=1_000_000_000)


class _TopicSnapshot(_SnapshotModel):
    current_topic: str = Field(default="", max_length=500)
    topic_history: list[str] = Field(default_factory=list, max_length=MAX_SNAPSHOT_ITEMS)
    topic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    transition_type: Literal["opening", "continuation", "shift", "return"] = "opening"
    topic_keywords: dict[str, list[str]] = Field(default_factory=dict)


async def _get_session(session_id: str) -> Session:
    """Return an active session or raise a user-facing lookup error."""
    async with SESSIONS_LOCK:
        session = SESSIONS.get(session_id)
    if session is None:
        raise ValueError(
            f"Session '{session_id}' not found. Create one first with psy_create_session."
        )
    session.last_accessed = iso_utc_now()
    return session


def _session_snapshot(session: Session) -> dict[str, Any]:
    """Convert session state into a JSON-safe, versioned snapshot."""
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "exported_at": iso_utc_now(),
        "session": {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turn_count": session.turn_count,
            "short_term_memory": list(session.short_term_memory),
            "long_term_memories": [asdict(memory) for memory in session.long_term_memories],
            "belief_graph": {
                entity: {attribute: asdict(belief) for attribute, belief in attributes.items()}
                for entity, attributes in session.belief_graph.items()
            },
            "contradiction_log": session.contradiction_log,
            "topic_state": asdict(session.topic_state),
            "dialogue_phase": session.dialogue_phase,
            "user_profile": asdict(session.user_profile),
            "user_profile_history": [asdict(profile) for profile in session.user_profile_history],
            "entity_registry": session.entity_registry,
            "pronoun_map": session.pronoun_map,
            "response_history": session.response_history,
        },
    }


def _restore_session(snapshot: dict[str, Any], session_id: str | None = None) -> Session:
    """Validate and restore a session from an exported snapshot."""
    if snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError(f"Unsupported snapshot_version; expected {SNAPSHOT_VERSION}.")

    data = snapshot.get("session")
    if not isinstance(data, dict):
        raise ValueError("Snapshot is missing the session object.")

    persona_id = data.get("persona_id")
    if persona_id not in PERSONAS:
        raise ValueError(f"Snapshot references unknown persona '{persona_id}'.")

    sid = session_id or data.get("session_id")
    if not isinstance(sid, str) or re.fullmatch(SESSION_ID_PATTERN, sid.strip()) is None:
        raise ValueError("Snapshot session_id must be 1-100 safe identifier characters.")

    def limited_list(name: str) -> list[Any]:
        value = data.get(name, [])
        if not isinstance(value, list):
            raise ValueError(f"Snapshot field '{name}' must be a list.")
        if len(value) > MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"Snapshot field '{name}' exceeds {MAX_SNAPSHOT_ITEMS} items.")
        return value

    def mapping(name: str) -> dict[str, Any]:
        value = data.get(name, {})
        if not isinstance(value, dict) or len(value) > MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"Snapshot field '{name}' must be a reasonably sized object.")
        return value

    def dict_entries(name: str) -> list[dict[str, Any]]:
        entries = limited_list(name)
        if not all(isinstance(entry, dict) for entry in entries):
            raise ValueError(f"Every item in snapshot field '{name}' must be an object.")
        return entries

    raw_turn_count = data.get("turn_count", 0)
    if isinstance(raw_turn_count, bool) or not isinstance(raw_turn_count, int):
        raise ValueError("Snapshot turn_count must be an integer.")
    if not 0 <= raw_turn_count <= 1_000_000_000:
        raise ValueError("Snapshot turn_count is outside the supported range.")

    created_at = str(data.get("created_at", iso_utc_now()))
    updated_at = str(data.get("updated_at", created_at))
    parse_timestamp(created_at)
    parse_timestamp(updated_at)

    memories: list[MemoryEntry] = []
    for item in dict_entries("long_term_memories"):
        validated_memory = _MemorySnapshot.model_validate(item)
        parse_timestamp(validated_memory.timestamp)
        memories.append(MemoryEntry(**validated_memory.model_dump()))

    profile_history = [
        PersonalityProfile(**_ProfileSnapshot.model_validate(item).model_dump())
        for item in dict_entries("user_profile_history")
    ]
    user_profile = PersonalityProfile(
        **_ProfileSnapshot.model_validate(mapping("user_profile")).model_dump()
    )

    beliefs: dict[str, dict[str, BeliefEntry]] = defaultdict(dict)
    raw_beliefs = mapping("belief_graph")
    belief_count = 0
    for entity, attributes in raw_beliefs.items():
        if not isinstance(attributes, dict):
            raise ValueError("Each belief_graph entity must map to an object of attributes.")
        belief_count += len(attributes)
        if belief_count > MAX_SNAPSHOT_ITEMS:
            raise ValueError(f"Snapshot belief_graph exceeds {MAX_SNAPSHOT_ITEMS} beliefs.")
        for attribute, raw_belief in attributes.items():
            validated_belief = _BeliefSnapshot.model_validate(raw_belief)
            if validated_belief.entity != entity or validated_belief.attribute != attribute:
                raise ValueError(
                    "Snapshot belief_graph keys must match each belief's entity and attribute."
                )
            parse_timestamp(validated_belief.timestamp)
            beliefs[str(entity)][str(attribute)] = BeliefEntry(**validated_belief.model_dump())

    topic = _TopicSnapshot.model_validate(mapping("topic_state"))
    if len(topic.topic_keywords) > MAX_SNAPSHOT_ITEMS or any(
        not isinstance(keywords, list) or len(keywords) > 100
        for keywords in topic.topic_keywords.values()
    ):
        raise ValueError("Snapshot topic_keywords is invalid or too large.")

    phase = data.get("dialogue_phase", "opening")
    valid_phases = {
        "opening",
        "information_gathering",
        "problem_solving",
        "rapport_building",
        "negotiation",
        "closing",
    }
    if phase not in valid_phases:
        raise ValueError(f"Snapshot dialogue_phase '{phase}' is invalid.")

    entity_registry = mapping("entity_registry")
    pronoun_map = mapping("pronoun_map")
    if not all(
        isinstance(key, str) and isinstance(value, str) for key, value in pronoun_map.items()
    ):
        raise ValueError("Snapshot pronoun_map must map strings to strings.")

    return Session(
        session_id=sid.strip(),
        persona_id=persona_id,
        created_at=created_at,
        turn_count=raw_turn_count,
        short_term_memory=deque(dict_entries("short_term_memory"), maxlen=30),
        long_term_memories=memories,
        belief_graph=beliefs,
        contradiction_log=dict_entries("contradiction_log"),
        topic_state=TopicState(**topic.model_dump()),
        dialogue_phase=phase,
        user_profile=user_profile,
        user_profile_history=profile_history,
        entity_registry=entity_registry,
        pronoun_map=pronoun_map,
        response_history=dict_entries("response_history"),
        updated_at=updated_at,
    )
