# Psychological Coherence MCP Server

A Model Context Protocol server that implements psychologically-informed, rule-based text generation with coherent conversational state management. Built from the Psychological Coherence Framework concept — distilled into functional, stateful tools that an LLM can orchestrate for persona-driven dialogue.

## What This Does

This MCP server gives an LLM the ability to maintain **psychological coherence** across a conversation by providing tools for:

- **Persona-driven voice**: Four deeply characterized personas with personality traits, communication styles, formative experiences, voice markers, and emotional triggers
- **Real-time psychological analysis**: Weighted Big Five personality profiling, emotion detection (valence/arousal model), formality/directness scoring, need detection, trigger identification
- **Multi-layered memory**: Short-term working memory, long-term storage with relevance-scored recall (TF-overlap + recency decay + importance weighting)
- **Belief tracking with contradiction detection**: Maintains a belief graph per entity/attribute, detects contradictions when new facts conflict with prior claims, suggests resolution strategies
- **Coherence scoring**: Multi-dimensional (topic, memory, belief, profile stability) with weighted composite
- **Topic tracking**: Detects continuations, shifts, and returns with appropriate discourse markers
- **Dialogue phase awareness**: Automatic phase detection (opening, information gathering, problem solving, rapport building, negotiation, closing)
- **Humanization**: Disfluency injection (filled pauses, filler words, hesitations, self-repairs), persona voice markers, prosody hints — all calibrated to persona traits and emotional context
- **Generation constraint building**: Converts psychological analysis into actionable LLM instructions (tone, structure, content, avoidance directives)

## Tools

| Tool | Description |
|------|-------------|
| `psy_list_personas` | List all available personas with summaries |
| `psy_get_persona` | Get full persona definition (traits, voice, experiences) |
| `psy_create_session` | Initialize a dialogue session with a specific persona |
| `psy_analyze_input` | Full psychological analysis of any text |
| `psy_generate_response` | **Primary tool** — full pipeline producing generation constraints |
| `psy_store_memory` | Store a memory (episodic, semantic, procedural, emotional) |
| `psy_recall` | Relevance-scored memory retrieval |
| `psy_store_belief` | Record facts with automatic contradiction detection |
| `psy_build_constraints` | Build generation constraints without full pipeline |
| `psy_humanize_text` | Apply disfluencies and persona voice to clean text |
| `psy_get_coherence_state` | Full session coherence report |
| `psy_end_session` | End session with comprehensive summary |

## Personas

- **Amara** (`counselor_amara`): Warm, perceptive counselor. Reflective listening, Socratic questioning, calm authority from genuine understanding.
- **Kai** (`engineer_kai`): Systems thinker. Precise but patient, finds beauty in mechanisms, values clarity over cleverness.
- **Vex** (`storyteller_vex`): Mercurial creative. Thinks in narrative arcs, every word chosen for weight, finds meaning where others find noise.
- **Sol** (`mentor_sol`): Grounded pragmatist. Speaks slowly and means every word. Blunt but never unkind.

Each persona includes Big Five traits, communication style parameters, emotional triggers, response patterns, voice markers (preferred starters, hedges, intensifiers, signature phrases), and formative experiences that shape their worldview.

## Installation

### Requirements

- Python 3.10+
- `mcp` (MCP Python SDK with FastMCP)
- `pydantic` v2+

```bash
pip install mcp pydantic
```

### Claude Desktop Integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "psychological_coherence": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": {}
    }
  }
}
```

### Running Standalone

```bash
python server.py
```

This starts the server on stdio transport (the protocol used by Claude Desktop and other MCP clients).

### Running Tests

```bash
python test_server.py
```

## How an LLM Uses This

The typical workflow:

1. **`psy_create_session`** — pick a persona, get a session ID
2. **`psy_generate_response`** — pass the user's text; get back a full generation brief with:
   - Psychological analysis of the user
   - Persona-calibrated constraints (tone, structure, content, avoidance)
   - Recalled memories
   - Topic transition guidance
   - Dialogue phase context
3. **The LLM writes its response** using those constraints
4. **`psy_humanize_text`** (optional) — add persona-authentic disfluencies
5. **`psy_store_memory`** / **`psy_store_belief`** — persist important facts
6. Repeat from step 2

## Architecture

The server is self-contained in a single Python file with zero external API dependencies. All analysis is algorithmic:

- **Emotion detection**: Weighted lexicon (~120 words → 13 emotions) with negation handling, sigmoid-scaled intensity, valence/arousal computation
- **Big Five profiling**: Directional lexicon scoring (~180 indicator words) with Bayesian shrinkage toward prior, supplemented by linguistic feature heuristics
- **Memory relevance**: TF-overlap with exponential recency decay (24h half-life), importance weighting, access frequency bonus
- **Coherence scoring**: Weighted composite of topic consistency, memory accessibility, belief contradiction rate, and profile stability
- **Disfluency injection**: Probabilistic with persona-trait calibration (neuroticism amplifies pauses, extraversion amplifies filler words) and emotional modulation

## License

Concept by James. MCP implementation follows the Model Context Protocol specification.
