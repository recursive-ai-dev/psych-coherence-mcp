"""Validated input schemas exposed by MCP tools."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .constants import PERSONAS, SESSION_ID_PATTERN, VALID_MEMORY_TYPES

SessionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=SESSION_ID_PATTERN,
    ),
]


class CreateSessionInput(BaseModel):
    """Input for creating a new dialogue session."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    persona_id: str = Field(
        ...,
        description="ID of the persona to use. Available: 'counselor_amara', 'engineer_kai', 'storyteller_vex', 'mentor_sol'",
        min_length=1,
        max_length=100,
    )
    session_id: SessionId | None = Field(
        default=None,
        description="Optional custom session ID. Auto-generated if omitted.",
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

    text: str = Field(
        ...,
        description="The user's text to analyze psychologically.",
        min_length=1,
        max_length=10000,
    )
    session_id: SessionId | None = Field(
        default=None,
        description="Session ID to update the running user profile. If omitted, analysis is stateless.",
    )


class GenerateResponseInput(BaseModel):
    """Input for the full generation pipeline."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: SessionId = Field(..., description="Active session ID.")
    user_text: str = Field(
        ..., description="The user's input text to respond to.", min_length=1, max_length=10000
    )
    enable_humanization: bool = Field(
        default=True, description="Apply disfluencies and persona voice markers."
    )
    disfluency_level: float = Field(
        default=0.3, description="Disfluency intensity 0.0-1.0.", ge=0.0, le=1.0
    )


class StoreMemoryInput(BaseModel):
    """Input for storing a memory entry."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: SessionId = Field(..., description="Active session ID.")
    content: str = Field(
        ...,
        description="The content to remember (fact, event, emotional moment, etc.).",
        min_length=1,
        max_length=5000,
    )
    memory_type: str = Field(
        default="episodic",
        description="Memory type: 'episodic' (events), 'semantic' (facts), 'procedural' (how-to), 'emotional' (feelings).",
    )
    importance: float = Field(default=0.5, description="Importance score 0.0-1.0.", ge=0.0, le=1.0)
    tags: list[str] | None = Field(
        default_factory=list, description="Tags for categorization.", max_length=20
    )

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

    session_id: SessionId = Field(..., description="Active session ID.")
    query: str = Field(
        ..., description="What to search for in memory.", min_length=1, max_length=1000
    )
    max_results: int = Field(default=5, description="Maximum results to return.", ge=1, le=20)
    memory_type: str | None = Field(default=None, description="Filter by memory type.")

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type_filter(cls, value: str | None) -> str | None:
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

    session_id: SessionId = Field(..., description="Active session ID.")
    entity: str = Field(
        ...,
        description="The entity (person, place, concept) the belief is about.",
        min_length=1,
        max_length=200,
    )
    attribute: str = Field(
        ...,
        description="The attribute being stated (e.g., 'favorite_color', 'occupation').",
        min_length=1,
        max_length=200,
    )
    value: str = Field(..., description="The stated value.", min_length=1, max_length=1000)
    confidence: float = Field(
        default=0.8, description="Confidence in this belief 0.0-1.0.", ge=0.0, le=1.0
    )


class HumanizeInput(BaseModel):
    """Input for humanizing text."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(..., description="Clean text to humanize.", min_length=1, max_length=10000)
    persona_id: str = Field(
        default="counselor_amara",
        description="Persona whose voice to apply.",
    )
    disfluency_level: float = Field(
        default=0.3, description="Disfluency intensity 0.0-1.0.", ge=0.0, le=1.0
    )
    emotional_context: str | None = Field(
        default=None,
        description="Primary emotion to calibrate humanization (e.g., 'anxious', 'excited', 'sad').",
    )
    emotion_intensity: float | None = Field(
        default=None,
        description="Emotion intensity 0.0-1.0.",
        ge=0.0,
        le=1.0,
    )


class SessionIdInput(BaseModel):
    """Input requiring only a session ID."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: SessionId = Field(..., description="Active session ID.")


class SafetyAssessmentInput(BaseModel):
    """Input for standalone conversational safety signal assessment."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    text: str = Field(
        ...,
        description="Text to assess for explicit harm-related signals.",
        min_length=1,
        max_length=10000,
    )


class RecordResponseInput(BaseModel):
    """Input for recording and evaluating the assistant's actual response."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: SessionId = Field(..., description="Active session ID.")
    response_text: str = Field(
        ..., description="The response actually shown to the user.", min_length=1, max_length=10000
    )


class ImportSessionInput(BaseModel):
    """Input for restoring a previously exported session snapshot."""

    model_config = ConfigDict(extra="forbid")
    snapshot: dict[str, Any] = Field(
        ..., description="Snapshot object returned by psy_export_session."
    )
    new_session_id: SessionId | None = None
    overwrite: bool = Field(
        default=False, description="Replace an active session with the same ID."
    )


class GetPersonaInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    persona_id: str = Field(..., description="Persona ID to retrieve.", min_length=1)


class BuildConstraintsInput(BaseModel):
    """Input for building generation constraints from analysis."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    session_id: SessionId = Field(..., description="Active session ID.")
    user_text: str = Field(
        ...,
        description="User text to analyze for constraint building.",
        min_length=1,
        max_length=10000,
    )
