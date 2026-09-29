# Code Stabilization Report

## Changes Applied

Inspected the Python package, MCP entry points, session lifecycle, snapshot validation, analysis, generation, and existing tests. Changes preserve public signatures and response schemas. All new regression tests are in `tests/test_stabilization.py`.

| Priority | Location | Defect | Fix | Regression Test |
| -------- | -------- | ------ | --- | --------------- |
| P1 | `src/psych_coherence_mcp/server.py` — `psy_generate_response` | Urgent-safety briefs returned `humanization_config.enabled = true` by default despite explicitly prohibiting humanization in their generation constraints. | Disable humanization whenever the constraints specify `safety_first`; preserve the caller's preference for ordinary turns. | `test_humanization_config_respects_safety_priority`: four combinations of safety priority and caller preference. |
| P2 | `src/psych_coherence_mcp/coherence.py` — `compute_memory_relevance` | JSON serialization escaped non-ASCII memory content before tokenization. Exact queries such as `café` received no overlap credit and could rank below unrelated memories. | Preserve Unicode characters when serializing content for relevance scoring. | `test_memory_relevance_matches_unicode_content`: accented and Japanese text; `test_unicode_recall_ranks_matching_memory_first`: public recall ranking. |
| P2 | `src/psych_coherence_mcp/coherence.py` — `update_topic_state` | A turn without extracted topics returned a continuation while leaving the stored transition at its previous value, such as `shift`. | Update the stored transition to `continuation`, preserving the current topic, confidence, and history. | `test_topic_free_turn_keeps_transition_consistent`. |
| P2 | `src/psych_coherence_mcp/server.py` — `psy_analyze_input`, `psy_store_memory`, `psy_store_belief`, `psy_recall` | Profile updates, stored memories/beliefs, and recall access-count changes left session `updated_at` stale in listings and exports. | Refresh the timestamp inside the existing session lock after successful mutations. Empty recalls and rejected writes preserve it. | `test_mutations_refresh_exported_and_listed_updated_at`: all four mutation paths; `test_empty_recall_and_rejected_writes_preserve_updated_at`. |

## Verification Results

Commands ran from the repository root using the existing Python 3.13 virtual environment.

| Command | Result | Scope |
| ------- | ------ | ----- |
| `.venv/bin/pytest -q` — baseline | Passed: 67 tests. | Existing suite before edits, including MCP stdio transport. |
| `.venv/bin/pytest -q tests/test_stabilization.py` — before fixes | Failed as expected: 10 failed, 4 passed. | Demonstrated each reported defect; ordinary behavior and no-op controls already passed. |
| `.venv/bin/ruff format tests/test_stabilization.py` | Completed: one file formatted. | New regression tests only. |
| `.venv/bin/pytest -q tests/test_stabilization.py tests/test_coherence.py tests/test_tools.py tests/test_audit_regressions.py tests/test_limits.py` | Passed: 69 tests. | Focused regression, state, lifecycle, safety, and resource-limit coverage after fixes. |
| `.venv/bin/ruff format --check .` | Passed: 30 files already formatted. | Repository Python formatting. |
| `.venv/bin/ruff check .` | Passed. | Repository lint rules. |
| `.venv/bin/mypy` | Passed: no issues in 12 source files. | Strict package type checking. |
| `.venv/bin/pytest -q` — final | Passed: 81 tests. | Full suite, including all 14 new regression cases and real stdio transport. |
| `.venv/bin/python tests/integration_check.py` | Passed: 66/66 checks. | Public tool integration. |
| `.venv/bin/python tests/regression_check.py` | Passed: “Expanded capability tests passed.” | Existing capability regressions. |
| `.venv/bin/python tests/adversarial_check.py` | Passed: 114/114 checks. | Malformed inputs, concurrent writes, state handling, and resource stress. |
| `.venv/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/psych-coherence-stabilization-wheels` | Failed: `Cannot import 'setuptools.build_meta'`. | The existing virtual environment lacks the build backend; retried below with normal build isolation. |
| `.venv/bin/python -m pip wheel --no-deps . --wheel-dir /tmp/psych-coherence-stabilization-wheels` | Passed: built `psych_coherence_mcp-1.0.0-py3-none-any.whl`. | Full wheel build using the declared build dependencies in an isolated environment. |
| `git diff --check` | Passed. | Patch whitespace validation. |

## Deferred Risks

No confirmed issues requiring an unsafe or breaking change were deferred in this pass. Verification used Python 3.13; the other advertised Python versions were not exercised.

## What I need from you

Nothing further. The current repository was used for this stabilization pass.
