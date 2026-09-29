# Code Stabilization Report

## Changes Applied

Inspected the Python package, MCP entry points, session lifecycle, snapshot validation, analysis, generation, and existing tests. The deeper follow-up traced accepted snapshots through subsequent operations, exercised counter boundaries, checked exact response identity, and tested concurrent retries and actual stdio transport. Public tool signatures and response schemas are preserved. Malformed snapshots now fail validation before replacing existing state.

The first four rows record the initial pass. Subsequent rows record the deeper follow-up. Regression coverage is in `tests/test_stabilization.py`, `tests/test_deep_stabilization.py`, and `tests/test_transport.py`.

| Priority | Location | Defect | Fix | Regression Test |
| -------- | -------- | ------ | --- | --------------- |
| P1 | `src/psych_coherence_mcp/server.py` — `psy_generate_response` | Urgent-safety briefs returned `humanization_config.enabled = true` by default despite explicitly prohibiting humanization in their generation constraints. | Disable humanization whenever the constraints specify `safety_first`; preserve the caller's preference for ordinary turns. | `test_humanization_config_respects_safety_priority`: four combinations of safety priority and caller preference. |
| P2 | `src/psych_coherence_mcp/coherence.py` — `compute_memory_relevance` | JSON serialization escaped non-ASCII memory content before tokenization. Exact queries such as `café` received no overlap credit and could rank below unrelated memories. | Initially preserved Unicode during serialization; the deeper fix below now tokenizes the underlying strings directly. | `test_memory_relevance_matches_unicode_content`: accented and Japanese text; `test_unicode_recall_ranks_matching_memory_first`: public recall ranking. |
| P2 | `src/psych_coherence_mcp/coherence.py` — `update_topic_state` | A turn without extracted topics returned a continuation while leaving the stored transition at its previous value, such as `shift`. | Update the stored transition to `continuation`, preserving the current topic, confidence, and history. | `test_topic_free_turn_keeps_transition_consistent`. |
| P2 | `src/psych_coherence_mcp/server.py` — `psy_analyze_input`, `psy_store_memory`, `psy_store_belief`, `psy_recall` | Profile updates, stored memories/beliefs, and recall access-count changes left session `updated_at` stale in listings and exports. | Refresh the timestamp inside the existing session lock after successful mutations. Empty recalls and rejected writes preserve it. | `test_mutations_refresh_exported_and_listed_updated_at`: all four mutation paths; `test_empty_recall_and_rejected_writes_preserve_updated_at`. |
| P2 | `src/psych_coherence_mcp/coherence.py` — memory content tokenization | Newlines, tabs, and other whitespace became JSON escape characters before tokenization. A memory containing `alpha` followed by a newline and `beta` received no overlap credit for `beta`, including inside nested imported content. | Tokenize decoded strings throughout JSON objects/lists, retaining Unicode and the existing tokenizer's treatment of literal backslash sequences. | `test_memory_search_uses_text_not_json_escapes`: ten nested/flat whitespace cases; `test_memory_search_preserves_literal_escape_sequences`; stdio recall ranking. |
| P2 | `src/psych_coherence_mcp/schemas.py` — `RecordResponseInput` | Model-wide whitespace stripping changed delivered text before storage and hashing, silently treating different responses as identical retries and removing meaningful indentation. | Preserve response text exactly while still rejecting blank responses; identifier normalization remains in the existing `SessionId` type. | `test_response_recording_preserves_exact_text_across_restore_and_retries`; four blank-response cases; stdio recording, hash, restore, retry, and conflict checks. |
| P2 | `src/psych_coherence_mcp/state.py` — response restoration | Import accepted response text/hash without a recording timestamp. Recording then treated that response as pending and overwrote it. | Reject the inconsistent snapshot atomically; valid legacy recorded responses without hashes remain protected by `response_conflict`. | `test_inconsistent_snapshot_rejected_without_replacing_session`: missing/empty recording timestamps; `test_legacy_recorded_response_without_hash_remains_protected`; stdio atomic rejection. |
| P2 | `src/psych_coherence_mcp/state.py` — memory and belief restoration | Duplicate memory IDs made recall identities ambiguous; future belief source turns produced impossible provenance and negative contradiction intervals. | Reject duplicate memory IDs and belief source turns greater than the session turn count before registration. | `test_inconsistent_snapshot_rejected_without_replacing_session`: duplicate-memory and future-belief cases, checking original state remains unchanged. |
| P3 | `src/psych_coherence_mcp/state.py` — snapshot metadata | Python equality accepted `true` and `1.0` as snapshot version 1; coercing timestamps to strings accepted integer dates such as `20260101`. | Require an integer version excluding booleans, and string session timestamps before date parsing. | `test_inconsistent_snapshot_rejected_without_replacing_session`: boolean/float versions and numeric creation/update timestamps. |
| P2 | `src/psych_coherence_mcp/constants.py`, `server.py`, `state.py` — counter bounds | A valid import at the accepted counter ceiling became unimportable after one recall or generation because live updates exceeded snapshot limits. | Share the existing limits between runtime and validation. Saturate memory access counts at 1,000,000,000; reject generation at the turn ceiling before mutating conversational state. Pending responses remain recordable. Document the limits and stricter import checks in `README.md`. | `test_memory_access_counter_boundary_remains_round_trippable`: recall and generation; `test_turn_limit_rejects_generation_before_mutating_state`: last valid turn, rejection, round trip, and pending recording. |

## Verification Results

Commands ran from the repository root using the existing Python 3.13 virtual environment. Other advertised Python versions were not exercised. The initial pass results are retained below, followed by the deeper pass results.

| Command | Result | Scope |
| ------- | ------ | ----- |
| `.venv/bin/pytest -q` — baseline | Passed: 67 tests. | Existing suite before edits, including MCP stdio transport. |
| `.venv/bin/pytest -q tests/test_stabilization.py` — before fixes | Failed as expected: 10 failed, 4 passed. | Demonstrated each reported defect; ordinary behavior and no-op controls already passed. |
| `.venv/bin/ruff format tests/test_stabilization.py` | Completed: one file formatted. | New regression tests only. |
| `.venv/bin/pytest -q tests/test_stabilization.py tests/test_coherence.py tests/test_tools.py tests/test_audit_regressions.py tests/test_limits.py` | Passed: 69 tests. | Focused regression, state, lifecycle, safety, and resource-limit coverage after fixes. |
| `.venv/bin/ruff format --check .` | Passed: 30 files already formatted. | Repository Python formatting. |
| `.venv/bin/ruff check .` | Passed. | Repository lint rules. |
| `.venv/bin/mypy` | Passed: no issues in 12 source files. | Strict package type checking. |
| `.venv/bin/pytest -q` — initial pass final | Passed: 81 tests. | Full suite, including all 14 initial regression cases and real stdio transport. |
| `.venv/bin/python tests/integration_check.py` | Passed: 66/66 checks. | Public tool integration. |
| `.venv/bin/python tests/regression_check.py` | Passed: “Expanded capability tests passed.” | Existing capability regressions. |
| `.venv/bin/python tests/adversarial_check.py` | Passed: 114/114 checks. | Malformed inputs, concurrent writes, state handling, and resource stress. |
| `.venv/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/psych-coherence-stabilization-wheels` | Failed: `Cannot import 'setuptools.build_meta'`. | The existing virtual environment lacks the build backend; retried below with normal build isolation. |
| `.venv/bin/python -m pip wheel --no-deps . --wheel-dir /tmp/psych-coherence-stabilization-wheels` | Passed: built `psych_coherence_mcp-1.0.0-py3-none-any.whl`. | Full wheel build using the declared build dependencies in an isolated environment. |
| `git diff --check` | Passed. | Patch whitespace validation. |

Deeper pass verification:

| Command | Result | Scope |
| ------- | ------ | ----- |
| Inline `.venv/bin/python` reproduction probes | Confirmed defects. | Whitespace differences incorrectly returned `already_recorded`; inconsistent snapshots were imported; missing recording timestamps allowed overwrite; counter ceilings produced unimportable exports; integer timestamps were accepted. |
| `.venv/bin/pytest -q tests/test_deep_stabilization.py --tb=short` — before fixes | Failed as expected: 20 failed, 7 passed. | Reproduced the additional defects; blank-response validation, literal backslash handling, valid legacy recording, and concurrent identical retries already passed. |
| `.venv/bin/ruff format src/psych_coherence_mcp/coherence.py src/psych_coherence_mcp/schemas.py src/psych_coherence_mcp/constants.py src/psych_coherence_mcp/state.py src/psych_coherence_mcp/server.py tests/test_deep_stabilization.py` | Completed: one file formatted, five unchanged. | Initial deeper-pass edits. |
| `.venv/bin/pytest -q tests/test_deep_stabilization.py tests/test_stabilization.py tests/test_tools.py tests/test_audit_regressions.py --tb=short` | Passed: 87 tests. | Focused new and existing regressions after initial deeper fixes. |
| `.venv/bin/pytest -q tests/test_deep_stabilization.py -k numeric --tb=short` — before timestamp fix | Failed as expected: 2 failed, 27 deselected. | Demonstrated numeric session timestamps were silently accepted. |
| `.venv/bin/ruff format src/psych_coherence_mcp/state.py tests/test_deep_stabilization.py tests/test_transport.py` | Completed: one file formatted, two unchanged. | Timestamp and real transport regression additions. |
| `.venv/bin/pytest -q tests/test_deep_stabilization.py tests/test_transport.py --tb=short` | Passed: 32 tests. | Boundary/validation regressions and three actual MCP stdio tests. |
| Inline `.venv/bin/python` snapshot mutation sweep | Passed: 774 cases; 572 rejected and 202 accepted without subsequent lifecycle failures. | Replaced snapshot fields with null, booleans, numbers, strings, lists, and objects. Accepted snapshots survived recall, scoring, generation, response recording, export, re-import, and ending. Retained as `test_snapshot_mutation_matrix_remains_usable_or_rejects_atomically`, with additional atomicity assertions. |
| Inline `.venv/bin/python` retention probe | Confirmed the deferred scoring issue below. | With history retention reduced to two entries, ten real generated turns and nine belief contradictions reported two contradictions and belief coherence 0.6. |
| `.venv/bin/ruff format tests/test_deep_stabilization.py` | Completed: one file formatted. | Retained mutation-matrix test. |
| `.venv/bin/pytest -q tests/test_deep_stabilization.py --tb=short` — final focused run | Passed: 30 tests. | All deeper regression cases, including the 774-case matrix and 20 concurrent response retries. |
| `.venv/bin/ruff format --check .` | Passed: 32 files already formatted. | Full repository formatting. |
| `.venv/bin/ruff check .` | Passed on both deeper-pass runs. | Full repository lint rules. |
| `.venv/bin/mypy` | Passed on both deeper-pass runs: no issues in 12 source files. | Strict package type checking. |
| `.venv/bin/pytest -q` — deeper pass final | Passed: 112 tests. | Full suite, including 31 additional tests and the embedded mutation matrix. |
| `.venv/bin/python tests/integration_check.py` | Passed: 66/66 checks. | Public tool integration. |
| `.venv/bin/python tests/regression_check.py` | Passed: “Expanded capability tests passed.” | Existing capability regressions. |
| `.venv/bin/python tests/adversarial_check.py` | Passed: 114/114 checks. | Adversarial inputs, concurrency, state, and resource tests. |
| `.venv/bin/python -m pip wheel --no-deps . --wheel-dir /tmp/psych-coherence-deep-stabilization-wheels` | Passed: built `psych_coherence_mcp-1.0.0-py3-none-any.whl`. | Full isolated wheel build. |
| `git diff --check` | Passed. | Final patch whitespace validation. |

## Deferred Risks

**Contradiction scoring after history eviction** — `coherence.py::compute_coherence_score` divides the retained contradiction-log length by the lifetime turn count. Once the 1,000-entry log starts evicting records, belief coherence can improve despite continuing contradictions; reported total contradictions also reflects only retained entries. A reduced-cap public-tool reproduction produced nine actual contradictions but reported two and a score of 0.6.

Changing this safely requires choosing lifetime or recent-window semantics. Lifetime scoring needs a persisted cumulative count plus a migration policy for snapshots that have already lost records; recent-window scoring changes the metric's meaning. Neither is inferable from existing snapshots. Containment: track cumulative contradictions externally, or export and rotate sessions before the contradiction log reaches 1,000 entries; do not interpret the current score as a lifetime rate after eviction.

## What I need from you

No input is needed for the applied fixes. Resolving the deferred scoring issue requires a choice between lifetime and recent-window scoring, including how historical snapshots should be treated.
