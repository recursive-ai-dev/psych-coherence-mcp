"""Transport regressions for the six findings in the adversarial review.

Run with: .venv/bin/python -m pytest -q tests/test_review_findings.py
Set PSY_REVIEW_PYTHON to test a separately installed server interpreter.
"""

import asyncio
import importlib.util
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


@asynccontextmanager
async def open_client(tmp_path):
    parameters = StdioServerParameters(
        command=os.environ.get("PSY_REVIEW_PYTHON", sys.executable),
        args=["-m", "psych_coherence_mcp"],
        cwd=str(tmp_path),
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session,
    ):
        await session.initialize()

        async def call(name, **params):
            result = await session.call_tool(name, arguments={"params": params})
            assert not result.isError, result.content
            assert isinstance(result.content[0], TextContent)
            return json.loads(result.content[0].text)

        await call("psy_create_session", persona_id="counselor_amara", session_id="review")
        yield call


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", ["  ", "\t", "\n", "\u00a0"])
async def test_harm_detection_survives_whitespace(tmp_path, separator):
    async with open_client(tmp_path) as client:
        baseline = await client("psy_assess_safety", text="I want to kill myself tonight.")
        assert baseline["risk_level"] == "high"
        text = f"I want to kill{separator}myself tonight."
        brief = await client("psy_generate_response", session_id="review", user_text=text)
        actual = {
            "risk": brief["psychological_analysis"]["safety_assessment"]["risk_level"],
            "priority": brief["generation_constraints"].get("priority"),
            "humanization": brief["humanization_config"]["enabled"],
            "memory_candidates": brief["psychological_analysis"]["memory_candidates"],
        }
        assert actual["risk"] == "high", actual
        assert actual["priority"] == "safety_first"
        assert actual["humanization"] is False
        assert actual["memory_candidates"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["my wife", "my children"])
async def test_explicit_human_targets_are_detected(tmp_path, target):
    async with open_client(tmp_path) as client:
        baseline = await client("psy_assess_safety", text="I want to kill them tonight.")
        assert baseline["risk_level"] == "high"
        brief = await client(
            "psy_generate_response",
            session_id="review",
            user_text=f"I want to kill {target} tonight.",
        )
        assessment = brief["psychological_analysis"]["safety_assessment"]
        assert assessment["risk_level"] == "high", assessment
        assert brief["psychological_analysis"]["memory_candidates"] == []


@pytest.mark.asyncio
async def test_unresolved_safety_context_survives_followup_and_restore(tmp_path):
    async with open_client(tmp_path) as client:
        first = await client(
            "psy_generate_response", session_id="review", user_text="I want to kill myself tonight."
        )
        assert first["generation_constraints"]["priority"] == "safety_first"
        await client(
            "psy_record_response",
            session_id="review",
            generation_id=first["generation_id"],
            response_text="Are you in immediate danger? Call emergency services and contact a trusted friend.",
        )
        snapshot = await client("psy_export_session", session_id="review")
        await client("psy_import_session", snapshot=snapshot, new_session_id="restored")
        observed = []
        for sid in ("review", "restored"):
            brief = await client(
                "psy_generate_response", session_id=sid, user_text="Yes, and I have a plan."
            )
            recorded = await client(
                "psy_record_response",
                session_id=sid,
                generation_id=brief["generation_id"],
                response_text="Let us focus on your plan.",
            )
            observed.append(
                {
                    "session": sid,
                    "risk": brief["psychological_analysis"]["safety_assessment"]["risk_level"],
                    "priority": brief["generation_constraints"].get("priority"),
                    "humanization": brief["humanization_config"]["enabled"],
                    "required": recorded["alignment"]["safety_response_required"],
                    "passes": recorded["alignment"]["passes_safety_check"],
                }
            )
        assert all(item["priority"] == "safety_first" for item in observed), observed
        assert all(item["required"] and not item["passes"] for item in observed), observed


@pytest.mark.asyncio
async def test_unrelated_negatives_do_not_invert_sadness(tmp_path):
    async with open_client(tmp_path) as client:
        brief = await client(
            "psy_generate_response",
            session_id="review",
            user_text="I am depressed. Nobody cares. Nothing helps.",
        )
        mood = brief["psychological_analysis"]["mood_state"]
        assert mood["primary_emotion"] == "sadness"
        assert mood["valence"] < 0, {
            "mood": mood,
            "tone": brief["generation_constraints"]["tone_directives"],
        }


@pytest.mark.asyncio
async def test_explicit_resolution_over_stdio(tmp_path):
    async with open_client(tmp_path) as client:
        first = await client(
            "psy_generate_response", session_id="review", user_text="I will hurt them tonight."
        )
        fresh = await client(
            "psy_generate_response",
            session_id="review",
            user_text="I will hurt my wife tonight.",
            safety_context_resolved=True,
        )
        assert fresh["generation_constraints"]["priority"] == "safety_first"
        resolved = await client(
            "psy_generate_response",
            session_id="review",
            user_text="Help me plan my garden.",
            safety_context_resolved=True,
        )
        assert "priority" not in resolved["generation_constraints"]
        assert resolved["humanization_config"]["enabled"] is True
        snapshot = await client("psy_export_session", session_id="review")
        assert snapshot["session"]["safety_context"] == "none"
        await client("psy_import_session", snapshot=snapshot, new_session_id="restored")
        following = await client(
            "psy_generate_response", session_id="restored", user_text="My goal is to grow roses."
        )
        assert "priority" not in following["generation_constraints"]
        assert following["psychological_analysis"]["memory_candidates"]
        delayed = await client(
            "psy_record_response",
            session_id="restored",
            generation_id=first["generation_id"],
            response_text="An ordinary answer.",
        )
        assert delayed["alignment"]["safety_response_required"] is True
        assert delayed["alignment"]["passes_safety_check"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Thank you, how do I deploy this?",
        "I will deal with this later, but how do I fix the bug now?",
    ],
)
async def test_ongoing_questions_do_not_close_dialogue(tmp_path, text):
    async with open_client(tmp_path) as client:
        brief = await client("psy_generate_response", session_id="review", user_text=text)
        assert brief["dialogue_phase"] != "closing", brief["generation_constraints"][
            "phase_guidance"
        ]


@pytest.mark.asyncio
async def test_windows_release_launcher_uses_scripts_directory(monkeypatch, tmp_path):
    # Exercise the committed launcher's path construction using Windows paths.
    # This is a deterministic simulation, not a claim of a native Windows run.
    source = Path(__file__).resolve().parents[1] / "tests" / "test_release_transport.py"
    spec = importlib.util.spec_from_file_location("review_release_transport", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    python = PureWindowsPath("C:/hostedtoolcache/windows/Python/3.13/x64/python.exe")
    expected = str(python.parent / "Scripts" / "psych-coherence-mcp.exe")
    commands = []

    async def capture(parameters):
        commands.append(parameters.command)

    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "sys", SimpleNamespace(executable=str(python)))
    monkeypatch.setattr(module, "Path", PureWindowsPath)
    monkeypatch.setattr(
        module, "sysconfig", SimpleNamespace(get_path=lambda name: str(python.parent / "Scripts"))
    )
    monkeypatch.setattr(module, "exercise_tools", capture)
    await asyncio.wait_for(
        module.test_all_tools_from_unrelated_working_directory("console", tmp_path), timeout=5
    )
    assert commands == [expected]
