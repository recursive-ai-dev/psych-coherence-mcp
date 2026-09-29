"""Shared topic bounds for live state and explicit legacy snapshot repair."""

from __future__ import annotations

import hashlib

from .constants import MAX_TOPIC_HISTORY, MAX_TOPIC_KEYWORDS, MAX_TOPIC_LABEL_LENGTH
from .models import TopicState


def bound_topic_label(label: str) -> str:
    """Bound labels while distinguishing long tokens with a common prefix."""
    if len(label) <= MAX_TOPIC_LABEL_LENGTH:
        return label
    suffix = hashlib.sha256(label.encode()).hexdigest()[:16]
    return label[: MAX_TOPIC_LABEL_LENGTH - 17] + "-" + suffix


def prune_topic_keywords(state: TopicState) -> None:
    """Evict oldest associations, preserving the current topic."""
    for key in list(state.topic_keywords):
        if len(state.topic_keywords) <= MAX_TOPIC_HISTORY:
            break
        if key != state.current_topic:
            del state.topic_keywords[key]


def repair_topic_state(state: TopicState) -> TopicState:
    """Normalize previously exported oversized state without mutating its input."""
    repaired = TopicState(
        current_topic=bound_topic_label(state.current_topic),
        topic_history=[bound_topic_label(t) for t in state.topic_history[-MAX_TOPIC_HISTORY:]],
        topic_confidence=state.topic_confidence,
        transition_type=state.transition_type,
        topic_keywords={
            bound_topic_label(key): [bound_topic_label(t) for t in values[:MAX_TOPIC_KEYWORDS]]
            for key, values in state.topic_keywords.items()
        },
    )
    prune_topic_keywords(repaired)
    return repaired
