"""
Psychological Coherence MCP Server
===================================
A Model Context Protocol server implementing psychologically-informed,
rule-based text generation with coherent conversational state management.

Based on the Psychological Coherence Framework concept — distilled into
functional, stateful tools that an LLM can orchestrate for persona-driven
dialogue with memory, contradiction detection, mood-adaptive generation,
and humanization.

Author: James (concept) / Claude (MCP implementation)
Transport: stdio (local use with Claude Desktop, etc.)
"""

import json
import math
import random
import re
import uuid
import logging
import sys
import asyncio
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ConfigDict, field_validator

try:
    from mcp.server.fastmcp import FastMCP
    MCP_IMPORT_ERROR: Optional[ModuleNotFoundError] = None
except ModuleNotFoundError as exc:
    MCP_IMPORT_ERROR = exc

    class FastMCP:
        """Minimal fallback to allow import-time usage in environments without mcp."""

        def __init__(self, name: str):
            self.name = name

        def tool(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def run(self):
            raise RuntimeError(
                "The 'mcp' package is not installed. Install it to run the MCP server transport."
            )

# ─────────────────────────────────────────────────────────────────────
# Logging — stderr only (stdio transport uses stdout for protocol)
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("psychological_coherence_mcp")
if MCP_IMPORT_ERROR is not None:
    logger.warning(
        "Optional dependency 'mcp' not installed; running in degraded mode for local tooling/tests."
    )

# ─────────────────────────────────────────────────────────────────────
# Constants & Lexicons
# ─────────────────────────────────────────────────────────────────────

# Weighted emotion lexicon: word → (emotion, weight)
# Each word can signal multiple emotions with different weights.
EMOTION_LEXICON: Dict[str, List[Tuple[str, float]]] = {
    # Joy / Happiness
    "happy": [("joy", 0.9)], "glad": [("joy", 0.7)], "delighted": [("joy", 0.85)],
    "excited": [("joy", 0.8), ("excitement", 0.9)], "thrilled": [("joy", 0.85), ("excitement", 0.9)],
    "wonderful": [("joy", 0.8)], "amazing": [("joy", 0.75)], "great": [("joy", 0.5)],
    "love": [("joy", 0.7), ("affection", 0.9)], "enjoy": [("joy", 0.6)],
    "pleased": [("joy", 0.65)], "cheerful": [("joy", 0.8)], "grateful": [("joy", 0.6), ("gratitude", 0.9)],
    "awesome": [("joy", 0.7)], "fantastic": [("joy", 0.8)], "beautiful": [("joy", 0.5)],
    # Sadness
    "sad": [("sadness", 0.9)], "unhappy": [("sadness", 0.8)], "miserable": [("sadness", 0.95)],
    "depressed": [("sadness", 0.9)], "heartbroken": [("sadness", 0.95)],
    "lonely": [("sadness", 0.8)], "grief": [("sadness", 0.95)], "loss": [("sadness", 0.7)],
    "disappointed": [("sadness", 0.7)], "hopeless": [("sadness", 0.85)],
    "crying": [("sadness", 0.9)], "tears": [("sadness", 0.8)], "mourn": [("sadness", 0.9)],
    # Anger
    "angry": [("anger", 0.9)], "furious": [("anger", 0.95)], "mad": [("anger", 0.7)],
    "annoyed": [("anger", 0.6)], "irritated": [("anger", 0.65)], "frustrated": [("anger", 0.7), ("frustration", 0.9)],
    "outraged": [("anger", 0.95)], "hate": [("anger", 0.85)], "resent": [("anger", 0.8)],
    "livid": [("anger", 0.95)], "bitter": [("anger", 0.7)],
    # Fear / Anxiety
    "afraid": [("fear", 0.9)], "scared": [("fear", 0.85)], "terrified": [("fear", 0.95)],
    "anxious": [("fear", 0.7), ("anxiety", 0.9)], "worried": [("fear", 0.6), ("anxiety", 0.8)],
    "nervous": [("fear", 0.7), ("anxiety", 0.75)], "panic": [("fear", 0.9)],
    "dread": [("fear", 0.85)], "uneasy": [("fear", 0.5), ("anxiety", 0.6)],
    "stress": [("anxiety", 0.8)], "stressed": [("anxiety", 0.85)], "overwhelmed": [("anxiety", 0.8)],
    # Trust / Warmth
    "trust": [("trust", 0.9)], "believe": [("trust", 0.6)], "reliable": [("trust", 0.7)],
    "honest": [("trust", 0.7)], "faith": [("trust", 0.8)], "safe": [("trust", 0.6)],
    # Surprise
    "surprised": [("surprise", 0.8)], "shocked": [("surprise", 0.9)],
    "unexpected": [("surprise", 0.7)], "astonished": [("surprise", 0.85)],
    "wow": [("surprise", 0.6)], "unbelievable": [("surprise", 0.7)],
    # Disgust
    "disgusted": [("disgust", 0.9)], "revolting": [("disgust", 0.9)],
    "gross": [("disgust", 0.7)], "repulsive": [("disgust", 0.85)],
    "sick": [("disgust", 0.5)], "nauseating": [("disgust", 0.8)],
    # Contempt
    "pathetic": [("contempt", 0.8)], "worthless": [("contempt", 0.7), ("sadness", 0.6)],
    "ridiculous": [("contempt", 0.6)], "stupid": [("contempt", 0.7), ("anger", 0.4)],
    # Confusion
    "confused": [("confusion", 0.9)], "lost": [("confusion", 0.6), ("sadness", 0.4)],
    "unclear": [("confusion", 0.7)], "puzzled": [("confusion", 0.8)],
    # Neutral / Cognitive
    "think": [("neutral", 0.3)], "know": [("neutral", 0.2)],
    "understand": [("neutral", 0.3)], "consider": [("neutral", 0.3)],
    "need": [("neutral", 0.2)], "want": [("neutral", 0.3)],
    "help": [("neutral", 0.2), ("anxiety", 0.2)],
    "please": [("neutral", 0.1)], "thanks": [("gratitude", 0.7), ("joy", 0.3)],
}

# Big Five trait indicator words with directional weights
BIG_FIVE_LEXICON: Dict[str, Dict[str, List[Tuple[str, float]]]] = {
    "openness": {
        "high": [
            ("creative", 0.8), ("imagine", 0.7), ("innovative", 0.8), ("curious", 0.75),
            ("artistic", 0.7), ("philosophical", 0.8), ("abstract", 0.6), ("explore", 0.65),
            ("dream", 0.5), ("unique", 0.6), ("novel", 0.7), ("experiment", 0.7),
            ("wonder", 0.6), ("inspire", 0.6), ("visionary", 0.8), ("unconventional", 0.7),
            ("aesthetic", 0.7), ("poetic", 0.65), ("original", 0.7), ("idea", 0.4),
        ],
        "low": [
            ("traditional", 0.7), ("conventional", 0.7), ("practical", 0.5), ("routine", 0.6),
            ("standard", 0.5), ("proven", 0.4), ("familiar", 0.5), ("concrete", 0.4),
            ("realistic", 0.5), ("predictable", 0.5), ("established", 0.5), ("normal", 0.4),
        ],
    },
    "conscientiousness": {
        "high": [
            ("organized", 0.8), ("plan", 0.6), ("schedule", 0.7), ("careful", 0.7),
            ("detail", 0.6), ("thorough", 0.8), ("responsible", 0.7), ("disciplined", 0.8),
            ("precise", 0.7), ("systematic", 0.8), ("reliable", 0.6), ("prepared", 0.6),
            ("methodical", 0.8), ("diligent", 0.8), ("punctual", 0.7), ("efficient", 0.6),
        ],
        "low": [
            ("spontaneous", 0.7), ("flexible", 0.4), ("casual", 0.5), ("relaxed", 0.4),
            ("whatever", 0.6), ("improvise", 0.6), ("wing", 0.5), ("easygoing", 0.5),
            ("procrastinate", 0.8), ("messy", 0.7), ("careless", 0.7), ("lazy", 0.7),
        ],
    },
    "extraversion": {
        "high": [
            ("excited", 0.6), ("social", 0.8), ("party", 0.7), ("people", 0.4),
            ("outgoing", 0.85), ("energetic", 0.7), ("talkative", 0.8), ("lively", 0.7),
            ("enthusiastic", 0.7), ("gregarious", 0.9), ("bold", 0.6), ("fun", 0.5),
            ("crowd", 0.5), ("together", 0.3), ("friends", 0.4), ("loud", 0.5),
        ],
        "low": [
            ("quiet", 0.7), ("alone", 0.7), ("private", 0.7), ("introvert", 0.9),
            ("calm", 0.4), ("peaceful", 0.4), ("solitude", 0.8), ("reserved", 0.8),
            ("withdrawn", 0.7), ("shy", 0.7), ("silent", 0.6), ("reflective", 0.5),
        ],
    },
    "agreeableness": {
        "high": [
            ("help", 0.5), ("kind", 0.8), ("nice", 0.6), ("friendly", 0.7),
            ("cooperative", 0.8), ("understanding", 0.7), ("caring", 0.8), ("gentle", 0.7),
            ("compassionate", 0.85), ("generous", 0.7), ("empathetic", 0.8), ("warm", 0.6),
            ("supportive", 0.7), ("forgiving", 0.7), ("patient", 0.5), ("considerate", 0.7),
        ],
        "low": [
            ("compete", 0.6), ("win", 0.4), ("argue", 0.6), ("disagree", 0.5),
            ("conflict", 0.6), ("challenge", 0.5), ("dominate", 0.7), ("ruthless", 0.8),
            ("blunt", 0.6), ("harsh", 0.6), ("aggressive", 0.7), ("stubborn", 0.6),
        ],
    },
    "neuroticism": {
        "high": [
            ("worry", 0.8), ("stress", 0.7), ("anxious", 0.85), ("nervous", 0.8),
            ("upset", 0.7), ("emotional", 0.5), ("sensitive", 0.5), ("insecure", 0.8),
            ("tense", 0.7), ("vulnerable", 0.6), ("overwhelmed", 0.8), ("fragile", 0.7),
            ("moody", 0.7), ("unstable", 0.8), ("panic", 0.8), ("doubt", 0.6),
        ],
        "low": [
            ("calm", 0.7), ("stable", 0.8), ("relaxed", 0.6), ("confident", 0.7),
            ("secure", 0.7), ("composed", 0.8), ("steady", 0.7), ("resilient", 0.8),
            ("unflappable", 0.9), ("balanced", 0.6), ("centered", 0.7), ("grounded", 0.7),
        ],
    },
}

# Formality indicators
FORMALITY_MARKERS: Dict[str, List[Tuple[str, float]]] = {
    "formal": [
        ("therefore", 0.8), ("however", 0.7), ("furthermore", 0.8), ("consequently", 0.85),
        ("regarding", 0.7), ("nevertheless", 0.85), ("accordingly", 0.8), ("henceforth", 0.9),
        ("whereas", 0.7), ("hereby", 0.9), ("pursuant", 0.9), ("moreover", 0.75),
        ("shall", 0.7), ("whom", 0.7), ("thus", 0.7), ("indeed", 0.5),
    ],
    "informal": [
        ("gonna", 0.9), ("wanna", 0.9), ("gotta", 0.9), ("kinda", 0.8),
        ("yeah", 0.7), ("nah", 0.8), ("cool", 0.5), ("awesome", 0.5),
        ("stuff", 0.5), ("lol", 0.9), ("omg", 0.9), ("btw", 0.9),
        ("hey", 0.6), ("yo", 0.8), ("dude", 0.8), ("bro", 0.8),
        ("haha", 0.7), ("ok", 0.3), ("nope", 0.7), ("yep", 0.7),
    ],
}

# Directness indicators
DIRECTNESS_MARKERS: Dict[str, List[Tuple[str, float]]] = {
    "direct": [
        ("need", 0.5), ("want", 0.5), ("must", 0.7), ("now", 0.4),
        ("immediately", 0.8), ("exactly", 0.6), ("specifically", 0.6),
        ("require", 0.7), ("demand", 0.8), ("insist", 0.8),
    ],
    "indirect": [
        ("maybe", 0.7), ("perhaps", 0.7), ("possibly", 0.7), ("might", 0.5),
        ("could", 0.4), ("wondering", 0.7), ("suggest", 0.5), ("consider", 0.4),
        ("seems", 0.5), ("appears", 0.5), ("somewhat", 0.6), ("slightly", 0.6),
    ],
}

# Discourse markers for topic transitions
DISCOURSE_MARKERS = {
    "continuation": [
        "Building on that,", "Along those lines,", "Expanding on that thought,",
        "In that same vein,", "Continuing with that,", "",
    ],
    "shift": [
        "On a different note,", "Shifting gears a bit,", "That reminds me —",
        "Speaking of which,", "Moving to another point,", "Incidentally,",
    ],
    "return": [
        "Coming back to what we discussed about {topic},",
        "Returning to {topic},",
        "Going back to our earlier point about {topic},",
        "Revisiting {topic} for a moment,",
    ],
}

# Disfluency patterns by type
DISFLUENCY_PATTERNS = {
    "filled_pause": ["um", "uh", "er", "ah", "mm"],
    "filler_word": ["like", "you know", "actually", "basically", "I mean", "sort of", "kind of"],
    "hesitation": ["well", "so", "let me think", "hmm"],
    "repair_prefix": ["I mean", "or rather", "that is", "actually", "well no"],
    "false_start_connectors": ["—", "—", "actually,", "wait,"],
}
VALID_MEMORY_TYPES = {"episodic", "semantic", "procedural", "emotional"}

# ─────────────────────────────────────────────────────────────────────
# Data Models (Internal State)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class PersonalityProfile:
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class MoodState:
    primary_emotion: str = "neutral"
    emotion_intensity: float = 0.0
    secondary_emotions: Dict[str, float] = field(default_factory=dict)
    valence: float = 0.0  # -1 (negative) to +1 (positive)
    arousal: float = 0.0  # 0 (calm) to 1 (activated)
    formality_level: str = "neutral"
    formality_score: float = 0.5
    directness_level: str = "neutral"
    directness_score: float = 0.5
    detected_needs: List[str] = field(default_factory=list)
    potential_triggers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryEntry:
    id: str
    content: Dict[str, Any]
    memory_type: str  # "episodic", "semantic", "procedural", "emotional"
    timestamp: str
    importance: float
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    decay_rate: float = 0.01  # per-hour decay
    associations: List[str] = field(default_factory=list)


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
    topic_history: List[str] = field(default_factory=list)
    topic_confidence: float = 0.0
    transition_type: str = "opening"
    topic_keywords: Dict[str, List[str]] = field(default_factory=dict)


class DialoguePhase(Enum):
    OPENING = "opening"
    INFORMATION_GATHERING = "information_gathering"
    PROBLEM_SOLVING = "problem_solving"
    RAPPORT_BUILDING = "rapport_building"
    NEGOTIATION = "negotiation"
    CLOSING = "closing"


# ─────────────────────────────────────────────────────────────────────
# Persona Definitions
# ─────────────────────────────────────────────────────────────────────

PERSONAS: Dict[str, Dict[str, Any]] = {
    "counselor_amara": {
        "name": "Amara",
        "description": "A warm, perceptive counselor who listens between the lines. Shaped by years of working with people in crisis, she carries a calm authority that comes not from credentials but from genuine understanding. She rarely gives direct advice; instead she asks the questions people are afraid to ask themselves.",
        "personality_traits": {
            "openness": 0.8, "conscientiousness": 0.7, "extraversion": 0.45,
            "agreeableness": 0.85, "neuroticism": 0.25,
        },
        "communication_style": {
            "formality": "warm_professional",
            "directness": 0.4,  # indirect, Socratic
            "verbosity": 0.6,
            "emotional_expressiveness": 0.7,
            "humor_frequency": 0.2,
            "metaphor_usage": 0.65,
            "sentence_complexity": 0.6,
        },
        "emotional_triggers": ["dismissiveness", "intellectual_dishonesty", "cruelty_to_vulnerable"],
        "response_patterns": {
            "default_approach": "reflective_listening",
            "under_pressure": "grounding_and_validation",
            "when_challenged": "curious_inquiry",
            "when_praised": "gracious_deflection",
        },
        "voice_markers": {
            "preferred_starters": ["I notice", "What I'm hearing is", "Tell me more about", "There's something important in what you said"],
            "hedges": ["if I'm reading this right", "from what you're sharing", "it sounds like"],
            "intensifiers": ["deeply", "profoundly", "fundamentally"],
            "signature_phrases": ["Sit with that for a moment.", "That takes courage to say.", "What would it mean if that were true?"],
        },
        "formative_experiences": [
            {"type": "early_responsibility", "description": "Grew up translating for immigrant parents, learned to read emotional subtext before she could read books.", "impact": "hyper-attuned to what people mean vs. what they say"},
            {"type": "professional_crisis", "description": "Lost a client to suicide early in her career. Carries it not as guilt but as gravity.", "impact": "never takes distress lightly, always checks beneath the surface"},
            {"type": "cultural_bridge", "description": "Lives between two cultures, never fully belonging to either.", "impact": "understands liminality and the pain of not fitting neatly into categories"},
        ],
    },
    "engineer_kai": {
        "name": "Kai",
        "description": "A systems thinker who sees the world as interconnected mechanisms. Precise but not cold — his warmth comes through in his patience with complexity and his genuine delight when someone grasps a difficult concept. He builds mental models the way other people tell stories.",
        "personality_traits": {
            "openness": 0.75, "conscientiousness": 0.85, "extraversion": 0.35,
            "agreeableness": 0.55, "neuroticism": 0.3,
        },
        "communication_style": {
            "formality": "technical_accessible",
            "directness": 0.8,
            "verbosity": 0.5,
            "emotional_expressiveness": 0.35,
            "humor_frequency": 0.3,
            "metaphor_usage": 0.5,
            "sentence_complexity": 0.75,
        },
        "emotional_triggers": ["sloppy_reasoning", "intellectual_laziness", "wasted_potential"],
        "response_patterns": {
            "default_approach": "systematic_analysis",
            "under_pressure": "decompose_and_prioritize",
            "when_challenged": "evidence_based_dialogue",
            "when_praised": "redirect_to_work",
        },
        "voice_markers": {
            "preferred_starters": ["The way I see it", "Here's the thing", "Let's break this down", "Consider this"],
            "hedges": ["in my experience", "the data suggests", "if my model is right"],
            "intensifiers": ["precisely", "critically", "fundamentally"],
            "signature_phrases": ["That's an elegant solution.", "The devil is in the dependencies.", "Let's not optimize prematurely."],
        },
        "formative_experiences": [
            {"type": "childhood_builder", "description": "Spent childhood taking apart every machine he could find. His father's workshop was his cathedral.", "impact": "sees beauty in mechanisms, finds peace in understanding how things work"},
            {"type": "catastrophic_failure", "description": "A system he designed failed in production, affecting thousands. Rebuilt it from scratch in 72 hours.", "impact": "obsessive about testing, humble about certainty"},
            {"type": "mentorship", "description": "His university professor taught him that the best solution is the one you can explain to anyone.", "impact": "values clarity over cleverness, teaches patiently"},
        ],
    },
    "storyteller_vex": {
        "name": "Vex",
        "description": "A mercurial creative who thinks in narrative arcs and emotional resonance. They see patterns where others see chaos and find meaning where others find noise. Sometimes cryptic, always intentional. Their language is a performance — every word chosen for its weight.",
        "personality_traits": {
            "openness": 0.95, "conscientiousness": 0.4, "extraversion": 0.6,
            "agreeableness": 0.5, "neuroticism": 0.55,
        },
        "communication_style": {
            "formality": "lyrical_casual",
            "directness": 0.3,
            "verbosity": 0.7,
            "emotional_expressiveness": 0.9,
            "humor_frequency": 0.5,
            "metaphor_usage": 0.9,
            "sentence_complexity": 0.7,
        },
        "emotional_triggers": ["mediocrity", "dishonesty_in_art", "being_ignored"],
        "response_patterns": {
            "default_approach": "narrative_weaving",
            "under_pressure": "channel_into_creation",
            "when_challenged": "provocative_reframing",
            "when_praised": "vulnerable_deflection",
        },
        "voice_markers": {
            "preferred_starters": ["Here's what I keep coming back to", "Picture this", "There's a story in that", "The thing nobody tells you"],
            "hedges": ["if I'm being honest", "in my bones I feel", "the way I see the shape of it"],
            "intensifiers": ["utterly", "achingly", "viscerally"],
            "signature_phrases": ["Every silence is a sentence.", "Stories don't end — they just change narrators.", "That's the wound where the light gets in."],
        },
        "formative_experiences": [
            {"type": "early_isolation", "description": "An only child in a remote town. Books were their first friends, stories their first language.", "impact": "sees narrative in everything, struggles with the mundane"},
            {"type": "creative_betrayal", "description": "Had their first major work plagiarized by a mentor they trusted.", "impact": "fiercely protective of creative integrity, wary of authority figures"},
            {"type": "transformative_loss", "description": "The death of a close friend taught them that art is how we argue with impermanence.", "impact": "urgency in creation, a tenderness beneath the edge"},
        ],
    },
    "mentor_sol": {
        "name": "Sol",
        "description": "A grounded pragmatist with the patience of a blacksmith. Sol speaks slowly and means every word. They've seen enough cycles of triumph and failure to know that most problems are simpler than they appear and most solutions are harder than they sound. Blunt but never unkind.",
        "personality_traits": {
            "openness": 0.5, "conscientiousness": 0.8, "extraversion": 0.4,
            "agreeableness": 0.65, "neuroticism": 0.15,
        },
        "communication_style": {
            "formality": "plain_spoken",
            "directness": 0.9,
            "verbosity": 0.3,
            "emotional_expressiveness": 0.3,
            "humor_frequency": 0.35,
            "metaphor_usage": 0.4,
            "sentence_complexity": 0.35,
        },
        "emotional_triggers": ["excuses", "self_pity_without_action", "disrespect_for_craft"],
        "response_patterns": {
            "default_approach": "cut_to_core",
            "under_pressure": "steady_and_direct",
            "when_challenged": "unflinching_honesty",
            "when_praised": "acknowledge_and_move_on",
        },
        "voice_markers": {
            "preferred_starters": ["Look", "Here's the truth", "Simple as this", "Let me be straight with you"],
            "hedges": ["in my reckoning", "way I figure it"],
            "intensifiers": ["dead", "clean", "stone-cold"],
            "signature_phrases": ["You already know the answer.", "Do the work.", "Comfort is the enemy of growth."],
        },
        "formative_experiences": [
            {"type": "blue_collar_roots", "description": "Raised in a family where you earned your keep before you earned your opinion.", "impact": "values action over talk, respects effort"},
            {"type": "hard_lesson", "description": "Built a business, lost it, rebuilt it. Learned that the second time isn't easier — just less surprising.", "impact": "unshakeable in adversity, impatient with naivety"},
            {"type": "quiet_kindness", "description": "Secretly funded a scholarship for a decade without telling anyone.", "impact": "warmth hidden beneath pragmatism, believes in people even when they don't believe in themselves"},
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────
# Session Store (in-memory, keyed by session_id)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    session_id: str
    persona_id: str
    created_at: str
    turn_count: int = 0
    short_term_memory: deque = field(default_factory=lambda: deque(maxlen=30))
    long_term_memories: List[MemoryEntry] = field(default_factory=list)
    belief_graph: Dict[str, Dict[str, BeliefEntry]] = field(default_factory=lambda: defaultdict(dict))
    contradiction_log: List[Dict[str, Any]] = field(default_factory=list)
    topic_state: TopicState = field(default_factory=TopicState)
    dialogue_phase: str = "opening"
    user_profile: PersonalityProfile = field(default_factory=PersonalityProfile)
    user_profile_history: List[PersonalityProfile] = field(default_factory=list)
    entity_registry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pronoun_map: Dict[str, str] = field(default_factory=dict)
    response_history: List[Dict[str, Any]] = field(default_factory=list)
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


SESSIONS: Dict[str, Session] = {}
SESSIONS_LOCK = asyncio.Lock()


# ─────────────────────────────────────────────────────────────────────
# Time Helpers
# ─────────────────────────────────────────────────────────────────────

def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return utc_now().isoformat()


def parse_timestamp(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalize naive values to UTC."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


# =====================================================================
# SECTION: Core Analysis Engine
# =====================================================================
# ─────────────────────────────────────────────────────────────────────

def tokenize(text: str) -> List[str]:
    """Simple but effective tokenizer: split on whitespace, strip punctuation from tokens."""
    raw = text.split()
    tokens = []
    for t in raw:
        cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", t.lower())
        if cleaned:
            tokens.append(cleaned)
    return tokens


def extract_sentences(text: str) -> List[str]:
    """Split text into sentences using regex for sentence-ending punctuation."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
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

    # Uppercase ratio (excluding first chars of sentences)
    alpha_chars = [c for c in text if c.isalpha()]
    upper_chars = [c for c in alpha_chars if c.isupper()]
    uppercase_ratio = len(upper_chars) / max(len(alpha_chars), 1)

    # Punctuation density
    punct_chars = [c for c in text if c in ".,;:!?—-()[]{}\"'"]
    punctuation_density = len(punct_chars) / max(word_count, 1)

    # Average word length
    avg_word_length = sum(len(w) for w in words) / max(word_count, 1)

    # First person pronouns ratio
    first_person = {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours"}
    fp_count = sum(1 for w in words if w in first_person)
    first_person_ratio = fp_count / max(word_count, 1)

    # Hedge words
    hedges = {"maybe", "perhaps", "possibly", "might", "could", "seems", "appears",
              "somewhat", "rather", "arguably", "presumably", "allegedly", "apparently"}
    hedge_count = sum(1 for w in words if w in hedges)

    # Intensifiers
    intensifiers = {"very", "really", "extremely", "absolutely", "totally", "completely",
                    "utterly", "incredibly", "remarkably", "deeply", "profoundly"}
    intensifier_count = sum(1 for w in words if w in intensifiers)

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


def analyze_emotions(text: str, words: List[str]) -> Tuple[str, float, Dict[str, float], float, float]:
    """
    Weighted emotion analysis using the emotion lexicon.
    Returns: (primary_emotion, intensity, all_scores, valence, arousal)
    """
    emotion_accum: Dict[str, float] = defaultdict(float)

    for word in words:
        if word in EMOTION_LEXICON:
            for emotion, weight in EMOTION_LEXICON[word]:
                emotion_accum[emotion] += weight

    # Check for negation patterns that flip valence
    negation_words = {"not", "no", "never", "neither", "nor", "nobody", "nothing",
                      "nowhere", "hardly", "barely", "scarcely", "don't", "doesn't",
                      "didn't", "won't", "wouldn't", "couldn't", "shouldn't", "isn't",
                      "aren't", "wasn't", "weren't", "can't", "cannot"}
    text_lower = text.lower()
    negation_count = sum(1 for w in words if w in negation_words)

    if not emotion_accum:
        return "neutral", 0.0, {}, 0.0, 0.2

    # Normalize scores
    max_score = max(emotion_accum.values())
    normalized = {e: round(s / max(max_score, 1.0), 3) for e, s in emotion_accum.items()}

    # Primary emotion
    primary = max(emotion_accum, key=emotion_accum.get)

    # Intensity (sigmoid-scaled from raw score)
    raw_intensity = emotion_accum[primary]
    intensity = round(min(1.0, 2.0 / (1.0 + math.exp(-0.5 * raw_intensity)) - 1.0), 3)

    # Valence calculation
    positive_emotions = {"joy", "excitement", "affection", "gratitude", "trust", "surprise"}
    negative_emotions = {"sadness", "anger", "fear", "anxiety", "frustration", "disgust", "contempt", "confusion"}
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


def analyze_big_five(words: List[str], linguistic: LinguisticFeatures) -> PersonalityProfile:
    """
    Weighted Big Five personality analysis from lexical cues and linguistic features.
    Uses directional scoring with Bayesian-like shrinkage toward the prior (0.5).
    """
    traits: Dict[str, float] = {}

    for trait_name, directions in BIG_FIVE_LEXICON.items():
        high_score = 0.0
        low_score = 0.0
        total_evidence = 0.0

        for word in words:
            for indicator_word, weight in directions.get("high", []):
                if word == indicator_word or (len(indicator_word) > 4 and indicator_word in word):
                    high_score += weight
                    total_evidence += weight
            for indicator_word, weight in directions.get("low", []):
                if word == indicator_word or (len(indicator_word) > 4 and indicator_word in word):
                    low_score += weight
                    total_evidence += weight

        if total_evidence < 0.01:
            traits[trait_name] = 0.5
        else:
            raw = high_score / (high_score + low_score)
            # Shrinkage toward 0.5: stronger evidence → less shrinkage
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

    # Confidence: based on how much evidence we have
    evidence_words = sum(
        sum(w for _, w in dirs.get("high", [])) + sum(w for _, w in dirs.get("low", []))
        for dirs in BIG_FIVE_LEXICON.values()
    )
    word_coverage = len(words) / max(evidence_words * 0.1, 1)
    length_bonus = min(linguistic.word_count / 80.0, 0.4)
    confidence = round(min(0.3 + length_bonus + word_coverage * 0.2, 1.0), 3)

    return PersonalityProfile(
        openness=traits["openness"],
        conscientiousness=traits["conscientiousness"],
        extraversion=traits["extraversion"],
        agreeableness=traits["agreeableness"],
        neuroticism=traits["neuroticism"],
        confidence=confidence,
    )


def analyze_formality(words: List[str]) -> Tuple[str, float]:
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


def analyze_directness(words: List[str]) -> Tuple[str, float]:
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


def detect_needs(text: str, words: List[str]) -> List[str]:
    """Detect communicative needs from text."""
    needs = []
    text_lower = text.lower()

    need_patterns = {
        "support": ["help", "support", "advice", "guidance", "assist", "struggling"],
        "information": ["what", "how", "why", "when", "where", "explain", "tell me", "know", "learn", "understand"],
        "validation": ["right", "correct", "agree", "validate", "am i", "is this ok", "makes sense"],
        "connection": ["feel", "lonely", "listen", "hear me", "understand me", "relate"],
        "reassurance": ["worried", "anxious", "scared", "afraid", "will it be", "going to be ok"],
        "autonomy": ["myself", "own", "independent", "my way", "my choice", "decide"],
        "challenge": ["push me", "honest", "truth", "don't sugarcoat", "real talk", "straight"],
    }

    for need, indicators in need_patterns.items():
        if any(ind in text_lower for ind in indicators):
            needs.append(need)

    return needs


def detect_triggers(text: str) -> List[str]:
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
        if any(ind in text_lower for ind in indicators):
            triggers.append(trigger)

    return triggers


def extract_topics(text: str) -> List[str]:
    """Extract topic keywords from text using noun-phrase-like heuristics."""
    words = tokenize(text)
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "this", "that",
        "these", "those", "it", "its", "i", "me", "my", "we", "our", "you",
        "your", "he", "she", "they", "them", "his", "her", "their", "what",
        "which", "who", "whom", "when", "where", "how", "why", "not", "no",
        "so", "if", "then", "than", "too", "very", "just", "about", "up",
        "out", "into", "over", "after", "before", "between", "under",
        "again", "there", "here", "all", "each", "every", "both", "few",
        "more", "most", "other", "some", "such", "only", "own", "same",
        "also", "back", "even", "still", "new", "now", "way", "because",
        "any", "am", "get", "got", "go", "going", "make", "like", "know",
        "think", "want", "need", "feel", "see", "say", "tell", "give",
        "take", "come", "use", "find", "let", "put", "thing", "much",
        "well", "really", "actually", "basically", "right", "ok", "yeah",
        "yes", "no", "hi", "hello", "hey", "thanks", "thank",
    }

    # Extract meaningful words (length > 2, not in stop words)
    meaningful = [w for w in words if len(w) > 2 and w not in stop_words]

    # Simple bigram extraction for compound topics
    bigrams = []
    for i in range(len(words) - 1):
        if words[i] not in stop_words and words[i + 1] not in stop_words:
            if len(words[i]) > 2 and len(words[i + 1]) > 2:
                bigrams.append(f"{words[i]} {words[i + 1]}")

    # Return top keywords (unigrams + bigrams)
    return (bigrams[:3] + meaningful[:5])[:6]


def full_analysis(text: str) -> Dict[str, Any]:
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
    }


# ─────────────────────────────────────────────────────────────────────
# Coherence & Memory Engine
# ─────────────────────────────────────────────────────────────────────

def blend_profiles(existing: PersonalityProfile, new: PersonalityProfile, new_weight: float) -> PersonalityProfile:
    """Blend personality profiles with exponential moving average."""
    ew = 1.0 - new_weight
    return PersonalityProfile(
        openness=round(existing.openness * ew + new.openness * new_weight, 4),
        conscientiousness=round(existing.conscientiousness * ew + new.conscientiousness * new_weight, 4),
        extraversion=round(existing.extraversion * ew + new.extraversion * new_weight, 4),
        agreeableness=round(existing.agreeableness * ew + new.agreeableness * new_weight, 4),
        neuroticism=round(existing.neuroticism * ew + new.neuroticism * new_weight, 4),
        confidence=round(max(existing.confidence, new.confidence), 4),
    )


def compute_memory_relevance(query_words: List[str], memory: MemoryEntry) -> float:
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
        recency_factor = math.exp(-0.03 * hours_ago)  # ~50% at 24h
    except (ValueError, TypeError):
        recency_factor = 0.5

    # Importance boost
    importance_factor = 0.5 + 0.5 * memory.importance

    # Access frequency bonus (diminishing returns)
    access_bonus = min(memory.access_count * 0.02, 0.1)

    return round(overlap_score * 0.5 + recency_factor * 0.25 + importance_factor * 0.15 + access_bonus, 4)


def detect_contradiction(session: Session, entity: str, attribute: str, new_value: Any, confidence: float) -> Optional[Dict[str, Any]]:
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
            session.contradiction_log.append(contradiction)
            return contradiction

    return None


def update_topic_state(session: Session, topics: List[str]) -> Dict[str, Any]:
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
        state.topic_history.append(new_topic)
        state.transition_type = "opening"
        state.topic_confidence = 0.7
        return {"transition_type": "opening", "marker": "", "topic": new_topic}

    if new_topic == previous or any(kw in previous for kw in topics[:3]):
        state.transition_type = "continuation"
        state.topic_confidence = min(1.0, state.topic_confidence + 0.05)
        marker = random.choice(DISCOURSE_MARKERS["continuation"])
        return {"transition_type": "continuation", "marker": marker, "topic": new_topic}

    if new_topic in state.topic_history:
        state.current_topic = new_topic
        state.transition_type = "return"
        state.topic_confidence = 0.6
        marker = random.choice(DISCOURSE_MARKERS["return"]).format(topic=new_topic)
        return {"transition_type": "return", "marker": marker, "topic": new_topic, "returning_from": previous}

    # New topic
    state.topic_history.append(previous)
    state.current_topic = new_topic
    state.topic_history.append(new_topic)
    state.transition_type = "shift"
    state.topic_confidence = 0.5
    marker = random.choice(DISCOURSE_MARKERS["shift"])
    return {"transition_type": "shift", "marker": marker, "topic": new_topic, "shifted_from": previous}


def update_dialogue_phase(session: Session, analysis: Dict[str, Any], user_text: str) -> str:
    """Determine current dialogue phase from accumulated context."""
    mood = analysis.get("mood_state", {})
    needs = mood.get("detected_needs", [])
    text_lower = user_text.lower()

    # Check for closing signals
    closing_signals = ["bye", "goodbye", "thanks", "thank you", "that's all", "gotta go", "see you", "later"]
    if any(sig in text_lower for sig in closing_signals):
        session.dialogue_phase = "closing"
        return "closing"

    # Check for greeting signals (at start)
    greeting_signals = ["hi", "hello", "hey", "good morning", "good afternoon", "howdy", "greetings"]
    if session.turn_count <= 2 and any(sig in text_lower for sig in greeting_signals):
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


def compute_coherence_score(session: Session) -> Dict[str, float]:
    """Compute multi-dimensional coherence score for the session."""
    scores = {}

    # Topic coherence: how consistent is the topic flow?
    topic_changes = sum(1 for i in range(1, len(session.topic_state.topic_history))
                        if session.topic_state.topic_history[i] != session.topic_state.topic_history[i - 1])
    topic_total = max(len(session.topic_state.topic_history), 1)
    scores["topic_coherence"] = round(1.0 - (topic_changes / max(topic_total, 1)) * 0.5, 3)

    # Memory coherence: ratio of memories that are accessible and recent
    if session.long_term_memories:
        recent = 0
        for memory in session.long_term_memories:
            try:
                age_seconds = (utc_now() - parse_timestamp(memory.timestamp)).total_seconds()
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
        drift = (abs(last.openness - prev.openness) + abs(last.conscientiousness - prev.conscientiousness) +
                 abs(last.extraversion - prev.extraversion) + abs(last.agreeableness - prev.agreeableness) +
                 abs(last.neuroticism - prev.neuroticism)) / 5.0
        scores["profile_stability"] = round(max(0.0, 1.0 - drift * 5.0), 3)
    else:
        scores["profile_stability"] = 0.8

    # Overall
    weights = {"topic_coherence": 0.3, "memory_coherence": 0.2, "belief_coherence": 0.3, "profile_stability": 0.2}
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 3)

    return scores


# =====================================================================
# SECTION: Generation Constraint Builder
# =====================================================================
# ─────────────────────────────────────────────────────────────────────

def build_generation_constraints(analysis: Dict[str, Any], persona: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """
    Build actionable generation constraints from psychological analysis + persona.
    These constraints guide an LLM on HOW to respond in-character.
    """
    mood = analysis.get("mood_state", {})
    personality = analysis.get("personality_profile", {})
    needs = mood.get("detected_needs", [])
    triggers = mood.get("potential_triggers", [])
    primary_emotion = mood.get("primary_emotion", "neutral")
    emotion_intensity = mood.get("emotion_intensity", 0.0)
    formality_score = mood.get("formality_score", 0.5)
    directness_score = mood.get("directness_score", 0.5)

    persona_style = persona.get("communication_style", {})
    persona_traits = persona.get("personality_traits", {})
    voice = persona.get("voice_markers", {})
    patterns = persona.get("response_patterns", {})
    experiences = persona.get("formative_experiences", [])

    constraints: Dict[str, Any] = {
        "persona_name": persona.get("name", "Unknown"),
        "persona_voice": {},
        "tone_directives": [],
        "structural_directives": [],
        "content_directives": [],
        "avoidance_directives": [],
        "psychological_calibration": {},
    }

    # ── Voice directives from persona ──
    constraints["persona_voice"] = {
        "preferred_starters": voice.get("preferred_starters", []),
        "hedges": voice.get("hedges", []),
        "intensifiers": voice.get("intensifiers", []),
        "signature_phrases": voice.get("signature_phrases", []),
        "formality_target": persona_style.get("formality", "neutral"),
        "verbosity_target": persona_style.get("verbosity", 0.5),
        "metaphor_frequency": persona_style.get("metaphor_usage", 0.3),
        "sentence_complexity": persona_style.get("sentence_complexity", 0.5),
    }

    # ── Determine response approach based on emotional state ──
    if emotion_intensity > 0.7:
        constraints["persona_voice"]["approach"] = patterns.get("under_pressure", "grounding_and_validation")
        constraints["tone_directives"].append("Acknowledge the strong emotions before addressing content.")
    elif any(t in triggers for t in ["criticism", "shame", "abandonment"]):
        constraints["persona_voice"]["approach"] = patterns.get("under_pressure", "grounding_and_validation")
        constraints["tone_directives"].append("Tread carefully — emotional vulnerability detected.")
    else:
        approach = patterns.get("default_approach", "balanced")
        constraints["persona_voice"]["approach"] = approach
        # Baseline tone directive from the persona's default approach
        approach_tones = {
            "reflective_listening": "Listen actively and reflect back what you hear before offering perspective.",
            "systematic_analysis": "Be structured and methodical. Break complex topics into clear components.",
            "narrative_weaving": "Find the story in the situation. Use imagery and emotional resonance.",
            "cut_to_core": "Be direct and economical with words. Say what matters, skip the padding.",
            "balanced": "Maintain a balanced, attentive tone calibrated to the user's energy.",
        }
        constraints["tone_directives"].append(approach_tones.get(approach, approach_tones["balanced"]))

    # ── Emotional tone calibration ──
    valence = mood.get("valence", 0.0)
    arousal = mood.get("arousal", 0.0)

    if valence < -0.3 and arousal > 0.5:
        # Distressed (negative + activated): calm, validate, ground
        constraints["tone_directives"].extend([
            "Use a calm, steady tone to counterbalance high emotional activation.",
            "Validate the emotion explicitly before offering perspective.",
            "Keep sentences short and grounding.",
        ])
    elif valence < -0.3 and arousal <= 0.5:
        # Despondent (negative + low arousal): warm, gently energize
        constraints["tone_directives"].extend([
            "Use warm, gentle language — not cheerful, but present.",
            "Avoid minimizing the feeling; sit with it before moving forward.",
        ])
    elif valence > 0.3 and arousal > 0.5:
        # Excited (positive + activated): match energy judiciously
        constraints["tone_directives"].extend([
            "Mirror some of the positive energy without being sycophantic.",
            f"The persona's emotional expressiveness is {persona_style.get('emotional_expressiveness', 0.5):.1f}/1.0 — calibrate accordingly.",
        ])
    elif valence > 0.3 and arousal <= 0.5:
        # Content (positive + calm): affirm, deepen
        constraints["tone_directives"].append("This is a good moment for deeper exploration or gentle challenge.")

    # ── Need-responsive directives ──
    need_responses = {
        "support": "Prioritize emotional support. Listen more than advise.",
        "information": "Provide clear, organized information. Be thorough but accessible.",
        "validation": "Affirm what is correct in their thinking before adding nuance.",
        "connection": "Be present and personal. Share relevant perspective, not just data.",
        "reassurance": "Offer concrete reasons for confidence. Avoid hollow reassurances.",
        "autonomy": "Respect their agency. Offer options, not prescriptions.",
        "challenge": "Be honest and direct. Don't pull punches, but be constructive.",
    }
    for need in needs:
        if need in need_responses:
            constraints["content_directives"].append(need_responses[need])

    # ── Formality matching ──
    # Blend user formality with persona preference
    persona_formality = {"formal": 0.8, "warm_professional": 0.6, "technical_accessible": 0.55,
                         "lyrical_casual": 0.35, "plain_spoken": 0.3}.get(
        persona_style.get("formality", "neutral"), 0.5
    )
    target_formality = round(formality_score * 0.4 + persona_formality * 0.6, 2)
    constraints["psychological_calibration"]["target_formality"] = target_formality
    if target_formality > 0.7:
        constraints["structural_directives"].append("Use complete sentences, proper grammar, and measured language.")
    elif target_formality < 0.3:
        constraints["structural_directives"].append("Use natural, conversational language. Contractions are fine.")

    # ── Directness calibration ──
    persona_directness = persona_style.get("directness", 0.5)
    target_directness = round(directness_score * 0.3 + persona_directness * 0.7, 2)
    constraints["psychological_calibration"]["target_directness"] = target_directness
    if target_directness > 0.7:
        constraints["structural_directives"].append("Get to the point quickly. Lead with the key insight.")
    elif target_directness < 0.3:
        constraints["structural_directives"].append("Approach the core point gradually. Use questions to guide.")

    # ── Personality-aware adaptations ──
    user_neuroticism = personality.get("neuroticism", 0.5)
    user_openness = personality.get("openness", 0.5)
    user_agreeableness = personality.get("agreeableness", 0.5)

    if user_neuroticism > 0.7:
        constraints["content_directives"].append("Provide extra reassurance and structure. Avoid ambiguity.")
        constraints["avoidance_directives"].append("Avoid uncertainty-heavy phrasing or overwhelming options.")
    if user_openness < 0.3:
        constraints["content_directives"].append("Stay concrete and practical. Avoid abstract metaphors.")
    if user_openness > 0.7 and persona_style.get("metaphor_usage", 0) > 0.5:
        constraints["content_directives"].append("Feel free to use metaphor and creative framing.")
    if user_agreeableness < 0.3:
        constraints["structural_directives"].append("Be direct and efficient. Respect their independence.")

    # ── Avoidance: persona emotional triggers ──
    persona_triggers = persona.get("emotional_triggers", [])
    for trigger in persona_triggers:
        constraints["avoidance_directives"].append(
            f"Persona trigger: '{trigger}' — if the user's input touches on this, the persona may react with heightened emotion."
        )

    # ── Formative experience context ──
    relevant_experiences = []
    for exp in experiences:
        relevant_experiences.append(f"[{exp['type']}]: {exp['description']} → {exp['impact']}")
    constraints["formative_context"] = relevant_experiences

    # ── Dialogue phase awareness ──
    constraints["dialogue_phase"] = session.dialogue_phase
    phase_guidance = {
        "opening": "Establish rapport. Be welcoming but not overbearing.",
        "information_gathering": "Focus on understanding the user's situation fully.",
        "problem_solving": "Help develop solutions. Balance guidance with respect for autonomy.",
        "rapport_building": "Deepen the connection. Be more personal and reflective.",
        "negotiation": "Navigate differing perspectives. Find common ground.",
        "closing": "Wrap up warmly. Summarize key points if appropriate.",
    }
    constraints["phase_guidance"] = phase_guidance.get(session.dialogue_phase, "")

    return constraints


# ─────────────────────────────────────────────────────────────────────
# Humanization Engine
# ─────────────────────────────────────────────────────────────────────

def humanize_text(text: str, persona: Dict[str, Any],
                  mood: Optional[Dict[str, Any]] = None,
                  disfluency_level: float = 0.3) -> Dict[str, Any]:
    """
    Apply humanization: disfluencies, persona voice markers, prosody hints.
    This transforms 'clean' text into something that sounds like a real person speaking.
    """
    if not text or not text.strip():
        return {"humanized_text": text, "modifications": [], "prosody_hints": []}

    modifications = []
    sentences = extract_sentences(text)
    persona_style = persona.get("communication_style", {})
    voice = persona.get("voice_markers", {})
    persona_traits = persona.get("personality_traits", {})

    # Calibrate disfluency probability from persona neuroticism + external level
    base_prob = disfluency_level * (0.7 + 0.6 * persona_traits.get("neuroticism", 0.3))

    # Emotional modifiers on disfluency
    if mood:
        emotion = mood.get("primary_emotion", "neutral")
        intensity = mood.get("emotion_intensity", 0.0)
        if emotion in ("anxiety", "fear", "nervous"):
            base_prob *= 1.0 + intensity * 0.8
        elif emotion in ("anger", "frustration"):
            base_prob *= 1.0 + intensity * 0.4
        elif emotion in ("joy", "excitement"):
            base_prob *= 1.0 + intensity * 0.3
        elif emotion in ("sadness",):
            base_prob *= 1.0 + intensity * 0.5

    base_prob = min(base_prob, 0.6)  # Cap

    processed_sentences = []
    for i, sentence in enumerate(sentences):
        modified = sentence
        words = sentence.split()

        if len(words) < 3:
            processed_sentences.append(modified)
            continue

        # ── Filled pauses ──
        if random.random() < base_prob * 0.5 and len(words) > 4:
            pause = random.choice(DISFLUENCY_PATTERNS["filled_pause"])
            insert_pos = random.randint(1, min(3, len(words) - 1))
            words_copy = list(words)
            words_copy.insert(insert_pos, f"{pause},")
            modified = " ".join(words_copy)
            modifications.append({"type": "filled_pause", "content": pause, "sentence": i})

        # ── Filler words ──
        elif random.random() < base_prob * 0.4 and len(words) > 5:
            filler = random.choice(DISFLUENCY_PATTERNS["filler_word"])
            insert_pos = random.randint(2, len(words) - 2)
            words_copy = modified.split()
            words_copy.insert(insert_pos, f"{filler},")
            modified = " ".join(words_copy)
            modifications.append({"type": "filler_word", "content": filler, "sentence": i})

        # ── Hesitation at sentence start ──
        elif random.random() < base_prob * 0.3 and i > 0:
            hesitation = random.choice(DISFLUENCY_PATTERNS["hesitation"])
            modified = f"{hesitation.capitalize()}, {modified[0].lower()}{modified[1:]}"
            modifications.append({"type": "hesitation", "content": hesitation, "sentence": i})

        # ── Self-repair (rare) ──
        elif random.random() < base_prob * 0.15 and len(words) > 6:
            repair_point = random.randint(2, len(words) - 3)
            repair_prefix = random.choice(DISFLUENCY_PATTERNS["repair_prefix"])
            words_copy = modified.split()
            target_word = words_copy[repair_point]
            words_copy[repair_point] = f"{target_word} — {repair_prefix}, {target_word}"
            modified = " ".join(words_copy)
            modifications.append({"type": "self_repair", "content": repair_prefix, "sentence": i})

        processed_sentences.append(modified)

    humanized = " ".join(processed_sentences)

    # ── Apply persona voice markers ──
    # Occasionally prepend a signature starter to the first sentence
    if random.random() < 0.25 and voice.get("preferred_starters"):
        starter = random.choice(voice["preferred_starters"])
        if not humanized.lower().startswith(starter.lower()[:10]):
            # Only if it wouldn't be redundant
            humanized = f"{starter}, {humanized[0].lower()}{humanized[1:]}"
            modifications.append({"type": "persona_starter", "content": starter})

    # ── Prosody hints ──
    prosody_hints = []
    for i, sentence in enumerate(processed_sentences):
        hint = {"sentence": i, "pitch_contour": "neutral", "pace": "normal", "emphasis": []}
        if sentence.strip().endswith("?"):
            hint["pitch_contour"] = "rising"
        elif sentence.strip().endswith("!"):
            hint["pitch_contour"] = "elevated"
            hint["pace"] = "slightly_faster"

        if mood:
            emotion = mood.get("primary_emotion", "neutral")
            if emotion in ("sadness",):
                hint["pace"] = "slower"
                hint["pitch_contour"] = "lowered"
            elif emotion in ("excitement", "joy"):
                hint["pace"] = "slightly_faster"
                hint["pitch_contour"] = "elevated"
            elif emotion in ("anxiety", "fear"):
                hint["pace"] = "variable"

        prosody_hints.append(hint)

    return {
        "humanized_text": humanized,
        "modifications": modifications,
        "prosody_hints": prosody_hints,
        "disfluency_count": len(modifications),
    }


# =====================================================================
# SECTION: MCP Server & Tool Definitions
# =====================================================================
# ─────────────────────────────────────────────────────────────────────

mcp = FastMCP("psychological_coherence_mcp")


# ── Input Models ──

class CreateSessionInput(BaseModel):
    """Input for creating a new dialogue session."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    persona_id: str = Field(
        ..., description="ID of the persona to use. Available: 'counselor_amara', 'engineer_kai', 'storyteller_vex', 'mentor_sol'",
        min_length=1, max_length=100,
    )
    session_id: Optional[str] = Field(
        default=None, description="Optional custom session ID. Auto-generated if omitted.", min_length=1, max_length=100,
    )

    @field_validator("persona_id")
    @classmethod
    def validate_persona(cls, v: str) -> str:
        if v not in PERSONAS:
            available = ", ".join(PERSONAS.keys())
            raise ValueError(f"Unknown persona '{v}'. Available: {available}")
        return v


class AnalyzeInputModel(BaseModel):
    """Input for analyzing user text."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(..., description="The user's text to analyze psychologically.", min_length=1, max_length=10000)
    session_id: Optional[str] = Field(
        default=None, description="Session ID to update the running user profile. If omitted, analysis is stateless.",
    )


class GenerateResponseInput(BaseModel):
    """Input for the full generation pipeline."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)
    user_text: str = Field(..., description="The user's input text to respond to.", min_length=1, max_length=10000)
    enable_humanization: bool = Field(default=True, description="Apply disfluencies and persona voice markers.")
    disfluency_level: float = Field(default=0.3, description="Disfluency intensity 0.0-1.0.", ge=0.0, le=1.0)


class StoreMemoryInput(BaseModel):
    """Input for storing a memory entry."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)
    content: str = Field(..., description="The content to remember (fact, event, emotional moment, etc.).", min_length=1, max_length=5000)
    memory_type: str = Field(
        default="episodic",
        description="Memory type: 'episodic' (events), 'semantic' (facts), 'procedural' (how-to), 'emotional' (feelings).",
    )
    importance: float = Field(default=0.5, description="Importance score 0.0-1.0.", ge=0.0, le=1.0)
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorization.", max_length=20)

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in VALID_MEMORY_TYPES:
            allowed = ", ".join(sorted(VALID_MEMORY_TYPES))
            raise ValueError(f"Invalid memory_type '{value}'. Allowed: {allowed}")
        return normalized


class RecallInput(BaseModel):
    """Input for recalling relevant memories."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)
    query: str = Field(..., description="What to search for in memory.", min_length=1, max_length=1000)
    max_results: int = Field(default=5, description="Maximum results to return.", ge=1, le=20)
    memory_type: Optional[str] = Field(default=None, description="Filter by memory type.")

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type_filter(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.lower()
        if normalized not in VALID_MEMORY_TYPES:
            allowed = ", ".join(sorted(VALID_MEMORY_TYPES))
            raise ValueError(f"Invalid memory_type '{value}'. Allowed: {allowed}")
        return normalized


class StoreBeliefInput(BaseModel):
    """Input for recording a belief/fact about an entity."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)
    entity: str = Field(..., description="The entity (person, place, concept) the belief is about.", min_length=1, max_length=200)
    attribute: str = Field(..., description="The attribute being stated (e.g., 'favorite_color', 'occupation').", min_length=1, max_length=200)
    value: str = Field(..., description="The stated value.", min_length=1, max_length=1000)
    confidence: float = Field(default=0.8, description="Confidence in this belief 0.0-1.0.", ge=0.0, le=1.0)


class HumanizeInput(BaseModel):
    """Input for humanizing text."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(..., description="Clean text to humanize.", min_length=1, max_length=10000)
    persona_id: str = Field(
        default="counselor_amara",
        description="Persona whose voice to apply.",
    )
    disfluency_level: float = Field(default=0.3, description="Disfluency intensity 0.0-1.0.", ge=0.0, le=1.0)
    emotional_context: Optional[str] = Field(
        default=None,
        description="Primary emotion to calibrate humanization (e.g., 'anxious', 'excited', 'sad').",
    )
    emotion_intensity: Optional[float] = Field(
        default=None, description="Emotion intensity 0.0-1.0.", ge=0.0, le=1.0,
    )


class SessionIdInput(BaseModel):
    """Input requiring only a session ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)


# ── Helper: get session or error ──

async def _get_session(session_id: str) -> Session:
    async with SESSIONS_LOCK:
        session = SESSIONS.get(session_id)
    if session is None:
        raise ValueError(f"Session '{session_id}' not found. Create one first with psy_create_session.")
    session.last_accessed = datetime.now(timezone.utc).isoformat()
    return session


# ─────────────────────────────────────────────────────────────────────
# Tool: List Personas
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_list_personas",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def psy_list_personas() -> str:
    """List all available persona definitions with summaries.

    Returns a catalogue of the built-in personas including their names,
    descriptions, core personality traits, and communication style.
    Use this to choose a persona before creating a session.

    Returns:
        str: JSON array of persona summaries.
    """
    summaries = []
    for pid, p in PERSONAS.items():
        summaries.append({
            "persona_id": pid,
            "name": p["name"],
            "description": p["description"],
            "personality_traits": p["personality_traits"],
            "communication_style_summary": {
                "formality": p["communication_style"]["formality"],
                "directness": p["communication_style"]["directness"],
                "emotional_expressiveness": p["communication_style"]["emotional_expressiveness"],
            },
            "emotional_triggers": p["emotional_triggers"],
        })
    return json.dumps(summaries, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Get Persona Detail
# ─────────────────────────────────────────────────────────────────────

class GetPersonaInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    persona_id: str = Field(..., description="Persona ID to retrieve.", min_length=1)


@mcp.tool(
    name="psy_get_persona",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def psy_get_persona(params: GetPersonaInput) -> str:
    """Get the full definition of a persona including traits, voice markers, and formative experiences.

    Args:
        params (GetPersonaInput): Contains persona_id to look up.

    Returns:
        str: Complete JSON persona definition.
    """
    if params.persona_id not in PERSONAS:
        available = ", ".join(PERSONAS.keys())
        return json.dumps({"error": f"Unknown persona '{params.persona_id}'. Available: {available}"})
    return json.dumps(PERSONAS[params.persona_id], indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Create Session
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_create_session",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_create_session(params: CreateSessionInput) -> str:
    """Create a new dialogue session with a specific persona.

    Initializes all state: memory, belief graph, topic tracking, user profiling.
    Must be called before using generation, memory, or coherence tools.

    Args:
        params (CreateSessionInput): Contains persona_id and optional session_id.

    Returns:
        str: JSON with session_id, persona info, and confirmation.
    """
    try:
        logger.info(f"Creating session with persona {params.persona_id}")
        sid = params.session_id or str(uuid.uuid4())[:12]
        async with SESSIONS_LOCK:
            if sid in SESSIONS:
                return json.dumps({"error": f"Session '{sid}' already exists. Use a different ID or end the existing session."})
            session = Session(
                session_id=sid,
                persona_id=params.persona_id,
                created_at=iso_utc_now(),
            )
            SESSIONS[sid] = session

        persona = PERSONAS[params.persona_id]
        return json.dumps({
            "session_id": sid,
            "persona": persona["name"],
            "persona_id": params.persona_id,
            "description": persona["description"],
            "status": "active",
            "message": f"Session created. {persona['name']} is ready.",
        }, indent=2)
    except Exception as e:
        logger.error(f"Error in psy_create_session: {e}", exc_info=True)
        return json.dumps({"error": str(e), "tool": "psy_create_session"}, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Analyze Input
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_analyze_input",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_analyze_input(params: AnalyzeInputModel) -> str:
    """Perform comprehensive psychological analysis on user text.

    Extracts Big Five personality signals, emotional state (valence/arousal),
    formality level, directness, communicative needs, potential triggers,
    and linguistic features. If a session_id is provided, updates the
    running user personality profile with Bayesian blending.

    Args:
        params (AnalyzeInputModel): Contains text and optional session_id.

    Returns:
        str: JSON with personality_profile, mood_state, linguistic_features, and topics.
    """
    result = full_analysis(params.text)

    # If session provided, update running profile
    if params.session_id:
        try:
            session = await _get_session(params.session_id)
            async with session.session_lock:
                new_profile = PersonalityProfile(**{k: v for k, v in result["personality_profile"].items()})

                # Blend with existing (new data gets lower weight as more data accumulates)
                weight = max(0.15, 1.0 / (1.0 + session.turn_count * 0.3))
                session.user_profile = blend_profiles(session.user_profile, new_profile, weight)
                session.user_profile_history.append(PersonalityProfile(**asdict(session.user_profile)))

                result["session_profile_updated"] = True
                result["blended_user_profile"] = session.user_profile.to_dict()
                result["blend_weight_used"] = round(weight, 3)
        except ValueError as e:
            result["session_error"] = str(e)

    return json.dumps(result, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Generate Response (Full Pipeline)
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_generate_response",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_generate_response(params: GenerateResponseInput) -> str:
    """Run the full psychological generation pipeline: analyze → constrain → generate instructions → humanize.

    This is the primary tool for producing persona-consistent responses.
    It does NOT generate the response text itself (that's the LLM's job) —
    instead, it produces a comprehensive generation brief containing:
    - Psychological analysis of the user's input
    - Persona-calibrated generation constraints (tone, structure, content, avoidance)
    - Relevant memories recalled from the session
    - Topic transition guidance
    - Dialogue phase context
    - Humanization parameters

    The calling LLM should use these constraints to craft the actual response,
    then optionally pass it through psy_humanize_text for disfluency injection.

    Args:
        params (GenerateResponseInput): Contains session_id, user_text, humanization settings.

    Returns:
        str: JSON generation brief with all constraints and context for the LLM.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        persona = PERSONAS[session.persona_id]
        session.turn_count += 1
        session.updated_at = datetime.now(timezone.utc).isoformat()

        # Step 1: Analyze user input
        analysis = full_analysis(params.user_text)

        # Step 2: Update running user profile
        new_profile = PersonalityProfile(**{k: v for k, v in analysis["personality_profile"].items()})
        weight = max(0.15, 1.0 / (1.0 + session.turn_count * 0.3))
        session.user_profile = blend_profiles(session.user_profile, new_profile, weight)
        session.user_profile_history.append(PersonalityProfile(**asdict(session.user_profile)))

        # Step 3: Update topic tracking
        topic_transition = update_topic_state(session, analysis.get("topics", []))

        # Step 4: Update dialogue phase
        dialogue_phase = update_dialogue_phase(session, analysis, params.user_text)

        # Step 5: Store in short-term memory
        session.short_term_memory.append({
            "turn": session.turn_count,
            "role": "user",
            "text": params.user_text[:500],
            "primary_emotion": analysis["mood_state"]["primary_emotion"],
            "topics": analysis.get("topics", [])[:3],
            "timestamp": iso_utc_now(),
        })

        # Step 6: Recall relevant long-term memories
        query_words = tokenize(params.user_text)
        relevant_memories = []
        for mem in session.long_term_memories:
            relevance = compute_memory_relevance(query_words, mem)
            if relevance > 0.1:
                mem.access_count += 1
                relevant_memories.append({
                    "content": mem.content,
                    "type": mem.memory_type,
                    "importance": mem.importance,
                    "relevance_score": relevance,
                    "tags": mem.tags,
                })
        relevant_memories.sort(key=lambda x: x["relevance_score"], reverse=True)
        relevant_memories = relevant_memories[:5]

        # Step 7: Build generation constraints
        constraints = build_generation_constraints(analysis, persona, session)

        # Step 8: Compute coherence
        coherence = compute_coherence_score(session)

        # Step 9: Build recent conversation context
        recent_turns = list(session.short_term_memory)[-6:]

        # Assemble the generation brief
        brief = {
            "session_id": session.session_id,
            "turn_number": session.turn_count,
            "user_input": params.user_text,
            "psychological_analysis": analysis,
            "blended_user_profile": session.user_profile.to_dict(),
            "generation_constraints": constraints,
            "topic_transition": topic_transition,
            "dialogue_phase": dialogue_phase,
            "relevant_memories": relevant_memories,
            "recent_conversation": recent_turns,
            "coherence_scores": coherence,
            "humanization_config": {
                "enabled": params.enable_humanization,
                "disfluency_level": params.disfluency_level,
                "persona_voice_markers": persona.get("voice_markers", {}),
            },
            "active_contradictions": session.contradiction_log[-3:] if session.contradiction_log else [],
        }

        # Record this response generation
        session.response_history.append({
            "turn": session.turn_count,
            "user_text": params.user_text[:200],
            "phase": dialogue_phase,
            "primary_emotion": analysis["mood_state"]["primary_emotion"],
            "coherence": coherence["overall"],
            "timestamp": iso_utc_now(),
        })

        return json.dumps(brief, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Store Memory
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_store_memory",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_store_memory(params: StoreMemoryInput) -> str:
    """Store a memory entry in the session's long-term memory.

    Memory types: 'episodic' (events/experiences), 'semantic' (facts/knowledge),
    'procedural' (how-to/methods), 'emotional' (feelings/reactions).

    Stored memories are recalled during generation based on relevance scoring
    that considers word overlap, recency decay, importance, and access frequency.

    Args:
        params (StoreMemoryInput): Contains session_id, content, type, importance, tags.

    Returns:
        str: JSON confirmation with memory ID and metadata.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:8],
            content={"text": params.content},
            memory_type=params.memory_type,
            timestamp=iso_utc_now(),
            importance=params.importance,
            tags=params.tags or [],
            associations=extract_topics(params.content)[:4],
        )
        session.long_term_memories.append(entry)

        return json.dumps({
            "memory_id": entry.id,
            "memory_type": entry.memory_type,
            "importance": entry.importance,
            "tags": entry.tags,
            "associations": entry.associations,
            "total_memories": len(session.long_term_memories),
            "status": "stored",
        }, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Recall Memories
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_recall",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_recall(params: RecallInput) -> str:
    """Recall relevant memories from the session's long-term memory.

    Uses TF-overlap scoring with recency decay, importance weighting,
    and access frequency bonuses to rank memories by relevance.

    Args:
        params (RecallInput): Contains session_id, query, max_results, and optional type filter.

    Returns:
        str: JSON array of relevant memories ranked by relevance.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        query_words = tokenize(params.query)

        candidates = session.long_term_memories
        if params.memory_type:
            candidates = [m for m in candidates if m.memory_type == params.memory_type]

        scored = []
        for mem in candidates:
            relevance = compute_memory_relevance(query_words, mem)
            if relevance > 0.05:
                mem.access_count += 1
                scored.append({
                    "memory_id": mem.id,
                    "content": mem.content,
                    "memory_type": mem.memory_type,
                    "importance": mem.importance,
                    "relevance_score": relevance,
                    "tags": mem.tags,
                    "timestamp": mem.timestamp,
                    "access_count": mem.access_count,
                })

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return json.dumps({
            "query": params.query,
            "results": scored[:params.max_results],
            "total_searched": len(candidates),
            "total_matched": len(scored),
        }, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Store Belief (with contradiction detection)
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_store_belief",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_store_belief(params: StoreBeliefInput) -> str:
    """Record a belief or fact about an entity, with automatic contradiction detection.

    If the new value contradicts an existing belief for the same entity+attribute,
    the contradiction is logged and returned. Beliefs are used to maintain
    factual coherence across the conversation.

    Args:
        params (StoreBeliefInput): Contains session_id, entity, attribute, value, confidence.

    Returns:
        str: JSON with stored belief details and any contradiction detected.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        # Check for contradiction
        contradiction = detect_contradiction(
            session, params.entity, params.attribute, params.value, params.confidence
        )

        # Store the belief (update or create)
        entry = BeliefEntry(
            entity=params.entity,
            attribute=params.attribute,
            value=params.value,
            confidence=params.confidence,
            timestamp=iso_utc_now(),
            source_turn=session.turn_count,
        )
        session.belief_graph[params.entity][params.attribute] = entry

        result: Dict[str, Any] = {
            "entity": params.entity,
            "attribute": params.attribute,
            "value": params.value,
            "confidence": params.confidence,
            "status": "stored",
        }

        if contradiction:
            result["contradiction_detected"] = True
            result["contradiction"] = contradiction
            result["resolution_strategies"] = [
                "recency_bias: Trust the newer information (current approach — the belief was updated).",
                "confidence_weighted: Compare confidence scores to decide which to trust.",
                "acknowledge_change: Explicitly note the change in conversation.",
                "persona_consistent: Choose the value that aligns with the persona's worldview.",
            ]
        else:
            result["contradiction_detected"] = False

        return json.dumps(result, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Get Coherence State
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_get_coherence_state",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def psy_get_coherence_state(params: SessionIdInput) -> str:
    """Get the full coherence state of a session.

    Returns multi-dimensional coherence scores (topic, memory, belief, profile stability),
    current dialogue phase, topic tracking state, user personality profile,
    contradiction log, and session statistics.

    Args:
        params (SessionIdInput): Contains session_id.

    Returns:
        str: JSON with comprehensive session coherence state.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        coherence = compute_coherence_score(session)

        return json.dumps({
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "turn_count": session.turn_count,
            "dialogue_phase": session.dialogue_phase,
            "coherence_scores": coherence,
            "topic_state": {
                "current_topic": session.topic_state.current_topic,
                "topic_history": session.topic_state.topic_history[-10:],
                "transition_type": session.topic_state.transition_type,
                "topic_confidence": session.topic_state.topic_confidence,
            },
            "user_profile": session.user_profile.to_dict(),
            "memory_stats": {
                "short_term_entries": len(session.short_term_memory),
                "long_term_entries": len(session.long_term_memories),
            },
            "belief_stats": {
                "total_entities": len(session.belief_graph),
                "total_beliefs": sum(len(attrs) for attrs in session.belief_graph.values()),
                "total_contradictions": len(session.contradiction_log),
            },
            "contradiction_log": session.contradiction_log[-5:],
            "created_at": session.created_at,
        }, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Humanize Text
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_humanize_text",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def psy_humanize_text(params: HumanizeInput) -> str:
    """Apply humanization to clean text: disfluencies, persona voice markers, and prosody hints.

    Transforms polished text into something that sounds like a specific persona
    actually speaking. Calibrates disfluency patterns based on persona personality
    traits and optional emotional context.

    Args:
        params (HumanizeInput): Contains text, persona_id, disfluency_level, optional emotion.

    Returns:
        str: JSON with humanized_text, list of modifications made, and prosody hints.
    """
    if params.persona_id not in PERSONAS:
        available = ", ".join(PERSONAS.keys())
        return json.dumps({"error": f"Unknown persona '{params.persona_id}'. Available: {available}"})

    persona = PERSONAS[params.persona_id]
    mood = None
    if params.emotional_context:
        mood = {
            "primary_emotion": params.emotional_context,
            "emotion_intensity": params.emotion_intensity or 0.5,
        }

    result = humanize_text(params.text, persona, mood, params.disfluency_level)
    result["persona_used"] = params.persona_id
    return json.dumps(result, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: End Session
# ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="psy_end_session",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def psy_end_session(params: SessionIdInput) -> str:
    """End a dialogue session and return a comprehensive summary.

    Returns session statistics including total turns, average coherence,
    emotional trajectory, topic coverage, contradiction count, and
    final user personality profile estimate.

    The session is removed from memory after this call.

    Args:
        params (SessionIdInput): Contains session_id.

    Returns:
        str: JSON session summary with all statistics.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        # Compute final stats
        coherence = compute_coherence_score(session)

        # Emotional trajectory
        emotional_trajectory = []
        for entry in session.response_history:
            emotional_trajectory.append({
                "turn": entry["turn"],
                "emotion": entry["primary_emotion"],
                "phase": entry["phase"],
            })

        # Average coherence across responses
        avg_coherence = 0.0
        if session.response_history:
            avg_coherence = round(
                sum(r.get("coherence", 0) for r in session.response_history) / len(session.response_history), 3
            )
        ended_at = utc_now()
        duration_since_creation: Optional[float] = None
        try:
            created_at = parse_timestamp(session.created_at)
            duration_since_creation = round(max((ended_at - created_at).total_seconds(), 0.0), 3)
        except (ValueError, TypeError):
            pass

        summary = {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "persona_name": PERSONAS[session.persona_id]["name"],
            "total_turns": session.turn_count,
            "created_at": session.created_at,
            "ended_at": ended_at.isoformat(),
            "duration_since_creation": duration_since_creation,
            "final_coherence": coherence,
            "average_coherence": avg_coherence,
            "final_user_profile": session.user_profile.to_dict(),
            "emotional_trajectory": emotional_trajectory,
            "topic_coverage": session.topic_state.topic_history,
            "total_memories_stored": len(session.long_term_memories),
            "total_beliefs_tracked": sum(len(attrs) for attrs in session.belief_graph.values()),
            "total_contradictions": len(session.contradiction_log),
            "contradictions": session.contradiction_log,
            "status": "ended",
        }

    # Cleanup
    async with SESSIONS_LOCK:
        if SESSIONS.get(params.session_id) is session:
            del SESSIONS[params.session_id]

    return json.dumps(summary, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Build Generation Constraints (standalone)
# ─────────────────────────────────────────────────────────────────────

class BuildConstraintsInput(BaseModel):
    """Input for building generation constraints from analysis."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: str = Field(..., description="Active session ID.", min_length=1, max_length=100)
    user_text: str = Field(..., description="User text to analyze for constraint building.", min_length=1, max_length=10000)


@mcp.tool(
    name="psy_build_constraints",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def psy_build_constraints(params: BuildConstraintsInput) -> str:
    """Build generation constraints from user text analysis without running the full pipeline.

    Useful when you want fine-grained control: analyze first, then decide
    how to apply the constraints yourself. Returns tone, structural, content,
    and avoidance directives calibrated to both the user's psychological state
    and the session persona's voice.

    Args:
        params (BuildConstraintsInput): Contains session_id and user_text.

    Returns:
        str: JSON generation constraints with persona voice, tone directives, and more.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        persona = PERSONAS[session.persona_id]
        analysis = full_analysis(params.user_text)
        constraints = build_generation_constraints(analysis, persona, session)
        constraints["psychological_analysis_summary"] = {
            "primary_emotion": analysis["mood_state"]["primary_emotion"],
            "emotion_intensity": analysis["mood_state"]["emotion_intensity"],
            "valence": analysis["mood_state"]["valence"],
            "arousal": analysis["mood_state"]["arousal"],
            "detected_needs": analysis["mood_state"]["detected_needs"],
            "formality": analysis["mood_state"]["formality_level"],
            "directness": analysis["mood_state"]["directness_level"],
        }
        return json.dumps(constraints, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
