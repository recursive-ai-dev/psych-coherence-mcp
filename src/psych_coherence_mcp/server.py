"""FastMCP server and psychological coherence tool implementations."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import asdict
from typing import Any

import mcp.server.fastmcp.server as _fastmcp_server
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .analysis import (
    assess_conversational_safety,
    extract_memory_candidates,
    extract_topics,
    full_analysis,
    tokenize,
)
from .coherence import (
    blend_profiles,
    compute_coherence_score,
    compute_memory_relevance,
    detect_contradiction,
    update_dialogue_phase,
    update_topic_state,
)
from .constants import (
    MAX_ACTIVE_SESSIONS,
    MAX_BELIEFS_PER_SESSION,
    MAX_MEMORIES_PER_SESSION,
    MAX_SESSION_HISTORY,
    PERSONAS,
)
from .generation import build_generation_constraints, humanize_text
from .models import BeliefEntry, MemoryEntry, PersonalityProfile, Session
from .schemas import (
    AnalyzeInputModel,
    BuildConstraintsInput,
    CreateSessionInput,
    GenerateResponseInput,
    GetPersonaInput,
    HumanizeInput,
    ImportSessionInput,
    RecallInput,
    RecordResponseInput,
    SafetyAssessmentInput,
    SessionIdInput,
    StoreBeliefInput,
    StoreMemoryInput,
)
from .state import (
    SESSIONS,
    SESSIONS_LOCK,
    _get_session,
    _restore_session,
    _session_snapshot,
)
from .utils import iso_utc_now, parse_timestamp, utc_now

# MCP 1.x currently leaves Settings.lifespan as a forward reference. Rebuild it
# before constructing FastMCP so pydantic-settings can inspect the field without
# emitting IncompleteFieldDefinitionWarning on every import.
_fastmcp_server.Settings.model_rebuild(_types_namespace=vars(_fastmcp_server))

logger = logging.getLogger("psychological_coherence_mcp")
logger.addHandler(logging.NullHandler())

mcp = FastMCP("psychological_coherence_mcp")


def _trim_history(items: list[Any]) -> None:
    """Bound retained session history without affecting current-turn processing."""
    if len(items) > MAX_SESSION_HISTORY:
        del items[: len(items) - MAX_SESSION_HISTORY]


# ─────────────────────────────────────────────────────────────────────
# Tool: List Personas
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_list_personas",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
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
        summaries.append(
            {
                "persona_id": pid,
                "name": p["name"],
                "description": p["description"],
                "personality_traits": p["personality_traits"],
                "communication_style_summary": {
                    "formality": p["communication_style"]["formality"],
                    "directness": p["communication_style"]["directness"],
                    "emotional_expressiveness": p["communication_style"][
                        "emotional_expressiveness"
                    ],
                },
                "emotional_triggers": p["emotional_triggers"],
            }
        )
    return json.dumps(summaries, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Get Persona Detail
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_get_persona",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
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
        return json.dumps(
            {"error": f"Unknown persona '{params.persona_id}'. Available: {available}"}
        )
    return json.dumps(PERSONAS[params.persona_id], indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Create Session
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_create_session",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
        sid = params.session_id or str(uuid.uuid4())[:12]
        async with SESSIONS_LOCK:
            if sid in SESSIONS:
                return json.dumps(
                    {
                        "error": f"Session '{sid}' already exists. Use a different ID or end the existing session."
                    }
                )
            if len(SESSIONS) >= MAX_ACTIVE_SESSIONS:
                return json.dumps(
                    {
                        "status": "limit_reached",
                        "error": (
                            "The active session limit has been reached. End or export an "
                            "existing session before creating another."
                        ),
                    }
                )
            session = Session(
                session_id=sid,
                persona_id=params.persona_id,
                created_at=iso_utc_now(),
            )
            SESSIONS[sid] = session

        persona = PERSONAS[params.persona_id]
        return json.dumps(
            {
                "session_id": sid,
                "persona": persona["name"],
                "persona_id": params.persona_id,
                "description": persona["description"],
                "status": "active",
                "message": f"Session created. {persona['name']} is ready.",
            },
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error in psy_create_session: {e}", exc_info=True)
        return json.dumps({"error": str(e), "tool": "psy_create_session"}, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: Analyze Input
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_analyze_input",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
                new_profile = PersonalityProfile(
                    **{k: v for k, v in result["personality_profile"].items()}
                )

                # Blend with existing (new data gets lower weight as more data accumulates)
                weight = max(0.15, 1.0 / (1.0 + session.turn_count * 0.3))
                session.user_profile = blend_profiles(session.user_profile, new_profile, weight)
                session.user_profile_history.append(
                    PersonalityProfile(**asdict(session.user_profile))
                )
                _trim_history(session.user_profile_history)

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
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
        session.updated_at = iso_utc_now()

        # Step 1: Analyze user input
        analysis = full_analysis(params.user_text)

        # Step 2: Update running user profile
        new_profile = PersonalityProfile(
            **{k: v for k, v in analysis["personality_profile"].items()}
        )
        weight = max(0.15, 1.0 / (1.0 + session.turn_count * 0.3))
        session.user_profile = blend_profiles(session.user_profile, new_profile, weight)
        session.user_profile_history.append(PersonalityProfile(**asdict(session.user_profile)))
        _trim_history(session.user_profile_history)

        # Step 3: Update topic tracking
        topic_transition = update_topic_state(session, analysis.get("topics", []))

        # Step 4: Update dialogue phase
        dialogue_phase = update_dialogue_phase(session, analysis, params.user_text)

        # Step 5: Store in short-term memory
        session.short_term_memory.append(
            {
                "turn": session.turn_count,
                "role": "user",
                "text": params.user_text[:500],
                "primary_emotion": analysis["mood_state"]["primary_emotion"],
                "topics": analysis.get("topics", [])[:3],
                "timestamp": iso_utc_now(),
            }
        )

        # Step 6: Recall relevant long-term memories
        query_words = tokenize(params.user_text)
        ranked_memories = []
        for mem in session.long_term_memories:
            relevance = compute_memory_relevance(query_words, mem)
            if relevance > 0.1:
                ranked_memories.append((relevance, mem))
        ranked_memories.sort(key=lambda item: item[0], reverse=True)
        relevant_memories = []
        for relevance, mem in ranked_memories[:5]:
            mem.access_count += 1
            relevant_memories.append(
                {
                    "memory_id": mem.id,
                    "content": mem.content,
                    "type": mem.memory_type,
                    "importance": mem.importance,
                    "relevance_score": relevance,
                    "tags": mem.tags,
                }
            )

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
            "active_contradictions": session.contradiction_log[-3:]
            if session.contradiction_log
            else [],
        }

        # Record this response generation
        session.response_history.append(
            {
                "turn": session.turn_count,
                "user_text": params.user_text[:200],
                "phase": dialogue_phase,
                "primary_emotion": analysis["mood_state"]["primary_emotion"],
                "risk_level": analysis["safety_assessment"]["risk_level"],
                "coherence": coherence["overall"],
                "timestamp": iso_utc_now(),
            }
        )
        _trim_history(session.response_history)

        return json.dumps(brief, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# Tool: Store Memory
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_store_memory",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
        if len(session.long_term_memories) >= MAX_MEMORIES_PER_SESSION:
            return json.dumps(
                {
                    "status": "limit_reached",
                    "error": (
                        "The session memory limit has been reached. Export and start a "
                        "new session before storing more memories."
                    ),
                },
                indent=2,
            )
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content={"text": params.content},
            memory_type=params.memory_type,
            timestamp=iso_utc_now(),
            importance=params.importance,
            tags=params.tags or [],
            associations=extract_topics(params.content)[:4],
        )
        session.long_term_memories.append(entry)

        return json.dumps(
            {
                "memory_id": entry.id,
                "memory_type": entry.memory_type,
                "importance": entry.importance,
                "tags": entry.tags,
                "associations": entry.associations,
                "total_memories": len(session.long_term_memories),
                "status": "stored",
            },
            indent=2,
        )


# ─────────────────────────────────────────────────────────────────────
# Tool: Recall Memories
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_recall",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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

        ranked = []
        for mem in candidates:
            relevance = compute_memory_relevance(query_words, mem)
            if relevance > 0.05:
                ranked.append((relevance, mem))

        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = ranked[: params.max_results]
        scored = []
        for relevance, mem in selected:
            mem.access_count += 1
            scored.append(
                {
                    "memory_id": mem.id,
                    "content": mem.content,
                    "memory_type": mem.memory_type,
                    "importance": mem.importance,
                    "relevance_score": relevance,
                    "tags": mem.tags,
                    "timestamp": mem.timestamp,
                    "access_count": mem.access_count,
                }
            )

        return json.dumps(
            {
                "query": params.query,
                "results": scored,
                "total_searched": len(candidates),
                "total_matched": len(ranked),
            },
            indent=2,
        )


# ─────────────────────────────────────────────────────────────────────
# Tool: Store Belief (with contradiction detection)
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_store_belief",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
        belief_exists = (
            params.entity in session.belief_graph
            and params.attribute in session.belief_graph[params.entity]
        )
        belief_count = sum(len(attributes) for attributes in session.belief_graph.values())
        if not belief_exists and belief_count >= MAX_BELIEFS_PER_SESSION:
            return json.dumps(
                {
                    "status": "limit_reached",
                    "error": "The session belief limit has been reached.",
                },
                indent=2,
            )

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

        result: dict[str, Any] = {
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
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
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

        return json.dumps(
            {
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
                "contradictions_detected": session.contradiction_log[-5:],
                "created_at": session.created_at,
            },
            indent=2,
            default=str,
        )


# ─────────────────────────────────────────────────────────────────────
# Tool: Humanize Text
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_humanize_text",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
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
        return json.dumps(
            {"error": f"Unknown persona '{params.persona_id}'. Available: {available}"}
        )

    persona = PERSONAS[params.persona_id]
    mood = None
    if params.emotional_context:
        mood = {
            "primary_emotion": params.emotional_context,
            "emotion_intensity": (
                params.emotion_intensity if params.emotion_intensity is not None else 0.5
            ),
        }

    result = humanize_text(params.text, persona, mood, params.disfluency_level)
    result["persona_used"] = params.persona_id
    return json.dumps(result, indent=2)


# ─────────────────────────────────────────────────────────────────────
# Tool: End Session
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_end_session",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
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
    async with SESSIONS_LOCK:
        session = SESSIONS.get(params.session_id)
    if session is None:
        return json.dumps(
            {
                "session_id": params.session_id,
                "status": "not_found",
                "error": "Session is not active; it may already have ended.",
            },
            indent=2,
        )

    async with session.session_lock:
        # Compute final stats
        coherence = compute_coherence_score(session)

        # Imported snapshots may come from older versions with partial history.
        emotional_trajectory = [
            {
                "turn": entry.get("turn"),
                "emotion": entry.get("primary_emotion", "unknown"),
                "phase": entry.get("phase", "unknown"),
            }
            for entry in session.response_history
            if isinstance(entry, dict)
        ]

        # Average coherence across responses
        avg_coherence = 0.0
        coherence_values = [
            entry["coherence"]
            for entry in session.response_history
            if isinstance(entry, dict) and isinstance(entry.get("coherence"), (int, float))
        ]
        if coherence_values:
            avg_coherence = round(sum(coherence_values) / len(coherence_values), 3)
        ended_at = utc_now()
        duration_since_creation: float | None = None
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


@mcp.tool(
    name="psy_build_constraints",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
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
# Additional safety, response lifecycle, and portability tools
# ─────────────────────────────────────────────────────────────────────


@mcp.tool(
    name="psy_assess_safety",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def psy_assess_safety(params: SafetyAssessmentInput) -> str:
    """Assess explicit self-harm or violence signals and return response priorities.

    This deterministic triage aid does not diagnose a person and must not replace
    professional judgment. It is useful when a client wants safety guidance without
    running the complete personality and coherence pipeline.
    """
    return json.dumps(assess_conversational_safety(params.text), indent=2)


@mcp.tool(
    name="psy_extract_memories",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def psy_extract_memories(params: AnalyzeInputModel) -> str:
    """Extract reviewable preference, identity, project, and goal memory candidates.

    Candidates are never stored automatically. Review them and explicitly call
    psy_store_memory, which avoids silently retaining sensitive user information.
    """
    candidates = extract_memory_candidates(params.text)
    return json.dumps(
        {"candidates": candidates, "count": len(candidates), "stored": False}, indent=2
    )


@mcp.tool(
    name="psy_record_response",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def psy_record_response(params: RecordResponseInput) -> str:
    """Record the assistant response actually delivered and evaluate basic alignment.

    Calling this after generation closes the conversation-state loop: later briefs
    can see both user and assistant turns instead of user messages alone.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        persona = PERSONAS[session.persona_id]
        words = tokenize(params.response_text)
        voice = persona.get("voice_markers", {})
        all_markers = (
            voice.get("preferred_starters", [])
            + voice.get("hedges", [])
            + voice.get("signature_phrases", [])
        )
        marker_hits = [
            marker for marker in all_markers if marker.lower() in params.response_text.lower()
        ]
        target_words = int(40 + persona.get("communication_style", {}).get("verbosity", 0.5) * 180)
        last_generation = session.response_history[-1] if session.response_history else {}
        safety_required = last_generation.get("risk_level") in {"high", "imminent"}
        safety_terms = [
            "safe",
            "emergency",
            "crisis",
            "call",
            "trusted person",
            "nearby",
            "immediate danger",
        ]
        safety_hits = [term for term in safety_terms if term in params.response_text.lower()]

        recommendations = []
        if len(words) > target_words * 1.8:
            recommendations.append(
                "Shorten the response to better match the persona's target verbosity."
            )
        elif len(words) < max(12, target_words * 0.25):
            recommendations.append(
                "Add enough substance to address the user's need before closing."
            )
        if not marker_hits:
            recommendations.append(
                "Consider one subtle persona voice marker; avoid forcing several."
            )
        if safety_required and len(safety_hits) < 2:
            recommendations.insert(
                0,
                "Safety alignment is insufficient: directly check immediate safety and offer concrete human help.",
            )

        recorded_at = iso_utc_now()
        session.short_term_memory.append(
            {
                "turn": session.turn_count,
                "role": "assistant",
                "text": params.response_text[:500],
                "timestamp": recorded_at,
            }
        )
        session.updated_at = recorded_at
        if session.response_history:
            session.response_history[-1]["assistant_text"] = params.response_text[:500]
            session.response_history[-1]["assistant_recorded_at"] = recorded_at

        return json.dumps(
            {
                "status": "recorded",
                "session_id": session.session_id,
                "turn": session.turn_count,
                "alignment": {
                    "word_count": len(words),
                    "target_word_count": target_words,
                    "persona_marker_hits": marker_hits,
                    "safety_response_required": safety_required,
                    "safety_language_hits": safety_hits,
                    "recommendations": recommendations,
                    "passes_safety_check": not safety_required or len(safety_hits) >= 2,
                },
            },
            indent=2,
        )


@mcp.tool(
    name="psy_list_sessions",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def psy_list_sessions() -> str:
    """List active in-memory sessions with compact lifecycle metadata."""
    async with SESSIONS_LOCK:
        sessions = list(SESSIONS.values())
    result = [
        {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "persona_name": PERSONAS[session.persona_id]["name"],
            "turn_count": session.turn_count,
            "dialogue_phase": session.dialogue_phase,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "last_accessed": session.last_accessed,
        }
        for session in sessions
    ]
    return json.dumps({"sessions": result, "count": len(result)}, indent=2)


@mcp.tool(
    name="psy_export_session",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def psy_export_session(params: SessionIdInput) -> str:
    """Export complete session state as a versioned JSON snapshot.

    The snapshot may contain sensitive conversation text. Store and transmit it
    according to the user's privacy expectations.
    """
    session = await _get_session(params.session_id)
    async with session.session_lock:
        return json.dumps(_session_snapshot(session), indent=2, default=str)


@mcp.tool(
    name="psy_import_session",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def psy_import_session(params: ImportSessionInput) -> str:
    """Restore a validated session snapshot, optionally under a new session ID."""
    try:
        session = _restore_session(params.snapshot, params.new_session_id)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return json.dumps(
            {"status": "invalid_snapshot", "error": str(exc)},
            indent=2,
        )

    async with SESSIONS_LOCK:
        if session.session_id in SESSIONS and not params.overwrite:
            return json.dumps(
                {
                    "error": f"Session '{session.session_id}' already exists; set overwrite=true or choose new_session_id."
                }
            )
        SESSIONS[session.session_id] = session
    return json.dumps(
        {
            "status": "imported",
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "turn_count": session.turn_count,
            "memories_restored": len(session.long_term_memories),
            "beliefs_restored": sum(
                len(attributes) for attributes in session.belief_graph.values()
            ),
        },
        indent=2,
    )


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
