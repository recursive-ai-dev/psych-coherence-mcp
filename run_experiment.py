import asyncio
import json
from server import psy_create_session, psy_generate_response, psy_get_coherence_state, CreateSessionInput, GenerateResponseInput, SessionIdInput

async def main():
    session_res = json.loads(await psy_create_session(CreateSessionInput(persona_id="counselor_amara", session_id="exp-001")))

    turns = [
        "I've been feeling really overwhelmed lately. My job is demanding too much and I have no time for myself.",
        "It's just constant pressure. I'm a software engineer and the deadlines are always unreasonable.",
        "I guess I could try to set better boundaries, but I'm afraid my manager will think I'm slacking.",
        "Thanks. I'll try talking to them tomorrow and see how it goes."
    ]

    mcp_responses = []

    for turn in turns:
        res = json.loads(await psy_generate_response(GenerateResponseInput(session_id="exp-001", user_text=turn)))

        # As an LLM simulating the persona, I will use these constraints to generate a response.
        # But for this experiment script, we'll just capture the constraints to show they are coherent and evolving.

        state = json.loads(await psy_get_coherence_state(SessionIdInput(session_id="exp-001")))

        mcp_responses.append({
            "user_input": turn,
            "constraints": res.get("generation_constraints", {}),
            "coherence_scores": state.get("coherence_scores", {})
        })

    with open("mcp_experiment_results.json", "w") as f:
        json.dump(mcp_responses, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
