"""Internal data models for conversational state."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


@dataclass
class PersonalityProfile:
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    confidence: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class MoodState:
    primary_emotion: str = "neutral"
    emotion_intensity: float = 0.0
    secondary_emotions: dict[str, float] = field(default_factory=dict)
    valence: float = 0.0  # -1 (negative) to +1 (positive)
    arousal: float = 0.0  # 0 (calm) to 1 (activated)
    formality_level: str = "neutral"
    formality_score: float = 0.5
    directness_level: str = "neutral"
    directness_score: float = 0.5
    detected_needs: list[str] = field(default_factory=list)
    potential_triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LinguisticFeatures:
    word_count: int = 0
    sentence_count: int = 0
    avg_sentence_length: float = 0.0
    vocabulary_richness: float = 0.0  # type-token ratio
    question_count: int = 0
    exclamation_count: int = 0
    uppercase_ratio: float = 0.0
    punctuation_density: float = 0.0
    avg_word_length: float = 0.0
    first_person_ratio: float = 0.0
    hedge_count: int = 0
    intensifier_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryEntry:
    id: str
    content: dict[str, Any]
    memory_type: str  # "episodic", "semantic", "procedural", "emotional"
    timestamp: str
    importance: float
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    decay_rate: float = 0.0289  # per-hour decay; approximately a 24-hour half-life
    associations: list[str] = field(default_factory=list)


@dataclass
class BeliefEntry:
    entity: str
    attribute: str
    value: Any
    confidence: float
    timestamp: str
    source_turn: int


@dataclass
class TopicState:
    current_topic: str = ""
    topic_history: list[str] = field(default_factory=list)
    topic_confidence: float = 0.0
    transition_type: str = "opening"
    topic_keywords: dict[str, list[str]] = field(default_factory=dict)


class DialoguePhase(Enum):
    OPENING = "opening"
    INFORMATION_GATHERING = "information_gathering"
    PROBLEM_SOLVING = "problem_solving"
    RAPPORT_BUILDING = "rapport_building"
    NEGOTIATION = "negotiation"
    CLOSING = "closing"


@dataclass
class Session:
    session_id: str
    persona_id: str
    created_at: str
    turn_count: int = 0
    short_term_memory: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=30))
    long_term_memories: list[MemoryEntry] = field(default_factory=list)
    belief_graph: dict[str, dict[str, BeliefEntry]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    contradiction_log: list[dict[str, Any]] = field(default_factory=list)
    topic_state: TopicState = field(default_factory=TopicState)
    dialogue_phase: str = "opening"
    user_profile: PersonalityProfile = field(default_factory=PersonalityProfile)
    user_profile_history: list[PersonalityProfile] = field(default_factory=list)
    entity_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    pronoun_map: dict[str, str] = field(default_factory=dict)
    response_history: list[dict[str, Any]] = field(default_factory=list)
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
