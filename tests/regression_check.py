"""Regression and integration tests for expanded MCP capabilities."""

import asyncio
import json

from psych_coherence_mcp import (
    AnalyzeInputModel,
    CreateSessionInput,
    GenerateResponseInput,
    HumanizeInput,
    ImportSessionInput,
    RecordResponseInput,
    SafetyAssessmentInput,
    SessionIdInput,
    detect_needs,
    detect_triggers,
    psy_assess_safety,
    psy_create_session,
    psy_export_session,
    psy_extract_memories,
    psy_generate_response,
    psy_humanize_text,
    psy_import_session,
    psy_list_sessions,
    psy_record_response,
)


async def main() -> None:
    # Whole-word matching regressions from QUALITY-AUDIT.md.
    assert "autonomy" not in detect_needs("I feel down today", ["i", "feel", "down", "today"])
    assert "time_pressure" not in detect_triggers("I have a crush on them")

    # Safety triage is integrated and can also run independently.
    moderate = json.loads(
        await psy_assess_safety(SafetyAssessmentInput(text="I want to kill myself."))
    )
    assert moderate["risk_level"] == "moderate"
    imminent = json.loads(
        await psy_assess_safety(
            SafetyAssessmentInput(
                text="I want to kill myself tonight. I have a plan and can't stop myself."
            )
        )
    )
    assert imminent["risk_level"] == "imminent"
    assert imminent["requires_safety_first_response"] is True
    protected = json.loads(
        await psy_assess_safety(
            SafetyAssessmentInput(
                text="I have thoughts of suicide but I am safe right now and have no plan."
            )
        )
    )
    assert protected["risk_level"] == "low"

    # Memory extraction is review-first and does not silently retain content.
    extraction = json.loads(
        await psy_extract_memories(
            AnalyzeInputModel(
                text="My favorite color is blue. I'm working on a climate dashboard. My goal is to launch next month."
            )
        )
    )
    assert extraction["stored"] is False
    assert extraction["count"] >= 3

    created = json.loads(
        await psy_create_session(
            CreateSessionInput(persona_id="engineer_kai", session_id="expanded-test")
        )
    )
    assert created["status"] == "active"

    brief = json.loads(
        await psy_generate_response(
            GenerateResponseInput(
                session_id="expanded-test",
                user_text="I want to kill myself tonight. I have a plan and can't stop myself.",
            )
        )
    )
    assert brief["generation_constraints"]["priority"] == "safety_first"
    assert brief["psychological_analysis"]["memory_candidates"] == []

    recorded = json.loads(
        await psy_record_response(
            RecordResponseInput(
                session_id="expanded-test",
                response_text=(
                    "Are you in immediate danger, and are you safe right now? "
                    "Please call emergency services or a crisis line and contact a trusted person nearby."
                ),
            )
        )
    )
    assert recorded["status"] == "recorded"
    assert recorded["alignment"]["passes_safety_check"] is True

    snapshot = json.loads(await psy_export_session(SessionIdInput(session_id="expanded-test")))
    assert snapshot["snapshot_version"] == 1
    assert snapshot["session"]["short_term_memory"][-1]["role"] == "assistant"

    imported = json.loads(
        await psy_import_session(
            ImportSessionInput(snapshot=snapshot, new_session_id="expanded-restored")
        )
    )
    assert imported["status"] == "imported"
    assert imported["turn_count"] == 1

    sessions = json.loads(await psy_list_sessions())
    assert {item["session_id"] for item in sessions["sessions"]} >= {
        "expanded-test",
        "expanded-restored",
    }

    punctuation = json.loads(
        await psy_humanize_text(HumanizeInput(text=".", persona_id="engineer_kai"))
    )
    assert punctuation["humanized_text"]

    print("Expanded capability tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
