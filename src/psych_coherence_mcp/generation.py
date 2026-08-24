"""Persona-aware generation constraints and text humanization."""

from __future__ import annotations

import random
from typing import Any

from .analysis import extract_sentences
from .constants import DISFLUENCY_PATTERNS
from .models import Session


def build_generation_constraints(
    analysis: dict[str, Any], persona: dict[str, Any], session: Session
) -> dict[str, Any]:
    """
    Build actionable generation constraints from psychological analysis + persona.
    These constraints guide an LLM on HOW to respond in-character.
    """
    mood = analysis.get("mood_state", {})
    personality = analysis.get("personality_profile", {})
    needs = mood.get("detected_needs", [])
    triggers = mood.get("potential_triggers", [])
    mood.get("primary_emotion", "neutral")
    emotion_intensity = mood.get("emotion_intensity", 0.0)
    formality_score = mood.get("formality_score", 0.5)
    directness_score = mood.get("directness_score", 0.5)

    persona_style = persona.get("communication_style", {})
    persona.get("personality_traits", {})
    voice = persona.get("voice_markers", {})
    patterns = persona.get("response_patterns", {})
    experiences = persona.get("formative_experiences", [])

    constraints: dict[str, Any] = {
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
        constraints["persona_voice"]["approach"] = patterns.get(
            "under_pressure", "grounding_and_validation"
        )
        constraints["tone_directives"].append(
            "Acknowledge the strong emotions before addressing content."
        )
    elif any(t in triggers for t in ["criticism", "shame", "abandonment"]):
        constraints["persona_voice"]["approach"] = patterns.get(
            "under_pressure", "grounding_and_validation"
        )
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
        constraints["tone_directives"].append(
            approach_tones.get(approach, approach_tones["balanced"])
        )

    # ── Emotional tone calibration ──
    valence = mood.get("valence", 0.0)
    arousal = mood.get("arousal", 0.0)

    if valence < -0.3 and arousal > 0.5:
        # Distressed (negative + activated): calm, validate, ground
        constraints["tone_directives"].extend(
            [
                "Use a calm, steady tone to counterbalance high emotional activation.",
                "Validate the emotion explicitly before offering perspective.",
                "Keep sentences short and grounding.",
            ]
        )
    elif valence < -0.3 and arousal <= 0.5:
        # Despondent (negative + low arousal): warm, gently energize
        constraints["tone_directives"].extend(
            [
                "Use warm, gentle language — not cheerful, but present.",
                "Avoid minimizing the feeling; sit with it before moving forward.",
            ]
        )
    elif valence > 0.3 and arousal > 0.5:
        # Excited (positive + activated): match energy judiciously
        constraints["tone_directives"].extend(
            [
                "Mirror some of the positive energy without being sycophantic.",
                f"The persona's emotional expressiveness is {persona_style.get('emotional_expressiveness', 0.5):.1f}/1.0 — calibrate accordingly.",
            ]
        )
    elif valence > 0.3 and arousal <= 0.5:
        # Content (positive + calm): affirm, deepen
        constraints["tone_directives"].append(
            "This is a good moment for deeper exploration or gentle challenge."
        )

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
    persona_formality = {
        "formal": 0.8,
        "warm_professional": 0.6,
        "technical_accessible": 0.55,
        "lyrical_casual": 0.35,
        "plain_spoken": 0.3,
    }.get(persona_style.get("formality", "neutral"), 0.5)
    target_formality = round(formality_score * 0.4 + persona_formality * 0.6, 2)
    constraints["psychological_calibration"]["target_formality"] = target_formality
    if target_formality > 0.7:
        constraints["structural_directives"].append(
            "Use complete sentences, proper grammar, and measured language."
        )
    elif target_formality < 0.3:
        constraints["structural_directives"].append(
            "Use natural, conversational language. Contractions are fine."
        )

    # ── Directness calibration ──
    persona_directness = persona_style.get("directness", 0.5)
    target_directness = round(directness_score * 0.3 + persona_directness * 0.7, 2)
    constraints["psychological_calibration"]["target_directness"] = target_directness
    if target_directness > 0.7:
        constraints["structural_directives"].append(
            "Get to the point quickly. Lead with the key insight."
        )
    elif target_directness < 0.3:
        constraints["structural_directives"].append(
            "Approach the core point gradually. Use questions to guide."
        )

    # ── Personality-aware adaptations ──
    user_neuroticism = personality.get("neuroticism", 0.5)
    user_openness = personality.get("openness", 0.5)
    user_agreeableness = personality.get("agreeableness", 0.5)

    if user_neuroticism > 0.7:
        constraints["content_directives"].append(
            "Provide extra reassurance and structure. Avoid ambiguity."
        )
        constraints["avoidance_directives"].append(
            "Avoid uncertainty-heavy phrasing or overwhelming options."
        )
    if user_openness < 0.3:
        constraints["content_directives"].append(
            "Stay concrete and practical. Avoid abstract metaphors."
        )
    if user_openness > 0.7 and persona_style.get("metaphor_usage", 0) > 0.5:
        constraints["content_directives"].append("Feel free to use metaphor and creative framing.")
    if user_agreeableness < 0.3:
        constraints["structural_directives"].append(
            "Be direct and efficient. Respect their independence."
        )

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

    # Safety always outranks persona performance and normal conversational goals.
    safety = analysis.get("safety_assessment", {})
    constraints["safety"] = safety
    if safety.get("requires_safety_first_response"):
        constraints["priority"] = "safety_first"
        constraints["tone_directives"] = safety.get("response_directives", []) + constraints.get(
            "tone_directives", []
        )
        constraints["avoidance_directives"] = [
            "Do not role-play, humanize, add playful disfluencies, or continue the ordinary task before addressing immediate safety.",
            "Do not claim to diagnose, guarantee confidentiality, or promise that everything will be fine.",
            *constraints.get("avoidance_directives", []),
        ]

    return constraints


# ─────────────────────────────────────────────────────────────────────
# Humanization Engine
# ─────────────────────────────────────────────────────────────────────


def humanize_text(
    text: str,
    persona: dict[str, Any],
    mood: dict[str, Any] | None = None,
    disfluency_level: float = 0.3,
) -> dict[str, Any]:
    """
    Apply humanization: disfluencies, persona voice markers, prosody hints.
    This transforms 'clean' text into something that sounds like a real person speaking.
    """
    if not text or not text.strip():
        return {"humanized_text": text, "modifications": [], "prosody_hints": []}

    modifications = []
    sentences = extract_sentences(text)
    persona.get("communication_style", {})
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
    if (
        humanized
        and any(character.isalnum() for character in humanized)
        and random.random() < 0.25
        and voice.get("preferred_starters")
    ):
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
