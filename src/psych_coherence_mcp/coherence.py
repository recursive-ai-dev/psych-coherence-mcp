"""Conversation coherence, memory relevance, beliefs, and topic tracking."""

from __future__ import annotations

import json
import math
import random
import re
from typing import Any, TypeVar

from .analysis import tokenize
from .constants import DISCOURSE_MARKERS, MAX_SESSION_HISTORY
from .models import MemoryEntry, PersonalityProfile, Session
from .utils import iso_utc_now, parse_timestamp, utc_now

T = TypeVar("T")


def _append_bounded(items: list[T], item: T) -> None:
    """Append to a history list while enforcing the per-session retention cap."""
    items.append(item)
    if len(items) > MAX_SESSION_HISTORY:
        del items[: len(items) - MAX_SESSION_HISTORY]


def blend_profiles(
    existing: PersonalityProfile, new: PersonalityProfile, new_weight: float
) -> PersonalityProfile:
    """Blend personality profiles with exponential moving average."""
    ew = 1.0 - new_weight
    return PersonalityProfile(
        openness=round(existing.openness * ew + new.openness * new_weight, 4),
        conscientiousness=round(
            existing.conscientiousness * ew + new.conscientiousness * new_weight, 4
        ),
        extraversion=round(existing.extraversion * ew + new.extraversion * new_weight, 4),
        agreeableness=round(existing.agreeableness * ew + new.agreeableness * new_weight, 4),
        neuroticism=round(existing.neuroticism * ew + new.neuroticism * new_weight, 4),
        confidence=round(max(existing.confidence, new.confidence), 4),
    )


def compute_memory_relevance(query_words: list[str], memory: MemoryEntry) -> float:
    """Compute relevance of a memory entry to a query using TF overlap + recency decay."""
    content_text = json.dumps(memory.content).lower()
    content_words = set(tokenize(content_text))
    tag_words = set(t.lower() for t in memory.tags)

    query_set = set(query_words)
    if not query_set:
        return 0.0

    # Word overlap score
    overlap = len(query_set & (content_words | tag_words))
    overlap_score = overlap / len(query_set)

    # Recency decay (exponential, half-life = 24 hours)
    try:
        created = parse_timestamp(memory.timestamp)
        hours_ago = max((utc_now() - created).total_seconds() / 3600.0, 0.0)
        recency_factor = math.exp(-max(memory.decay_rate, 0.0) * hours_ago)
    except (ValueError, TypeError):
        recency_factor = 0.5

    # Importance boost
    importance_factor = 0.5 + 0.5 * memory.importance

    # Access frequency bonus (diminishing returns)
    access_bonus = min(memory.access_count * 0.02, 0.1)

    return round(
        overlap_score * 0.5 + recency_factor * 0.25 + importance_factor * 0.15 + access_bonus, 4
    )


def detect_contradiction(
    session: Session, entity: str, attribute: str, new_value: Any, confidence: float
) -> dict[str, Any] | None:
    """Check if a new belief contradicts an existing one in the belief graph."""
    if entity in session.belief_graph and attribute in session.belief_graph[entity]:
        existing = session.belief_graph[entity][attribute]

        # String comparison (case-insensitive for strings)
        old_val = str(existing.value).lower().strip()
        new_val = str(new_value).lower().strip()

        if old_val != new_val and old_val and new_val:
            contradiction = {
                "entity": entity,
                "attribute": attribute,
                "previous_value": existing.value,
                "previous_confidence": existing.confidence,
                "previous_turn": existing.source_turn,
                "new_value": new_value,
                "new_confidence": confidence,
                "current_turn": session.turn_count,
                "turns_apart": session.turn_count - existing.source_turn,
                "timestamp": iso_utc_now(),
            }
            _append_bounded(session.contradiction_log, contradiction)
            return contradiction

    return None


def update_topic_state(session: Session, topics: list[str]) -> dict[str, Any]:
    """Update topic tracking and return transition information."""
    if not topics:
        return {"transition_type": "continuation", "marker": ""}

    new_topic = topics[0]  # Primary topic
    state = session.topic_state
    previous = state.current_topic

    # Store keyword associations
    state.topic_keywords[new_topic] = topics

    if not previous:
        state.current_topic = new_topic
        _append_bounded(state.topic_history, new_topic)
        state.transition_type = "opening"
        state.topic_confidence = 0.7
        return {"transition_type": "opening", "marker": "", "topic": new_topic}

    if new_topic == previous or any(kw == previous or kw in previous.split() for kw in topics[:3]):
        state.transition_type = "continuation"
        state.topic_confidence = min(1.0, state.topic_confidence + 0.05)
        marker = random.choice(DISCOURSE_MARKERS["continuation"])
        return {"transition_type": "continuation", "marker": marker, "topic": new_topic}

    if new_topic in state.topic_history:
        state.current_topic = new_topic
        _append_bounded(state.topic_history, new_topic)
        state.transition_type = "return"
        state.topic_confidence = 0.6
        marker = random.choice(DISCOURSE_MARKERS["return"]).format(topic=new_topic)
        return {
            "transition_type": "return",
            "marker": marker,
            "topic": new_topic,
            "returning_from": previous,
        }

    # New topic
    state.current_topic = new_topic
    _append_bounded(state.topic_history, new_topic)
    state.transition_type = "shift"
    state.topic_confidence = 0.5
    marker = random.choice(DISCOURSE_MARKERS["shift"])
    return {
        "transition_type": "shift",
        "marker": marker,
        "topic": new_topic,
        "shifted_from": previous,
    }


def update_dialogue_phase(session: Session, analysis: dict[str, Any], user_text: str) -> str:
    """Determine current dialogue phase from accumulated context."""
    mood = analysis.get("mood_state", {})
    needs = mood.get("detected_needs", [])
    text_lower = user_text.lower()

    # Check for closing signals
    closing_signals = [
        "bye",
        "goodbye",
        "thanks",
        "thank you",
        "that's all",
        "gotta go",
        "see you",
        "later",
    ]
    if any(
        re.search(r"(?<!\w)" + re.escape(sig) + r"(?!\w)", text_lower) for sig in closing_signals
    ):
        session.dialogue_phase = "closing"
        return "closing"

    # Check for greeting signals (at start)
    greeting_signals = [
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "howdy",
        "greetings",
    ]
    if session.turn_count <= 2 and any(
        re.search(r"(?<!\w)" + re.escape(sig) + r"(?!\w)", text_lower) for sig in greeting_signals
    ):
        session.dialogue_phase = "opening"
        return "opening"

    # Need-based phase detection
    if "support" in needs or "reassurance" in needs:
        session.dialogue_phase = "problem_solving"
        return "problem_solving"
    if "information" in needs:
        session.dialogue_phase = "information_gathering"
        return "information_gathering"
    if "connection" in needs or "validation" in needs:
        session.dialogue_phase = "rapport_building"
        return "rapport_building"
    if "challenge" in needs or "autonomy" in needs:
        session.dialogue_phase = "negotiation"
        return "negotiation"

    # Default progression
    if session.turn_count < 3:
        session.dialogue_phase = "opening"
    elif session.turn_count < 8:
        session.dialogue_phase = "information_gathering"
    else:
        session.dialogue_phase = "rapport_building"

    return session.dialogue_phase


def compute_coherence_score(session: Session) -> dict[str, float]:
    """Compute multi-dimensional coherence score for the session."""
    scores = {}

    # Topic coherence: how consistent is the topic flow?
    topic_changes = sum(
        1
        for i in range(1, len(session.topic_state.topic_history))
        if session.topic_state.topic_history[i] != session.topic_state.topic_history[i - 1]
    )
    topic_total = max(len(session.topic_state.topic_history), 1)
    scores["topic_coherence"] = round(1.0 - (topic_changes / max(topic_total, 1)) * 0.5, 3)

    # Memory coherence: ratio of memories that are accessible and recent
    if session.long_term_memories:
        recent = 0
        now = utc_now()
        for memory in session.long_term_memories:
            try:
                age_seconds = (now - parse_timestamp(memory.timestamp)).total_seconds()
                if age_seconds < 7200:
                    recent += 1
            except (ValueError, TypeError):
                continue
        scores["memory_coherence"] = round(recent / len(session.long_term_memories), 3)
    else:
        scores["memory_coherence"] = 0.5  # baseline

    # Contradiction coherence: fewer contradictions = better
    if session.turn_count > 0:
        contradiction_rate = len(session.contradiction_log) / session.turn_count
        scores["belief_coherence"] = round(max(0.0, 1.0 - contradiction_rate * 2.0), 3)
    else:
        scores["belief_coherence"] = 1.0

    # Profile stability: how much has the user profile changed?
    if len(session.user_profile_history) >= 2:
        last = session.user_profile_history[-1]
        prev = session.user_profile_history[-2]
        drift = (
            abs(last.openness - prev.openness)
            + abs(last.conscientiousness - prev.conscientiousness)
            + abs(last.extraversion - prev.extraversion)
            + abs(last.agreeableness - prev.agreeableness)
            + abs(last.neuroticism - prev.neuroticism)
        ) / 5.0
        scores["profile_stability"] = round(max(0.0, 1.0 - drift * 5.0), 3)
    else:
        scores["profile_stability"] = 0.8

    # Overall
    weights = {
        "topic_coherence": 0.3,
        "memory_coherence": 0.2,
        "belief_coherence": 0.3,
        "profile_stability": 0.2,
    }
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 3)

    return scores
