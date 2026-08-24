"""Unit tests for deterministic text-analysis behavior."""

import random

import pytest

from psych_coherence_mcp import (
    PERSONAS,
    analyze_big_five,
    assess_conversational_safety,
    compute_linguistic_features,
    detect_needs,
    detect_triggers,
    extract_memory_candidates,
    humanize_text,
    tokenize,
)


def test_tokenizer_and_empty_features_are_total() -> None:
    assert tokenize("  Hello, café!  ") == ["hello", "café"]
    features = compute_linguistic_features("")
    assert features.word_count == 0
    assert features.sentence_count == 1
    assert features.avg_sentence_length == 0


def test_uppercase_ratio_ignores_sentence_initials() -> None:
    ordinary = compute_linguistic_features("This is normal. Another sentence follows.")
    shouting = compute_linguistic_features("This is VERY LOUD.")
    assert ordinary.uppercase_ratio == 0
    assert shouting.uppercase_ratio > 0.5


def test_need_and_trigger_detection_use_phrase_boundaries() -> None:
    assert "autonomy" not in detect_needs("I feel down today", tokenize("I feel down today"))
    assert "time_pressure" not in detect_triggers("I have a crush on them")
    assert "information" in detect_needs("How does this work?", tokenize("How does this work?"))
    assert "time_pressure" in detect_triggers("The deadline is tomorrow")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nothing dangerous here.", "none"),
        ("I want to kill myself.", "moderate"),
        ("I want to kill myself tonight and I have a plan.", "imminent"),
        ("I have thoughts of suicide, but I am safe now and have no plan.", "low"),
    ],
)
def test_safety_levels(text: str, expected: str) -> None:
    assert assess_conversational_safety(text)["risk_level"] == expected


def test_safety_content_is_not_extracted_as_memory() -> None:
    assert extract_memory_candidates("I want to kill myself tonight.") == []
    candidates = extract_memory_candidates(
        "My favorite color is blue. I'm working on a dashboard. My goal is to launch."
    )
    assert {candidate["tags"][0] for candidate in candidates} >= {
        "preference",
        "project",
        "goal",
    }


def test_conflicting_personality_signals_reduce_confidence() -> None:
    mixed = "Organized but spontaneous, confident but insecure, social but alone."
    features = compute_linguistic_features(mixed)
    profile = analyze_big_five(tokenize(mixed), features)
    assert 0 <= profile.confidence < 0.9
    assert all(
        0 <= value <= 1
        for value in (
            profile.openness,
            profile.conscientiousness,
            profile.extraversion,
            profile.agreeableness,
            profile.neuroticism,
        )
    )


def test_humanization_handles_punctuation_only_text() -> None:
    random.seed(1)
    result = humanize_text(".", PERSONAS["engineer_kai"], disfluency_level=1)
    assert result["humanized_text"] == "."
    assert result["prosody_hints"]
