# Psychological Coherence MCP

A stateful [Model Context Protocol](https://modelcontextprotocol.io/) server that gives language models structured guidance for persona-consistent dialogue. It combines deterministic text analysis, conversational memory, belief tracking, topic state, safety triage, and response-alignment checks without calling an external API.

> [!IMPORTANT]
> The safety and psychological signals are rule-based conversational aids. They are not diagnoses and are not substitutes for qualified professional judgment or emergency services.

## Highlights

- Four detailed personas with stable traits, voice markers, and response patterns
- Weighted emotion, Big Five, formality, directness, need, and trigger analysis
- Short- and long-term memory with relevance-ranked recall
- Belief tracking with contradiction detection
- Topic, dialogue-phase, and multi-dimensional coherence tracking
- Safety-first handling of explicit self-harm and violence signals
- Review-first memory extraction—nothing is silently promoted to long-term memory
- Versioned session export/import with strict validation and bounded state
- Closed-loop recording and evaluation of the response actually shown to a user
- Fully local, deterministic analysis with no external model or network dependency

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/recursive-ai-dev/psych-coherence-mcp.git
cd psych-coherence-mcp
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e .
python -m psych_coherence_mcp
```

The last command starts the MCP server over stdio. Installation also provides a `psych-coherence-mcp` console command.

### Claude Desktop

Install the package in the Python environment Claude Desktop will use, then add the following entry to its configuration:

```json
{
  "mcpServers": {
    "psychological_coherence": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "psych_coherence_mcp"],
      "env": {}
    }
  }
}
```

An editable template is available in [`claude_desktop_config.json`](claude_desktop_config.json). The root-level `server.py` launcher remains as a backward-compatible entry point, but new integrations should use the package module or console command.

## Available tools

| Tool | Purpose |
| --- | --- |
| `psy_list_personas` | List persona summaries |
| `psy_get_persona` | Retrieve a complete persona definition |
| `psy_create_session` | Create state for a persona-driven dialogue |
| `psy_analyze_input` | Run the complete text-analysis pipeline |
| `psy_generate_response` | Build the primary generation brief and update session state |
| `psy_store_memory` | Explicitly store an approved long-term memory |
| `psy_recall` | Rank and retrieve relevant memories |
| `psy_store_belief` | Store a fact and detect contradictions |
| `psy_build_constraints` | Build persona-aware constraints without advancing a turn |
| `psy_humanize_text` | Add calibrated disfluencies and prosody hints |
| `psy_get_coherence_state` | Inspect the current coherence state |
| `psy_assess_safety` | Run standalone explicit harm-signal triage |
| `psy_extract_memories` | Suggest reviewable memory candidates without storing them |
| `psy_record_response` | Record the delivered assistant turn and check alignment |
| `psy_list_sessions` | List active in-memory sessions |
| `psy_export_session` | Export a versioned JSON snapshot |
| `psy_import_session` | Validate and restore a snapshot |
| `psy_end_session` | End a session and return its summary |

## Typical workflow

1. Call `psy_create_session` with one of the persona IDs below.
2. Pass each user turn to `psy_generate_response`.
3. Use the returned tone, structure, content, safety, memory, and persona constraints to compose a response. A `safety_first` priority always outranks persona performance.
4. Optionally pass ordinary responses through `psy_humanize_text`. Do not humanize urgent safety responses.
5. Call `psy_record_response` with the exact response delivered to the user.
6. Review `psy_extract_memories` output and explicitly persist approved items with `psy_store_memory` or `psy_store_belief`.
7. Export the session if it must survive process shutdown.

Sessions are held in memory and are intentionally bounded. Export important sessions before stopping the process.

## Personas

- **Amara** (`counselor_amara`) — warm, perceptive, reflective, and calm
- **Kai** (`engineer_kai`) — systematic, precise, patient, and evidence-oriented
- **Vex** (`storyteller_vex`) — lyrical, mercurial, and narrative-driven
- **Sol** (`mentor_sol`) — grounded, direct, practical, and economical

## Project layout

```text
.
├── src/psych_coherence_mcp/
│   ├── analysis.py       # linguistic, emotion, trait, safety, and memory analysis
│   ├── coherence.py      # memory relevance, beliefs, topics, and scoring
│   ├── constants.py      # lexicons, personas, and state limits
│   ├── generation.py     # generation constraints and humanization
│   ├── models.py         # internal state models
│   ├── schemas.py        # validated MCP inputs
│   ├── server.py         # FastMCP tools and stdio entry point
│   └── state.py          # session registry and snapshot validation
├── tests/                # pytest plus integration/adversarial checks
├── examples/             # runnable local examples
├── results/              # checked-in experiment fixtures
└── docs/                 # audit and experiment notes
```

## Development

Install development dependencies and run every quality gate:

```bash
pip install -e '.[dev]'
ruff format --check .
ruff check .
mypy
pytest
python tests/integration_check.py
python tests/regression_check.py
python tests/adversarial_check.py
```

The pytest suite includes a real stdio client/server smoke test, so it checks MCP registration and transport in addition to direct Python calls.

## Design notes

All analysis is algorithmic:

- emotion detection uses a weighted lexicon, valence/arousal mapping, and basic negation handling;
- personality estimates use directional lexical evidence with shrinkage toward a neutral prior and conflict-aware confidence;
- memory relevance combines token overlap, configurable recency decay, importance, and a bounded access bonus;
- coherence combines topic flow, memory recency, contradiction rate, and profile stability;
- humanization probabilistically applies persona-calibrated pauses, fillers, hesitations, and self-repairs.

These heuristics provide transparent, reproducible signals. They do not claim the accuracy of a clinical instrument or a learned psychological model.

## Acknowledgment

Original Psychological Coherence Framework concept by James.
