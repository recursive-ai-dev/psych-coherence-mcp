import asyncio
import json
from server import psy_create_session, psy_generate_response, psy_get_coherence_state, CreateSessionInput, GenerateResponseInput, SessionIdInput

async def main():
    session_res = json.loads(await psy_create_session(CreateSessionInput(persona_id="counselor_amara", session_id="sim-001")))
    print("Session created.")

    turns = [
        "Hi, I'm feeling a bit anxious about my upcoming project.",
        "Yes, the deadline is next week and I haven't started.",
        "I'm usually good at this, but I've been procrastinating.",
        "Maybe I should just break it down into smaller tasks?"
    ]

    for turn in turns:
        print(f"\nUser: {turn}")
        res = json.loads(await psy_generate_response(GenerateResponseInput(session_id="sim-001", user_text=turn)))
        state = json.loads(await psy_get_coherence_state(SessionIdInput(session_id="sim-001")))
        scores = state["coherence_scores"]
        print(f"Coherence Scores: {scores}")

if __name__ == "__main__":
    asyncio.run(main())
