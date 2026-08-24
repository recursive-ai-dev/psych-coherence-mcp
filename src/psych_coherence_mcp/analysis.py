"""Rule-based linguistic, psychological, safety, and memory analysis."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from .constants import (
    BIG_FIVE_LEXICON,
    DIRECTNESS_MARKERS,
    EMOTION_LEXICON,
    FIRST_PERSON_PRONOUNS,
    FORMALITY_MARKERS,
    HEDGE_WORDS,
    INTENSIFIER_WORDS,
    TOKEN_CLEANUP_RE,
)
from .models import LinguisticFeatures, MoodState, PersonalityProfile


def tokenize(text: str) -> list[str]:
    """Simple but effective tokenizer: split on whitespace, strip punctuation from tokens."""
    raw = text.split()
    tokens = []
    for t in raw:
        cleaned = TOKEN_CLEANUP_RE.sub("", t.lower())
        if cleaned:
            tokens.append(cleaned)
    return tokens


def extract_sentences(text: str) -> list[str]:
    """Split text into sentences using regex for sentence-ending punctuation."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def compute_linguistic_features(text: str) -> LinguisticFeatures:
    """Extract linguistic features from raw text."""
    words = tokenize(text)
    sentences = extract_sentences(text)
    word_count = len(words)
    sentence_count = max(len(sentences), 1)

    # Type-token ratio (vocabulary richness)
    unique_words = set(words)
    ttr = len(unique_words) / max(word_count, 1)

    # Question and exclamation counts
    question_count = text.count("?")
    exclamation_count = text.count("!")

    # Uppercase ratio, excluding the first alphabetic character of each sentence.
    non_initial_text = []
    for sentence in sentences:
        skipped_initial = False
        for char in sentence:
            if char.isalpha() and not skipped_initial:
                skipped_initial = True
                continue
            non_initial_text.append(char)
    alpha_chars = [c for c in non_initial_text if c.isalpha()]
    upper_chars = [c for c in alpha_chars if c.isupper()]
    uppercase_ratio = len(upper_chars) / max(len(alpha_chars), 1)

    # Punctuation density
    punct_chars = [c for c in text if c in ".,;:!?—-()[]{}\"'"]
    punctuation_density = len(punct_chars) / max(word_count, 1)

    # Average word length
    avg_word_length = sum(len(w) for w in words) / max(word_count, 1)

    # First person pronouns ratio
    fp_count = sum(1 for w in words if w in FIRST_PERSON_PRONOUNS)
    first_person_ratio = fp_count / max(word_count, 1)

    # Hedge words and intensifiers
    hedge_count = sum(1 for w in words if w in HEDGE_WORDS)
    intensifier_count = sum(1 for w in words if w in INTENSIFIER_WORDS)

    return LinguisticFeatures(
        word_count=word_count,
        sentence_count=sentence_count,
        avg_sentence_length=word_count / sentence_count,
        vocabulary_richness=round(ttr, 4),
        question_count=question_count,
        exclamation_count=exclamation_count,
        uppercase_ratio=round(uppercase_ratio, 4),
        punctuation_density=round(punctuation_density, 4),
        avg_word_length=round(avg_word_length, 2),
        first_person_ratio=round(first_person_ratio, 4),
        hedge_count=hedge_count,
        intensifier_count=intensifier_count,
    )


def analyze_emotions(
    text: str, words: list[str]
) -> tuple[str, float, dict[str, float], float, float]:
    """
    Weighted emotion analysis using the emotion lexicon.
    Returns: (primary_emotion, intensity, all_scores, valence, arousal)
    """
    emotion_accum: dict[str, float] = defaultdict(float)

    for word in words:
        if word in EMOTION_LEXICON:
            for emotion, weight in EMOTION_LEXICON[word]:
                emotion_accum[emotion] += weight

    # Check for negation patterns that flip valence
    negation_words = {
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "nobody",
        "nothing",
        "nowhere",
        "hardly",
        "barely",
        "scarcely",
        "don't",
        "doesn't",
        "didn't",
        "won't",
        "wouldn't",
        "couldn't",
        "shouldn't",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "can't",
        "cannot",
    }
    text.lower()
    negation_count = sum(1 for w in words if w in negation_words)

    if not emotion_accum:
        return "neutral", 0.0, {}, 0.0, 0.2

    # Normalize scores
    max_score = max(emotion_accum.values())
    normalized = {e: round(s / max(max_score, 1.0), 3) for e, s in emotion_accum.items()}

    # Primary emotion
    primary = max(emotion_accum, key=lambda emotion: emotion_accum[emotion])

    # Intensity (sigmoid-scaled from raw score)
    raw_intensity = emotion_accum[primary]
    intensity = round(min(1.0, 2.0 / (1.0 + math.exp(-0.5 * raw_intensity)) - 1.0), 3)

    # Valence calculation
    positive_emotions = {"joy", "excitement", "affection", "gratitude", "trust", "surprise"}
    negative_emotions = {
        "sadness",
        "anger",
        "fear",
        "anxiety",
        "frustration",
        "disgust",
        "contempt",
        "confusion",
    }
    pos_sum = sum(emotion_accum.get(e, 0) for e in positive_emotions)
    neg_sum = sum(emotion_accum.get(e, 0) for e in negative_emotions)
    total = pos_sum + neg_sum
    valence = round((pos_sum - neg_sum) / max(total, 0.01), 3)

    # If heavy negation, dampen or flip valence
    if negation_count >= 2:
        valence *= -0.5

    # Arousal: high-arousal emotions vs low-arousal
    high_arousal = {"excitement", "anger", "fear", "anxiety", "frustration", "surprise"}
    low_arousal = {"sadness", "trust", "neutral", "gratitude"}
    ha_sum = sum(emotion_accum.get(e, 0) for e in high_arousal)
    la_sum = sum(emotion_accum.get(e, 0) for e in low_arousal)
    arousal = round(ha_sum / max(ha_sum + la_sum, 0.01), 3)

    return primary, intensity, normalized, valence, arousal


def analyze_big_five(words: list[str], linguistic: LinguisticFeatures) -> PersonalityProfile:
    """
    Weighted Big Five personality analysis from lexical cues and linguistic features.
    Uses directional scoring with Bayesian-like shrinkage toward the prior (0.5).
    """
    traits: dict[str, float] = {}
    evidence_by_trait: dict[str, tuple[float, float]] = {}

    for trait_name, directions in BIG_FIVE_LEXICON.items():
        high_score = 0.0
        low_score = 0.0

        for word in words:
            for indicator_word, weight in directions.get("high", []):
                if word == indicator_word or (len(indicator_word) > 4 and indicator_word in word):
                    high_score += weight
            for indicator_word, weight in directions.get("low", []):
                if word == indicator_word or (len(indicator_word) > 4 and indicator_word in word):
                    low_score += weight

        total_evidence = high_score + low_score
        evidence_by_trait[trait_name] = (high_score, low_score)
        if total_evidence < 0.01:
            traits[trait_name] = 0.5
        else:
            raw = high_score / total_evidence
            # Shrink toward the neutral prior when evidence is sparse.
            shrinkage = max(0.1, 1.0 - min(total_evidence / 5.0, 0.9))
            traits[trait_name] = round(0.5 * shrinkage + raw * (1.0 - shrinkage), 4)

    # Supplement with linguistic feature heuristics
    # High question count → higher openness
    if linguistic.question_count >= 2:
        traits["openness"] = min(1.0, traits["openness"] + 0.05)
    # Long average sentence → higher conscientiousness
    if linguistic.avg_sentence_length > 15:
        traits["conscientiousness"] = min(1.0, traits["conscientiousness"] + 0.04)
    # High exclamation count → higher extraversion
    if linguistic.exclamation_count >= 2:
        traits["extraversion"] = min(1.0, traits["extraversion"] + 0.05)
    # High first-person ratio → higher neuroticism (self-focused)
    if linguistic.first_person_ratio > 0.1:
        traits["neuroticism"] = min(1.0, traits["neuroticism"] + 0.03)
    # High hedge count → higher agreeableness (hedging = social awareness)
    if linguistic.hedge_count >= 2:
        traits["agreeableness"] = min(1.0, traits["agreeableness"] + 0.04)

    # Confidence depends on observed trait evidence, not merely input length.
    # Opposing signals for the same trait reduce confidence instead of inflating it.
    evidence_total = sum(high + low for high, low in evidence_by_trait.values())
    conflicting_evidence = sum(2.0 * min(high, low) for high, low in evidence_by_trait.values())
    conflict_ratio = conflicting_evidence / max(evidence_total, 0.01)
    length_bonus = min(linguistic.word_count / 100.0, 0.2)
    evidence_bonus = min(evidence_total / 10.0, 0.55)
    raw_confidence = (0.15 + length_bonus + evidence_bonus) * (1.0 - 0.45 * conflict_ratio)
    confidence = round(max(0.1, min(raw_confidence, 0.95)), 3)

    return PersonalityProfile(
        openness=traits["openness"],
        conscientiousness=traits["conscientiousness"],
        extraversion=traits["extraversion"],
        agreeableness=traits["agreeableness"],
        neuroticism=traits["neuroticism"],
        confidence=confidence,
    )


def analyze_formality(words: list[str]) -> tuple[str, float]:
    """Analyze formality level. Returns (level, score 0-1 where 1=very formal)."""
    formal_score = 0.0
    informal_score = 0.0

    for word in words:
        for marker, weight in FORMALITY_MARKERS["formal"]:
            if word == marker:
                formal_score += weight
        for marker, weight in FORMALITY_MARKERS["informal"]:
            if word == marker:
                informal_score += weight

    total = formal_score + informal_score
    if total < 0.01:
        return "neutral", 0.5

    score = round(formal_score / total, 3)
    if score > 0.65:
        level = "formal"
    elif score < 0.35:
        level = "informal"
    else:
        level = "neutral"

    return level, score


def analyze_directness(words: list[str]) -> tuple[str, float]:
    """Analyze directness level. Returns (level, score 0-1 where 1=very direct)."""
    direct_score = 0.0
    indirect_score = 0.0

    for word in words:
        for marker, weight in DIRECTNESS_MARKERS["direct"]:
            if word == marker:
                direct_score += weight
        for marker, weight in DIRECTNESS_MARKERS["indirect"]:
            if word == marker:
                indirect_score += weight

    total = direct_score + indirect_score
    if total < 0.01:
        return "neutral", 0.5

    score = round(direct_score / total, 3)
    if score > 0.65:
        level = "direct"
    elif score < 0.35:
        level = "indirect"
    else:
        level = "neutral"

    return level, score


def detect_needs(text: str, words: list[str]) -> list[str]:
    """Detect communicative needs from text."""
    needs = []
    text_lower = text.lower()

    need_patterns = {
        "support": ["help", "support", "advice", "guidance", "assist", "struggling"],
        "information": [
            "what",
            "how",
            "why",
            "when",
            "where",
            "explain",
            "tell me",
            "know",
            "learn",
            "understand",
        ],
        "validation": [
            "right",
            "correct",
            "agree",
            "validate",
            "am i",
            "is this ok",
            "makes sense",
        ],
        "connection": ["feel", "lonely", "listen", "hear me", "understand me", "relate"],
        "reassurance": ["worried", "anxious", "scared", "afraid", "will it be", "going to be ok"],
        "autonomy": ["myself", "own", "independent", "my way", "my choice", "decide"],
        "challenge": ["push me", "honest", "truth", "don't sugarcoat", "real talk", "straight"],
    }

    for need, indicators in need_patterns.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(ind) + r"(?!\w)", text_lower) for ind in indicators
        ):
            needs.append(need)

    return needs


def detect_triggers(text: str) -> list[str]:
    """Detect potential emotional triggers in text."""
    triggers = []
    text_lower = text.lower()

    trigger_patterns = {
        "being_ignored": ["ignore", "dismiss", "don't care", "not listening", "invisible"],
        "time_pressure": ["rush", "hurry", "quick", "fast", "deadline", "running out"],
        "criticism": ["wrong", "stupid", "dumb", "idiot", "failure", "useless"],
        "abandonment": ["leave", "abandon", "alone", "left me", "gone", "nobody"],
        "injustice": ["unfair", "unjust", "wrong", "shouldn't", "not right"],
        "loss_of_control": ["helpless", "powerless", "trapped", "stuck", "no choice"],
        "shame": ["embarrassed", "ashamed", "humiliated", "pathetic", "worthless"],
    }

    for trigger, indicators in trigger_patterns.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(ind) + r"(?!\w)", text_lower) for ind in indicators
        ):
            triggers.append(trigger)

    return triggers


def extract_topics(text: str) -> list[str]:
    """Extract topic keywords from text using noun-phrase-like heuristics."""
    words = tokenize(text)
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "how",
        "why",
        "not",
        "no",
        "so",
        "if",
        "then",
        "than",
        "too",
        "very",
        "just",
        "about",
        "up",
        "out",
        "into",
        "over",
        "after",
        "before",
        "between",
        "under",
        "again",
        "there",
        "here",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "also",
        "back",
        "even",
        "still",
        "new",
        "now",
        "way",
        "because",
        "any",
        "am",
        "get",
        "got",
        "go",
        "going",
        "make",
        "like",
        "know",
        "think",
        "want",
        "need",
        "feel",
        "see",
        "say",
        "tell",
        "give",
        "take",
        "come",
        "use",
        "find",
        "let",
        "put",
        "thing",
        "much",
        "well",
        "really",
        "actually",
        "basically",
        "right",
        "ok",
        "yeah",
        "yes",
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank",
    }

    # Extract meaningful words (length > 2, not in stop words)
    meaningful = [w for w in words if len(w) > 2 and w not in stop_words]

    # Simple bigram extraction for compound topics
    bigrams = []
    for i in range(len(words) - 1):
        if (
            words[i] not in stop_words
            and words[i + 1] not in stop_words
            and len(words[i]) > 2
            and len(words[i + 1]) > 2
        ):
            bigrams.append(f"{words[i]} {words[i + 1]}")

    # Return top keywords (unigrams + bigrams)
    return (bigrams[:3] + meaningful[:5])[:6]


def assess_conversational_safety(text: str) -> dict[str, Any]:
    """Detect explicit safety signals and return conservative response guidance.

    This is a rule-based conversational triage aid, not a clinical assessment.
    It intentionally reports matched categories rather than echoing matched text.
    """
    lowered = text.lower()
    categories: list[str] = []
    signals: list[str] = []

    self_harm_patterns = [
        r"\bkill myself\b",
        r"\bend my (?:own )?life\b",
        r"\bhurt myself\b",
        r"\bself[- ]harm\b",
        r"\bsuicid(?:e|al)\b",
        r"\bdon'?t want to (?:be alive|live)\b",
        r"\bbetter off dead\b",
        r"\bno reason to live\b",
    ]
    violence_patterns = [
        r"\b(?:kill|murder|shoot|stab|hurt) (?:him|her|them|someone|people)\b",
        r"\b(?:they|he|she) (?:deserve|needs?) to die\b",
    ]
    immediacy_patterns = [
        r"\bright now\b",
        r"\btonight\b",
        r"\btoday\b",
        r"\bthis (?:minute|hour|evening)\b",
        r"\babout to\b",
        r"\bcan'?t stop myself\b",
    ]
    planning_patterns = [
        r"\b(?:have|made|making) (?:a )?plan\b",
        r"\bplanned (?:it|this|everything)\b",
        r"\bwrote (?:a|my) (?:note|goodbye)\b",
        r"\bknow how (?:i(?:'m| am) going to|to do it)\b",
        r"\baccess to (?:a )?(?:gun|weapon|pills?)\b",
    ]
    protective_patterns = [
        r"\bnot (?:going to|planning to|about to) (?:hurt|kill) myself\b",
        r"\b(?:am|i'm) safe (?:right now|now)\b",
        r"\bno (?:plan|intent)\b",
    ]

    self_harm = any(re.search(pattern, lowered) for pattern in self_harm_patterns)
    violence = any(re.search(pattern, lowered) for pattern in violence_patterns)
    immediate = any(re.search(pattern, lowered) for pattern in immediacy_patterns)
    planning = any(re.search(pattern, lowered) for pattern in planning_patterns)
    protective = any(re.search(pattern, lowered) for pattern in protective_patterns)

    if self_harm:
        categories.append("self_harm_or_suicide")
        signals.append("explicit_self_harm_language")
    if violence:
        categories.append("harm_to_others")
        signals.append("explicit_violence_language")
    if immediate:
        signals.append("time_immediacy")
    if planning:
        signals.append("planning_or_means")
    if protective:
        signals.append("stated_protective_context")

    if (self_harm or violence) and immediate and planning and not protective:
        level = "imminent"
    elif (self_harm or violence) and (immediate or planning) and not protective:
        level = "high"
    elif self_harm or violence:
        level = "moderate" if not protective else "low"
    else:
        level = "none"

    if level in {"high", "imminent"}:
        directives = [
            "Prioritize immediate safety over persona style or the original task.",
            "Respond calmly and directly; ask whether the person is in immediate danger.",
            "Encourage contacting local emergency services or a crisis line and a trusted nearby person.",
            "Do not leave the person alone with only generic reassurance; keep the exchange focused on the next safe step.",
        ]
    elif level in {"low", "moderate"}:
        directives = [
            "Acknowledge the distress without judgment or dramatization.",
            "Ask a brief, direct safety check about current intent, plan, and immediate safety.",
            "Encourage support from a trusted person or qualified local professional.",
        ]
    else:
        directives = []

    return {
        "risk_level": level,
        "categories": categories,
        "signals": signals,
        "response_directives": directives,
        "requires_safety_first_response": level in {"high", "imminent"},
        "disclaimer": "Rule-based conversational signal detection; not a diagnosis or substitute for professional assessment.",
    }


def extract_memory_candidates(text: str) -> list[dict[str, Any]]:
    """Extract conservative, user-reviewable long-term memory candidates."""
    # Never turn acute harm language into an ordinary goal/preference memory.
    if assess_conversational_safety(text)["risk_level"] != "none":
        return []
    candidates: list[dict[str, Any]] = []
    patterns = [
        ("semantic", "preference", r"\bmy favou?rite ([^.!?]{1,40}?) is ([^.!?]{1,100})"),
        ("semantic", "preference", r"\bi (?:prefer|enjoy|love) ([^.!?]{2,120})"),
        ("semantic", "identity", r"\bi(?:'m| am) (?:a|an) ([^.!?]{2,100})"),
        ("episodic", "project", r"\bi(?:'m| am) (?:working on|building|writing) ([^.!?]{2,160})"),
        ("semantic", "goal", r"\bmy goal is (?:to )?([^.!?]{2,160})"),
        ("semantic", "goal", r"\bi want to ([^.!?]{2,160})"),
    ]
    seen = set()
    for memory_type, tag, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            content = match.group(0).strip(" ,")
            key = content.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "content": content,
                    "memory_type": memory_type,
                    "importance": 0.65 if tag in {"goal", "project"} else 0.5,
                    "tags": [tag, *extract_topics(content)[:2]],
                    "source_span": [match.start(), match.end()],
                }
            )
            if len(candidates) >= 10:
                return candidates
    return candidates


def full_analysis(text: str) -> dict[str, Any]:
    """Run the complete psychological analysis pipeline on a text."""
    words = tokenize(text)
    linguistic = compute_linguistic_features(text)
    primary_emotion, intensity, emotion_scores, valence, arousal = analyze_emotions(text, words)
    personality = analyze_big_five(words, linguistic)
    formality_level, formality_score = analyze_formality(words)
    directness_level, directness_score = analyze_directness(words)
    needs = detect_needs(text, words)
    triggers = detect_triggers(text)
    topics = extract_topics(text)

    mood = MoodState(
        primary_emotion=primary_emotion,
        emotion_intensity=intensity,
        secondary_emotions=emotion_scores,
        valence=valence,
        arousal=arousal,
        formality_level=formality_level,
        formality_score=formality_score,
        directness_level=directness_level,
        directness_score=directness_score,
        detected_needs=needs,
        potential_triggers=triggers,
    )

    return {
        "personality_profile": personality.to_dict(),
        "mood_state": mood.to_dict(),
        "linguistic_features": linguistic.to_dict(),
        "topics": topics,
        "safety_assessment": assess_conversational_safety(text),
        "memory_candidates": extract_memory_candidates(text),
    }
