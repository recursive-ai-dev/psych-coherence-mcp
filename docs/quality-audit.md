# Code Quality Audit

This document records the cleanup and reliability sweep completed during the package refactor. The original audit findings are retained here as a resolved checklist rather than as stale line-number references.

## Resolved findings

| Finding | Resolution |
| --- | --- |
| Substring matches produced false needs, triggers, greetings, and closings | Phrase checks now use word-boundary-aware regular expressions. Regression cases cover `down`/`own`, `crush`/`rush`, and `this`/`hi`. |
| Topic tracking confused token substrings with continuations | Continuations compare complete topic tokens, and returns are recorded as real history transitions. |
| Memory access counts changed for results that were not returned | Access counts are incremented only after ranking and slicing the selected results. |
| Topic shifts duplicated the previous topic | Shift history appends only the new topic; return transitions append one return event. |
| Punctuation-only humanization could crash or produce an inappropriate starter | Empty and punctuation-only inputs are handled without indexing an empty string or prepending persona text. |
| Uppercase ratio counted normal sentence initials as shouting | The first alphabetic character in each sentence is excluded. |
| Timestamp work was repeated inside scoring loops | A single current timestamp is captured per coherence pass. |
| Token cleanup regexes and linguistic marker sets were repeatedly allocated | They are module-level constants. |
| Personality confidence increased mostly with input length | Confidence now reflects observed trait evidence and is reduced by opposing evidence. |
| A second end-session call raised an exception | Ending an inactive session returns a structured `not_found` result. |
| Contradictions were logged but omitted under the legacy state key | Coherence state exposes both `contradiction_log` and `contradictions_detected`. |
| MCP startup emitted a Pydantic forward-reference warning | The MCP settings model is rebuilt before server construction. Imports pass under `-W error`. |
| Untrusted snapshots could construct malformed dataclasses | Snapshot memories, profiles, beliefs, topics, timestamps, phases, identifiers, and collection sizes are validated before restoration. Invalid snapshots return structured errors. |
| In-memory collections could grow without a bound | Active sessions, memories, beliefs, and retained histories have explicit caps. |
| The one-file layout encouraged fragile `from server import ...` paths | The implementation now uses an installable `src/psych_coherence_mcp` package with explicit relative imports and a compatibility launcher. |

## Verification gates

The current codebase is checked with:

- Ruff formatting and linting across source, tests, and examples;
- strict Mypy checking across the package;
- pytest unit, integration, snapshot-fuzz, concurrency, and stdio transport tests;
- the 66-check integration script;
- expanded capability regressions;
- the 114-check adversarial script;
- warning-as-error import and bytecode compilation checks.

See the root [`README.md`](../README.md) for exact commands.
