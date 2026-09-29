# Psychological Coherence MCP

A stateful [Model Context Protocol](https://modelcontextprotocol.io/) server designed to help **smaller language models hold more consistent, context-aware conversations**. It supplies conversational memory, current facts, persona guidance, topic tracking, and rule-based safety signals that a calling application can give to its model on each turn.

The server handles conversation state and builds a structured response brief; your model writes the reply. This is intended to improve conversational behavior by giving the model relevant context and explicit guidance at inference time. The server runs locally and does not call a model or an external API.

> [!IMPORTANT]
> The safety and psychological signals are rule-based conversational aids. They are not diagnoses and are not substitutes for qualified professional judgment or emergency services.

## How this helps smaller models

A conversation asks a model to do several things at once: answer the current question, remember earlier facts, follow a consistent voice, recognize topic changes, and respond appropriately to the user's tone. This project is built for smaller models and applications with limited context budgets that benefit from having that information tracked outside the model and supplied explicitly.

Instead of requiring the model to reconstruct all conversation state on every turn, the server maintains a session and returns guidance through `psy_generate_response`:

| Conversational task | What the server supplies | Intended benefit for the model |
| --- | --- | --- |
| Remember relevant details | Recent conversation and up to five ranked long-term memories | Gives the reply access to stored context beyond the current message |
| Keep facts consistent | Up to five relevant current beliefs, with confidence and provenance, plus recent contradictions | Helps the model use updated facts and recognize conflicting statements |
| Maintain a recognizable voice | Persona-specific tone, structure, and voice guidance | Makes the expected speaking style explicit on each turn |
| Follow the conversation | Topic transitions and dialogue-phase guidance | Helps the model connect its reply to the ongoing discussion |
| Adapt its response | Heuristic emotion, formality, directness, and conversational-need signals | Provides cues for choosing an appropriate tone and level of detail |
| Attend to explicit danger signals | Safety priority and response directives | Makes safety-related instructions visible in the generation brief |
| Carry replies into later turns | Recorded assistant responses and basic alignment feedback | Keeps subsequent briefs aware of what the assistant actually said |

For example, an application can store `user.city = Paris` with `psy_store_belief`, then update it to `Rome` when the user reports a move. When the user later asks, "What city do I live in?", the brief's `relevant_beliefs` includes the current value, `Rome`, with its confidence and source information. The model receives the relevant fact even when the original exchange is outside its prompt. Facts must be explicitly stored; memory extraction produces suggestions for review, not automatic permanent memory.

These are intended benefits of the architecture, not a measured capability gain for every smaller model. The server does not train the model, change its weights, or expand its context window. Results depend on the model, the context supplied by the application, and how well it follows the guidance. The tests verify server behavior; evaluate conversational quality with your own model and representative conversations.

### Connecting a smaller model

Your application acts as the MCP client and connects the server to your chosen model runtime. The model itself does not need native MCP support or reliable tool selection if the application makes the tool calls in a fixed sequence:

1. Create a session once with `psy_create_session`.
2. Before each model call, send the user's message to `psy_generate_response`.
3. Build the model's prompt from the user's message, the returned generation constraints, relevant beliefs and memories, and recent conversation. Preserve safety priority and directives when selecting context.
4. Ask the model to write the user-facing reply using that context.
5. Record the delivered reply with `psy_record_response`, passing the brief's `generation_id`. Use its alignment feedback to inspect behavior, and include the recorded conversation in subsequent turns.

The full brief includes diagnostic detail and can be lengthy. For a model with a small context budget, the application can select the relevant fields and limit their size before building the prompt. This selection is the application's responsibility; the server does not automatically fit the brief to a model's token budget. Treat stored memories, beliefs, and quoted conversation as context data, keeping them separate from application instructions.

Response recording evaluates text after delivery; it does not automatically revise or block the reply. Any review before delivery belongs in the application. The server can accompany a local model for a local conversation pipeline, or a remotely hosted model; model inference and its resource requirements are separate from this server.

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

A configuration using the installed `psych-coherence-mcp` command is available in
[`claude_desktop_config.json`](claude_desktop_config.json). It works when that command
is on the desktop client's `PATH`. If the client does not inherit your activated
virtual environment, use the absolute Python path shown above. The root-level
`server.py` launcher remains as a backward-compatible entry point, but new
integrations should use the package module or console command.

### Deployment

The supported deployment is a local stdio subprocess launched by an MCP client.
No API keys, environment variables, database, model download, writable data
directory, or network service is required at runtime. Dependencies must be
available from a package index during installation, or supplied as local wheels.
The server runs from any working directory after installation. Its stdout is
reserved for MCP messages; diagnostics go to stderr.

For a non-editable production installation from this checkout:

```bash
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/psych-coherence-mcp
```

On Windows, use `.venv\Scripts\python.exe` and
`.venv\Scripts\psych-coherence-mcp.exe`. Configure the MCP client to launch the
installed command or the virtual environment's Python with
`-m psych_coherence_mcp`. A process waiting silently for input is normal; MCP
initialization and `ping` are the readiness check. Closing stdin shuts it down.
There is no HTTP listener or HTTP health route in this deployment.

To build distributable artifacts, install `.[dev]` and run `python -m build`.
This creates an sdist and a wheel built from that sdist in `dist/`. Install the
wheel with `python -m pip install dist/psych_coherence_mcp-1.0.0-py3-none-any.whl`,
then run `python -m pip check`. The release CI installs the wheel and exercises all
18 tools through the module, console, and compatibility launchers from unrelated
working directories. See [`RELEASE_READINESS.md`](RELEASE_READINESS.md) for actual
verification results and platform coverage.

State belongs to a single process and is lost on shutdown unless the client
exports snapshots and restores them after restart. Run one server per trusted
client; the stdio service does not provide shared hosting, authentication, or
cross-process session persistence. End sessions when finished: the default cap is
1,000 active sessions, each with at most 1,000 memories and 1,000 beliefs. A model
runtime is only needed by the calling application if it wants to compose replies
from the server's generation briefs.

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
3. Supply the returned tone, structure, content, safety, memory, belief, and persona guidance to your model to compose a response. A `safety_first` priority always outranks persona performance.
4. Optionally pass ordinary responses through `psy_humanize_text`. Do not humanize urgent safety responses.
5. Call `psy_record_response` with the returned `generation_id` and the exact response delivered to the user.
6. Review `psy_extract_memories` output and explicitly persist approved items with `psy_store_memory` or `psy_store_belief`.
7. Export the session if it must survive process shutdown.

Sessions are held in memory and are intentionally bounded. Export important sessions before stopping the process.

### Response identity and snapshot compatibility

`psy_generate_response` returns a unique `generation_id`. Pass it together with
`session_id` and `response_text` to `psy_record_response`. The ID is required,
including for clients upgrading from earlier releases. Responses can arrive out
of order; each uses its generation's turn and safety context. Repeating the same
response returns `already_recorded` without adding another message. A different
response for an already recorded generation returns `response_conflict` and
preserves the original. Unknown IDs and IDs evicted from the 1,000-entry history
return `generation_not_found`. IDs and response hashes survive export/import.
Response text retains its leading and trailing whitespace; retries compare the
exact text, while whitespace-only responses are rejected.

Version 1 snapshots remain supported. Legacy response entries without generation
IDs receive deterministic IDs on import, available in the next export. Missing
risk levels become `unknown`, which requires safety checks when recording a
response. Invalid risk types or values reject the import before existing state
is replaced. Already recorded legacy responses without a full-text hash cannot
be verified as identical retries and return `response_conflict`.

Topic labels are limited to 500 characters, with a hash suffix for longer labels;
topic history and keyword associations retain at most 1,000 entries each. For an
older snapshot that exceeds these topic limits, explicitly pass
`repair_topics: true` to `psy_import_session`. This bounds labels and retains the
newest entries while preserving the current topic's keyword association. The
result reports `topic_state_repaired`; export the repaired session to save it.
Normal imports strictly validate the topic limits. Both creation and import
enforce the active-session cap; explicit replacement at capacity is allowed.
Imports also reject duplicate memory IDs, beliefs sourced from future turns,
and response text or hashes without a recording timestamp. Session timestamps
must be strings, and the snapshot version must be an integer.

The session turn limit is 1,000,000,000. Further generation returns `limit_reached`
without advancing the turn; existing responses can still be recorded and the
session can still be exported. Memory access counts stop at 1,000,000,000 while
recall remains available. These bounds keep exported state importable.

Generation briefs include up to five `relevant_beliefs`, ranked by entity and
attribute matches, with current values, confidence, and source turn/timestamp.
Updated beliefs replace previous values in this section; contradiction history
remains separately available.

The response safety check requires both an immediate-safety question and concrete
human-support guidance, using phrase boundaries and basic negation checks. Its
`assessment_type`, `safety_elements`, and `limitations` fields describe a limited
rule-based heuristic; a passing result does not establish clinical safety.

Contradiction totals and belief coherence use a persisted lifetime counter even
after detailed log entries are evicted. `total_contradictions` includes evicted
events; `retained_contradictions` reports the remaining log size. Version 1
snapshots without a counter are still accepted and initialize it from the log.
If a legacy log is at the 1,000-entry cap, the server cannot recover earlier
events: it sets `contradiction_count_complete` to `false`, preserves that flag on
export, and reports it in briefs, coherence state, and session summaries. In that
case the count is a lower bound and belief coherence can overestimate lifetime
consistency. New sessions track the complete count. Keep migration metadata when
saving snapshots; older server versions do not preserve these new counter fields.

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
│   ├── state.py          # session registry and snapshot validation
│   └── topics.py         # shared topic limits and legacy snapshot repair
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
