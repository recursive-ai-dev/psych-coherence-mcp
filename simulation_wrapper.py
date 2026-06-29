import asyncio
import json
import sys
from server import psy_create_session, psy_generate_response, psy_store_memory, psy_get_coherence_state
from server import CreateSessionInput, GenerateResponseInput, StoreMemoryInput, SessionIdInput

async def main():
    if len(sys.argv) < 2:
        print("Usage: python simulation_wrapper.py <command> [args]")
        return

    command = sys.argv[1]

    if command == "create":
        res = await psy_create_session(CreateSessionInput(persona_id="counselor_amara", session_id="exp-001"))
        print(res)

    elif command == "generate":
        user_text = sys.argv[2]
        res = await psy_generate_response(GenerateResponseInput(session_id="exp-001", user_text=user_text))
        print(res)

    elif command == "store":
        text = sys.argv[2]
        res = await psy_store_memory(StoreMemoryInput(session_id="exp-001", content=text, memory_type="episodic", importance=0.8, tags=["experiment"]))
        print(res)

    elif command == "state":
        res = await psy_get_coherence_state(SessionIdInput(session_id="exp-001"))
        print(res)

if __name__ == "__main__":
    asyncio.run(main())
