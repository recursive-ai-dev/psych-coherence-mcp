"""Print coherence changes across a short sample conversation."""

import asyncio
import json

from psych_coherence_mcp import (
    CreateSessionInput,
    GenerateResponseInput,
    SessionIdInput,
    psy_create_session,
    psy_generate_response,
    psy_get_coherence_state,
)


async def main() -> None:
    session_id = "sim-001"
    created = json.loads(
        await psy_create_session(
            CreateSessionInput(persona_id="counselor_amara", session_id=session_id)
        )
    )
    if created.get("status") != "active":
        raise RuntimeError(created.get("error", "Could not create the simulation session."))
    print("Session created.")

    turns = [
        "Hi, I'm feeling a bit anxious about my upcoming project.",
        "Yes, the deadline is next week and I haven't started.",
        "I'm usually good at this, but I've been procrastinating.",
        "Maybe I should just break it down into smaller tasks?",
    ]

    for turn in turns:
        print(f"\nUser: {turn}")
        await psy_generate_response(GenerateResponseInput(session_id=session_id, user_text=turn))
        state = json.loads(await psy_get_coherence_state(SessionIdInput(session_id=session_id)))
        print(f"Coherence scores: {state['coherence_scores']}")


if __name__ == "__main__":
    asyncio.run(main())
