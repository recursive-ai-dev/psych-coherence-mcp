# Release Readiness Report

## Executive Summary

**Deployable as a local MCP stdio server on the verified Linux/Python 3.13 environment. No unresolved release blocker for that target.** No credentials, model, database, or external runtime service is required. Installation requires Python and access to the declared packages (a package index or predownloaded wheels).

Audited on 2026-09-29. Built a source distribution and a wheel from that source distribution; installed the wheel into separate development, runtime-only, and minimum-dependency virtual environments. The final suite passes **130 tests** with both MCP/Pydantic dependency combinations. All **18 MCP tools** work through the module, console, and compatibility launchers from unrelated working directories. Invalid requests leave the transport usable, and EOF exits cleanly without stdout contamination.

The deployable artifacts are `dist/psych_coherence_mcp-1.0.0-py3-none-any.whl` and `dist/psych_coherence_mcp-1.0.0.tar.gz` (generated, Git-ignored). Install the wheel into a virtual environment with `python -m pip install dist/psych_coherence_mcp-1.0.0-py3-none-any.whl`; configure the MCP client to launch that environment's `psych-coherence-mcp` command, or its Python with `-m psych_coherence_mcp`. No service was published or deployed externally.

This conclusion covers the server and protocol, not downstream model quality, desktop GUI integration, or hosted HTTP service. Platform coverage limits are listed below.

## Gaps Resolved

| Location | Gap | Production Logic Added | Verification |
| -------- | --- | ---------------------- | ------------ |
| `src/psych_coherence_mcp/models.py`, `coherence.py`, `server.py` | Evicting contradiction details made lifetime totals and belief coherence misleading. A ten-turn reproduction reported only two of nine contradictions. | Keep a cumulative counter independent of the bounded log. Use it for lifetime scoring and totals; expose the retained count separately. Clamp the rate before float conversion to handle large imported counters. | Retention, subsequent writes, export/import, final summaries, and a 401-digit counter pass regression tests. |
| `src/psych_coherence_mcp/state.py` | A counter fix needs safe migration without inventing lost historical events. | Persist and strictly validate count/completeness metadata. Reject counts below retained history and malformed types before replacement. Legacy snapshots initialize from the retained log; capped histories and explicitly incomplete histories remain flagged incomplete. | Atomic rejection, uncapped/capped migration, repeated round trips, and preservation of incomplete metadata pass. Snapshot version 1 remains supported. |
| `tests/test_release_transport.py` | Existing transport checks did not exercise every tool through every supported launcher outside the checkout. | Add real MCP initialization/ping, calls to all 18 tools, generation/recording, memory/belief operations, export/import/end, and invalid-tool/input/session recovery through all three launchers. | Three end-to-end launcher tests pass; also replayed against an environment containing only runtime dependencies. |
| `pyproject.toml`, `MANIFEST.in` | No declared build frontend; sdist contents were implicit and omitted supporting release material. | Declare `build` in development dependencies; explicitly ship the compatibility launcher, tests, examples, configuration, reports, documentation, fixture data, and CI workflow in the sdist. Wheel contains runtime package and typing marker only. | Isolated sdist build, wheel build from sdist, artifact inspection, clean wheel installation, and all four examples from the extracted sdist pass. |
| `.github/workflows/release-checks.yml` | No automated packaging and release gates. | Add formatting, lint, strict typing, isolated distribution build, installed-wheel tests, dependency checks, integration/adversarial scripts, warning checks, and artifact retention. Matrix covers Linux Python 3.10–3.13 and Windows 3.13; UTF-8 is explicit for Unicode test output. | Equivalent Linux 3.13 commands pass locally. Remote GitHub Actions runs were not triggered. |
| `pyproject.toml` | A concurrent `.gitignore` edit excluding `tests/` caused Ruff to silently omit test files. | Disable Git-ignore filtering for Ruff while excluding generated `build/` contents. Preserve the user's ignore edits; mark the two new test files as intent-to-add so Git can review/include them. | Final formatter checks 35 files; lint passes and new tests appear in the Git diff. |
| `README.md`, `claude_desktop_config.json` | Desktop template used a nonexistent placeholder executable; non-editable deployment and operational assumptions were insufficiently documented. | Default to the installed console command; document absolute interpreter paths when desktop PATH differs, wheel installation, stdio readiness/shutdown, state ownership, caps, and snapshot migration. | Installed executable and module run outside the checkout; minimal-environment EOF checks pass. Desktop GUI itself is not available here. |

Repository sweep: no unresolved TODO, FIXME, stub, or placeholder implementation was found in runtime source. The `pass` in session-duration handling intentionally preserves a null duration when a Python-API-created session has an invalid timestamp; normal snapshot imports validate timestamps. Rule-based analysis and persona definitions are the intended implementation. Static responses in `examples/generate_baseline.py` and `results/` are explicitly documented experiment fixtures, never production data sources or model responses. There are no application HTTP routes or background event handlers to complete; MCP tools are the exposed routes. The prior scoring deferral in `CODE_STABILIZATION_REPORT.md` is marked superseded.

## Environment and Dependency Matrix

| Item | Requirement / safe default | Verified behavior |
| --- | --- | --- |
| Python | `>=3.10`; no interpreter downloaded at startup | Tested with Linux x86_64 Python **3.13.15**. Other interpreters/platforms were unavailable in this environment. |
| Required secrets / application environment variables | **None** | Runtime starts and serves tools without application configuration or secrets. |
| `PATH` | Inherited OS/client executable search path | Relevant only when the client uses `psych-coherence-mcp` by name. An absolute virtual-environment executable removes this assumption. |
| `PYTHONPATH`, current directory | No custom value or checkout directory needed | Installed-wheel imports verified under `site-packages`; all launchers work from a temporary empty directory. |
| `FASTMCP_*`, `.env` | No supported application configuration is required through these | SDK has settings machinery, but this entry point constructs default FastMCP settings and selects stdio. No `.env` file is needed. Do not treat SDK HTTP settings as a supported hosted deployment. |
| `PYTHONUTF8` | Not required by the server; CI sets `1` | Makes existing Unicode test-script output portable across CI consoles. |
| `mcp` | `>=1.29,<2` | Full suite passes with **1.30.0** and minimum **1.29.0**. |
| `pydantic` | `>=2.11,<3` | Full suite passes with **2.13.5** and minimum **2.11.0**. |
| Build backend / frontend | `setuptools>=69`; development extra adds `build>=1.2,<2` | Isolated builds use **setuptools 84.0.0**, **build 1.6.1**. Backend installation is handled by build isolation. |
| Quality tools | Mypy, pytest, pytest-asyncio, Ruff in `.[dev]` | **mypy 1.20.2**, **pytest 8.4.2**, **pytest-asyncio 1.4.0**, **Ruff 0.16.9** in the isolated environment. |
| Runtime transitive dependencies | Resolved through MCP/Pydantic metadata; no separately managed service | Dependency consistency passes. Observed SDK support packages include anyio 4.15.1, pydantic-settings 2.15.0, jsonschema 4.26.0, httpx 0.28.1, starlette 1.7.0, uvicorn 0.54.0, and cryptography 50.0.1. HTTP packages being installed does not start an HTTP listener. |
| Network / package index | Needed during ordinary dependency installation, not tool execution | Clean dependency resolution and installation succeeded. Runtime source has no external API/model/data-source call. |
| Model runtime | Optional external responsibility of the calling application | Server produces generation briefs, not model-composed replies. No model endpoint is required for this deployment. |
| Transport / readiness | Client-managed stdin/stdout; logs to stderr | MCP initialization, ping, all 18 tools, error recovery, and clean EOF pass. No HTTP port, health URL, container runtime, or database required. |
| Session persistence | In-memory by default; export/import for persistence | State is process-local. Client must save snapshots before shutdown and restore them after restart if continuity is required. |
| Resource defaults | 1,000 active sessions; 1,000 memories and beliefs per session; 30 short-term entries; 1,000 retained history/topic entries | Existing limit, concurrency, mutation-matrix, and transport tests pass. End unused sessions to release capacity. |
| Snapshot compatibility | Version 1 plus additive counter metadata | Capped legacy logs yield lower-bound counts with `contradiction_count_complete=false`; new sessions track full counts. |

The host Python injects `/app/.../site-packages` through `sitecustomize` even with `include-system-site-packages=false`. To avoid relying on it, an additional runtime probe used `python -I -S` with only the runtime environment's package directory added explicitly. All 18 tools passed with system customization, user packages, environment import paths, and checkout imports disabled. No development dependency was needed by that server process.

## Verification Results

Commands ran from the repository root unless specified. In the table, `B=/tmp/psych-release-build/bin`, `R=/tmp/psych-release-runtime/bin`, `M=/tmp/psych-release-minimum/bin`, and `W=dist/psych_coherence_mcp-1.0.0-py3-none-any.whl`. These are fresh virtual environments, not the repository's pre-existing `.venv`. No tests were skipped or disabled to obtain a pass.

| Check / command | Exact result |
| --- | --- |
| Baseline `.venv/bin/pytest -q` | **PASS: 112 passed in 5.17s.** |
| Baseline `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy` | **PASS:** 32 files formatted; all lint checks passed; no issues in 12 source files. |
| `python -m venv /tmp/psych-release-build`; `$B/python -m pip install '.[dev]' build` | **PASS:** non-editable package and development tools installed with independently resolved dependencies. |
| Pre-fix `$B/pytest -q tests/test_release_readiness.py --tb=short` against the previously installed package | **EXPECTED FAILURE: 13 failed.** Reproduced `2 != 9` lifetime totals; remaining cases required the new counter/migration validation. These failures are resolved in the final suite. |
| Initial focused `.venv/bin/pytest -q tests/test_release_readiness.py tests/test_release_transport.py --tb=short` | **PASS: 16 passed in 1.86s** before adding two further counter edge cases. |
| `$B/python -m build` | **PASS:** isolated sdist build, then wheel built from the sdist. Both version 1.0.0 artifacts created. |
| `$B/python -m pip install --force-reinstall --no-deps "$W"` | **PASS:** installed the built wheel; import path is `/tmp/psych-release-build/lib/python3.13/site-packages/psych_coherence_mcp/__init__.py`. |
| `python -m venv /tmp/psych-release-runtime`; `$R/python -m pip install "$W"` | **PASS:** wheel and runtime dependencies resolve/install without development extras. |
| `python -m venv /tmp/psych-release-minimum`; `$M/python -I -m pip install "$W[dev]" 'mcp==1.29.0' 'pydantic==2.11.0'` | **PASS:** declared minimum direct runtime dependencies resolve/install. |
| Final `$B/python -m pytest -q` | **PASS: 130 passed in 6.98s.** Includes unit, state/snapshot, concurrency, safety, limits, and real stdio tests. |
| Final `$M/python -m pytest -q` | **PASS: 130 passed in 6.80s** with minimum direct runtime dependencies. |
| Final `$B/python -m ruff format --check .` | **PASS: 35 files already formatted**, including tests despite Git ignore rules. |
| Final `$B/python -m ruff check .` | **PASS: All checks passed!** |
| Final `$B/python -m mypy` | **PASS: Success: no issues found in 12 source files.** |
| `$B/python tests/integration_check.py` | **PASS: 66/66 passed, 0 failed.** |
| `$B/python tests/regression_check.py` | **PASS: Expanded capability tests passed.** |
| `$B/python tests/adversarial_check.py` | **PASS: 114 passed, 0 failed, 0 critical.** |
| `$B/python -m pip check`, `$R/python -m pip check`, `$M/python -m pip check` | **PASS in all three environments: No broken requirements found.** |
| `$B/python -W error -c 'import psych_coherence_mcp'`; same under `$M/python` | **PASS:** no warnings/errors, exit 0. |
| `$B/python -m compileall -q src server.py examples tests` | **PASS:** exit 0. |
| `tests/test_release_transport.py` in the full suite | **PASS: 3 launchers × all 18 registered tools**, initialization/ping, invalid tool/session/persona/blank-input errors, and continued operation. |
| Runtime-only replay of `exercise_tools` with `$R/python -m psych_coherence_mcp`, `$R/psych-coherence-mcp`, and `$R/python <absolute-repo>/server.py` | **PASS:** all 18 tools for each launcher from an unrelated empty directory. |
| EOF startup probe for those same three commands with `env={'PATH':'/usr/bin:/bin','HOME':<temporary-directory>}`, empty stdin, captured output, and 20-second timeout | **PASS:** all return code 0; stdout is exactly empty. |
| Runtime isolation replay using `$R/python -I -S -c <explicit runtime-site-packages + server.main()>` | **PASS:** all 18 tools and error recovery with host customization and checkout imports disabled. |
| Wheel/sdist inspection using `zipfile` and `tarfile` | **PASS:** typing marker, console entry point, and runtime modules in wheel; all release tests/scripts, fixtures, examples, compatibility launcher, and workflow in sdist. Runtime wheel contains no example/fixture/test packages. |
| Extracted-sdist `$R/python examples/simulate_conversation.py`; `$R/python examples/simulation_cli.py 'Help me plan a release'`; `$R/python examples/run_experiment.py`; `$R/python examples/generate_baseline.py` (absolute extracted script paths, unrelated cwd) | **PASS:** all four exit 0; generated experiment and baseline JSON each contain four turns. Repository fixture files were not overwritten. |
| `git diff --check` | **PASS:** no whitespace errors. |
| GitHub Actions matrix / desktop GUI / HTTP/browser E2E | **NOT RUN:** remote CI and desktop GUI unavailable here. HTTP/browser tests are not applicable to the implemented stdio server. |

## Remaining Blockers and Residual Risk

No unresolved blocker for the verified local Linux/Python 3.13 stdio deployment.

| Unresolved item | Impact | Condition needed to clear |
| --- | --- | --- |
| Other Python versions, Windows/macOS, and remote CI execution are unverified here. | Local success does not prove all advertised interpreter/platform combinations. | Run the committed CI matrix and test any additional target platform before claiming that platform verified. |
| Actual desktop GUI executable discovery is unverified. | Desktop applications may not inherit the virtual environment's PATH. | Configure the documented absolute executable path and initialize from the intended desktop client. The underlying launchers and MCP protocol have passed. |
| Legacy snapshots may already have lost contradiction records. | Imported capped logs expose lower-bound totals and can overestimate lifetime belief coherence; old server versions can discard additive metadata on re-export. | Retain the new completeness metadata, start a fresh session for exact future-only statistics, or supply trustworthy historical totals if available. Lost events cannot be reconstructed by this release. |
| Dependency ranges permit future versions that were not tested today. | A later fresh install can resolve a different transitive dependency set. | Re-run release gates for the chosen deployment resolution; retain its wheels/constraints when exact repeatability is required. Current and minimum direct dependency combinations pass. |
