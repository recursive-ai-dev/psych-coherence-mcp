"""Analyze one or more turns in a single in-memory session from the command line."""

import argparse
import asyncio
import json

from psych_coherence_mcp import (
    PERSONAS,
    CreateSessionInput,
    GenerateResponseInput,
    psy_create_session,
    psy_generate_response,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("turns", nargs="+", help="One or more user turns to analyze in order.")
    parser.add_argument(
        "--persona",
        choices=sorted(PERSONAS),
        default="counselor_amara",
        help="Persona used for the session.",
    )
    return parser.parse_args()


async def run(persona_id: str, turns: list[str]) -> None:
    created = json.loads(await psy_create_session(CreateSessionInput(persona_id=persona_id)))
    session_id = created.get("session_id")
    if not session_id:
        raise RuntimeError(created.get("error", "Could not create a session."))

    for turn in turns:
        brief = json.loads(
            await psy_generate_response(
                GenerateResponseInput(session_id=session_id, user_text=turn)
            )
        )
        print(json.dumps(brief, indent=2))


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.persona, args.turns))


if __name__ == "__main__":
    main()
