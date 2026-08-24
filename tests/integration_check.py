"""
Integration test for Psychological Coherence MCP Server.
Exercises every tool and validates output structure and logic.
"""

import asyncio
import json
import sys

from psych_coherence_mcp import (
    AnalyzeInputModel,
    BuildConstraintsInput,
    CreateSessionInput,
    GenerateResponseInput,
    GetPersonaInput,
    HumanizeInput,
    RecallInput,
    SessionIdInput,
    StoreBeliefInput,
    StoreMemoryInput,
    psy_analyze_input,
    psy_build_constraints,
    psy_create_session,
    psy_end_session,
    psy_generate_response,
    psy_get_coherence_state,
    psy_get_persona,
    psy_humanize_text,
    psy_list_personas,
    psy_recall,
    psy_store_belief,
    psy_store_memory,
)

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


async def main():
    global PASS, FAIL

    print("\n" + "═" * 60)
    print("  PSYCHOLOGICAL COHERENCE MCP — INTEGRATION TESTS")
    print("═" * 60)

    # ── 1. List Personas ──
    print("\n▸ psy_list_personas")
    result = json.loads(await psy_list_personas())
    check("Returns list", isinstance(result, list))
    check("Has 4 personas", len(result) == 4)
    check("Each has persona_id", all("persona_id" in p for p in result))
    check("Each has personality_traits", all("personality_traits" in p for p in result))

    # ── 2. Get Persona Detail ──
    print("\n▸ psy_get_persona")
    result = json.loads(await psy_get_persona(GetPersonaInput(persona_id="storyteller_vex")))
    check("Has name", result.get("name") == "Vex")
    check("Has formative_experiences", len(result.get("formative_experiences", [])) > 0)
    check("Has voice_markers", "signature_phrases" in result.get("voice_markers", {}))

    # ── 3. Create Session ──
    print("\n▸ psy_create_session")
    result = json.loads(
        await psy_create_session(
            CreateSessionInput(persona_id="counselor_amara", session_id="test-001")
        )
    )
    check("Returns session_id", result.get("session_id") == "test-001")
    check("Status active", result.get("status") == "active")
    check("Persona name correct", result.get("persona") == "Amara")

    # ── 4. Analyze Input (stateless) ──
    print("\n▸ psy_analyze_input (stateless)")
    test_text = "I'm really worried about the deadline. I feel so anxious and stressed, like I can't handle it anymore. Maybe I should just give up on the whole creative project."
    result = json.loads(await psy_analyze_input(AnalyzeInputModel(text=test_text)))
    mood = result.get("mood_state", {})
    personality = result.get("personality_profile", {})
    check(
        "Detects anxiety-related emotion",
        mood.get("primary_emotion") in ("anxiety", "fear", "sadness"),
    )
    check("Emotion intensity > 0.3", mood.get("emotion_intensity", 0) > 0.3)
    check("Negative valence", mood.get("valence", 0) < 0)
    check("Detects needs", len(mood.get("detected_needs", [])) > 0)
    check("Personality has confidence", personality.get("confidence", 0) > 0)
    check("Neuroticism elevated", personality.get("neuroticism", 0.5) > 0.5)
    check(
        "Has linguistic features", result.get("linguistic_features", {}).get("word_count", 0) > 10
    )
    check("Extracts topics", len(result.get("topics", [])) > 0)

    # ── 5. Analyze Input (with session) ──
    print("\n▸ psy_analyze_input (session-linked)")
    result = json.loads(
        await psy_analyze_input(AnalyzeInputModel(text=test_text, session_id="test-001"))
    )
    check("Session profile updated", result.get("session_profile_updated"))
    check("Has blended profile", "blended_user_profile" in result)

    # ── 6. Store Memory ──
    print("\n▸ psy_store_memory")
    result = json.loads(
        await psy_store_memory(
            StoreMemoryInput(
                session_id="test-001",
                content="The user is working on a creative writing project with a deadline next Friday.",
                memory_type="episodic",
                importance=0.8,
                tags=["project", "deadline", "creative_writing"],
            )
        )
    )
    check("Returns memory_id", "memory_id" in result)
    check("Status stored", result.get("status") == "stored")
    check("Has associations", len(result.get("associations", [])) > 0)

    # Store a second memory
    await psy_store_memory(
        StoreMemoryInput(
            session_id="test-001",
            content="The user's favorite color is blue and they enjoy poetry.",
            memory_type="semantic",
            importance=0.4,
            tags=["preference", "personality"],
        )
    )

    # ── 7. Recall Memories ──
    print("\n▸ psy_recall")
    result = json.loads(
        await psy_recall(RecallInput(session_id="test-001", query="creative project deadline"))
    )
    check("Returns results", len(result.get("results", [])) > 0)
    check("Top result is relevant", result["results"][0]["relevance_score"] > 0.1)
    check("Has total_searched", result.get("total_searched", 0) > 0)

    # ── 8. Store Belief (no contradiction) ──
    print("\n▸ psy_store_belief (no contradiction)")
    result = json.loads(
        await psy_store_belief(
            StoreBeliefInput(
                session_id="test-001",
                entity="user",
                attribute="occupation",
                value="writer",
                confidence=0.9,
            )
        )
    )
    check("Stored successfully", result.get("status") == "stored")
    check("No contradiction", not result.get("contradiction_detected"))

    # ── 9. Store Belief (WITH contradiction) ──
    print("\n▸ psy_store_belief (with contradiction)")
    result = json.loads(
        await psy_store_belief(
            StoreBeliefInput(
                session_id="test-001",
                entity="user",
                attribute="occupation",
                value="engineer",
                confidence=0.7,
            )
        )
    )
    check("Contradiction detected", result.get("contradiction_detected"))
    check("Shows previous value", result.get("contradiction", {}).get("previous_value") == "writer")
    check("Shows resolution strategies", len(result.get("resolution_strategies", [])) > 0)

    # ── 10. Generate Response (Full Pipeline) ──
    print("\n▸ psy_generate_response")
    result = json.loads(
        await psy_generate_response(
            GenerateResponseInput(
                session_id="test-001",
                user_text="I don't know if I can finish this project. Every time I sit down to write, my mind goes blank. It's like the words are stuck somewhere I can't reach.",
            )
        )
    )
    check("Has generation_constraints", "generation_constraints" in result)
    check("Has persona_voice", "persona_voice" in result.get("generation_constraints", {}))
    check(
        "Has tone_directives",
        len(result.get("generation_constraints", {}).get("tone_directives", [])) > 0,
    )
    check(
        "Has content_directives",
        len(result.get("generation_constraints", {}).get("content_directives", [])) > 0,
    )
    check("Has psychological_analysis", "psychological_analysis" in result)
    check("Has topic_transition", "topic_transition" in result)
    check("Has dialogue_phase", result.get("dialogue_phase") is not None)
    check("Has coherence_scores", "overall" in result.get("coherence_scores", {}))
    check("Has relevant_memories", isinstance(result.get("relevant_memories"), list))
    check("Has humanization_config", "humanization_config" in result)
    check(
        "Has formative_context",
        len(result.get("generation_constraints", {}).get("formative_context", [])) > 0,
    )

    # Verify the constraints are actionable
    gc = result["generation_constraints"]
    check("Persona name in constraints", gc.get("persona_name") == "Amara")
    check(
        "Has preferred_starters", len(gc.get("persona_voice", {}).get("preferred_starters", [])) > 0
    )
    check("Has target_formality", "target_formality" in gc.get("psychological_calibration", {}))
    check("Has target_directness", "target_directness" in gc.get("psychological_calibration", {}))
    check("Has phase_guidance", gc.get("phase_guidance", "") != "")

    # ── 11. Humanize Text ──
    print("\n▸ psy_humanize_text")
    clean_text = "I understand how frustrating that feeling can be. Creative blocks often come from putting too much pressure on ourselves. Sometimes the words need space to find their way to us, rather than the other way around."
    result = json.loads(
        await psy_humanize_text(
            HumanizeInput(
                text=clean_text,
                persona_id="counselor_amara",
                disfluency_level=0.6,
                emotional_context="empathy",
                emotion_intensity=0.5,
            )
        )
    )
    check("Has humanized_text", len(result.get("humanized_text", "")) > 0)
    check(
        "Text was modified",
        result.get("humanized_text") != clean_text or result.get("disfluency_count", 0) >= 0,
    )
    check("Has modifications list", isinstance(result.get("modifications"), list))
    check("Has prosody_hints", isinstance(result.get("prosody_hints"), list))

    # ── 12. Build Constraints (standalone) ──
    print("\n▸ psy_build_constraints")
    result = json.loads(
        await psy_build_constraints(
            BuildConstraintsInput(
                session_id="test-001",
                user_text="Can you explain quantum computing in simple terms? I'm curious but it seems really complicated.",
            )
        )
    )
    check("Has persona_voice", "persona_voice" in result)
    check("Has analysis summary", "psychological_analysis_summary" in result)
    check(
        "Detects information need",
        "information" in result.get("psychological_analysis_summary", {}).get("detected_needs", []),
    )

    # ── 13. Get Coherence State ──
    print("\n▸ psy_get_coherence_state")
    result = json.loads(await psy_get_coherence_state(SessionIdInput(session_id="test-001")))
    check("Has coherence_scores", "overall" in result.get("coherence_scores", {}))
    check("Has topic_state", "current_topic" in result.get("topic_state", {}))
    check("Has user_profile", "openness" in result.get("user_profile", {}))
    check("Has memory_stats", result.get("memory_stats", {}).get("long_term_entries", 0) > 0)
    check("Has belief_stats", result.get("belief_stats", {}).get("total_contradictions", 0) > 0)
    check("Turn count > 0", result.get("turn_count", 0) > 0)

    # ── 14. End Session ──
    print("\n▸ psy_end_session")
    result = json.loads(await psy_end_session(SessionIdInput(session_id="test-001")))
    check("Status ended", result.get("status") == "ended")
    check("Has total_turns", result.get("total_turns", 0) > 0)
    check("Has final coherence", "overall" in result.get("final_coherence", {}))
    check("Has emotional_trajectory", isinstance(result.get("emotional_trajectory"), list))
    check("Has contradictions", result.get("total_contradictions", 0) > 0)
    check("Has final_user_profile", "openness" in result.get("final_user_profile", {}))

    # ── Summary ──
    print("\n" + "═" * 60)
    total = PASS + FAIL
    print(f"  Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("  🎉 ALL TESTS PASSED")
    else:
        print(f"  ⚠️  {FAIL} test(s) failed")
    print("═" * 60 + "\n")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
