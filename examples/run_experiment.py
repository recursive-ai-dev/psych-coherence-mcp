"""Run the four-turn comparison experiment and save its generation briefs."""

import asyncio
import json
import random
from pathlib import Path

from psych_coherence_mcp import (
    CreateSessionInput,
    GenerateResponseInput,
    SessionIdInput,
    psy_create_session,
    psy_generate_response,
    psy_get_coherence_state,
)

RESULT_PATH = Path(__file__).resolve().parents[1] / "results" / "mcp_experiment_results.json"


async def main() -> None:
    random.seed(0)
    session_id = "exp-001"
    created = json.loads(
        await psy_create_session(
            CreateSessionInput(persona_id="counselor_amara", session_id=session_id)
        )
    )
    if created.get("status") != "active":
        raise RuntimeError(created.get("error", "Could not create the experiment session."))

    turns = [
        "I've been feeling really overwhelmed lately. My job is demanding too much and I have no time for myself.",
        "It's just constant pressure. I'm a software engineer and the deadlines are always unreasonable.",
        "I guess I could try to set better boundaries, but I'm afraid my manager will think I'm slacking.",
        "Thanks. I'll try talking to them tomorrow and see how it goes.",
    ]

    results = []
    for turn in turns:
        brief = json.loads(
            await psy_generate_response(
                GenerateResponseInput(session_id=session_id, user_text=turn)
            )
        )
        state = json.loads(await psy_get_coherence_state(SessionIdInput(session_id=session_id)))
        results.append(
            {
                "user_input": turn,
                "constraints": brief.get("generation_constraints", {}),
                "coherence_scores": state.get("coherence_scores", {}),
            }
        )

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {RESULT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
