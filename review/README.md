**Adversarial review of commit `36134295c2d6c482e070ff6323bf390e6f3d3e15`, 2026-09-29**

The original review found three P1 safety failures and three P2 correctness/release-check failures. All six are now addressed in the working tree. The findings and pre-fix evidence below are retained as historical context.

The fixes normalize safety whitespace, recognize explicit family targets, retain unresolved session safety context, scope emotion negation locally, distinguish farewells from continuing requests, and use the interpreter's scripts directory for console launch tests. Urgent context now has an explicit client resolution flag, persists through snapshots and history eviction, and continues to govern delayed response recording. The README documents its conservative legacy migration and resolution contract.

Regression coverage is now part of the default release suite in [test_review_findings.py](../tests/test_review_findings.py) and [test_review_safety.py](../tests/test_review_safety.py). The original cases are expected to pass after these fixes. Additional cases cover resolution over stdio, fresh risk during resolution, alternate session tools, malformed snapshot rejection, history eviction, legacy migration, benign phrases, local negation and genuine farewells.

Post-fix validation: **199 tests passed in 16.26 seconds against the installed wheel**, including all 18 tools through the module, console and compatibility launchers. Formatting (38 files), Ruff lint, strict mypy (12 source modules), integration (66/66), capability regressions, adversarial checks (114/114), `pip check`, and warning-free import passed. The wheel was built from a freshly built sdist and installed into `/tmp/psych-review-fixes-zcxokn6x/env`; import resolved under that environment's `site-packages`. The sdist includes both new regression modules. Artifacts are in `/tmp/psych-review-fixes-zcxokn6x/dist`; the wheel SHA-256 is `066512f4602a55627e617e7b10c80fcac1af9aa2f4d4e8ce7421eda70dd96bbd`.

This fix validation ran on Linux/Python 3.13.15. The Windows correction was verified through path simulation; native Windows CI and other interpreter/platform combinations were not rerun locally. No package was published or deployed.

P1 means address before relying on the affected safety behavior. P2 means a reproducible functional or release-verification defect. These findings concern the server's own signals and directives; no downstream model response or clinical outcome was evaluated.

| ID | Priority | Finding | Primary location |
| --- | --- | --- | --- |
| R1 | P1 | Harmless whitespace changes disable harm detection and permit harm text as a memory candidate | `src/psych_coherence_mcp/analysis.py:556` |
| R2 | P1 | An unresolved urgent exchange loses safety priority on its next turn | `src/psych_coherence_mcp/server.py:340` |
| R3 | P1 | Explicit threats against family members are classified as no risk | `src/psych_coherence_mcp/analysis.py:566` |
| R4 | P2 | Global negation counting turns unambiguously negative emotion positive | `src/psych_coherence_mcp/analysis.py:174` |
| R5 | P2 | Polite acknowledgments and ordinary uses of “later” close ongoing conversations | `src/psych_coherence_mcp/coherence.py:225` |
| R6 | P2 | Windows release test looks for the console executable in the wrong directory | `tests/test_release_transport.py:20` |

**R1 — Normalize whitespace without losing phrase and clause meaning.**

The input `I want to kill myself tonight.` yields `high`, as expected by existing tests. Replace the space between `kill` and `myself` with two spaces, a tab, a newline, or a nonbreaking space: the same input now yields `none`. The generated brief has no `safety_first` priority, enables humanization, and includes the statement as a semantic goal memory candidate with importance 0.65. Nothing is automatically stored; the error is in the proposed candidate and generation guidance.

The harm patterns contain literal single spaces, and the clause splitter also breaks at newlines before matching. Fixing only `\s+` in the phrase regex is insufficient for line-wrapped phrases. Normalize appropriately before splitting/matching, preserve original text/source offsets for extraction, and test the downstream brief and candidate suppression as well as standalone triage. The same sensitivity affects other multiword safety patterns.

Reproducer: `test_harm_detection_survives_whitespace`, four real stdio cases.

**R2 — Preserve unresolved safety context across turns and restoration.**

Create a session and generate for `I want to kill myself tonight.` Record an assistant response that asks about immediate danger and suggests human support. Then generate for `Yes, and I have a plan.` The first brief has safety priority. The second reports `none`, removes safety priority, and reenables humanization. Recording `Let us focus on your plan.` for the second generation returns `safety_response_required=false` and `passes_safety_check=true`.

`psy_generate_response` calls `full_analysis` only on the new text; the prior risk stored in `response_history` does not inform the next generation. The same failure occurs after exporting and importing the session, even though the original urgent turn and response history remain present. Brief context still contains previous messages, so a downstream model might independently recover the risk; the explicit flags supplied to that model and the response checker are nevertheless wrong.

Track unresolved session safety context with an explicit resolution policy. Use the effective context for generation priority, humanization, memory-candidate handling, and the risk stored against the new generation ID. Preserve this state through snapshots. Do not let an elliptical follow-up implicitly clear it. Keep the standalone assessment stateless if that is its intended contract.

Reproducer: `test_unresolved_safety_context_survives_followup_and_restore`, including both original and restored sessions and subsequent response recording.

**R3 — Recognize explicit human targets beyond the small pronoun list.**

`I want to kill them tonight.` yields `high`. Replacing `them` with `my wife` or `my children` yields `none`; ordinary persona guidance and humanization remain active. The wife example also produces a goal memory candidate. This is a failure on direct, ordinary threat wording, not an inference about euphemisms or indirect distress.

The violence regex accepts only `him|her|them|someone|people` after the harm verb. Extend recognition to common explicit human targets, with controls for negation and benign technical phrases such as killing a process. Ensure memory extraction shares the corrected assessment.

Reproducer: `test_explicit_human_targets_are_detected`, two real stdio cases with a detected-pronoun control.

**R4 — Scope negation to the emotion it modifies.**

`I am depressed. Nobody cares. Nothing helps.` produces `primary_emotion=sadness` but positive `valence=0.5`. Generation consequently adds `This is a good moment for deeper exploration or gentle challenge.` The two negative words in separate sentences cause the entire utterance's valence to be multiplied by -0.5. Conversely, `I am not happy.` retains `joy` and `valence=1.0` because a single negator is ignored.

Apply negation locally to relevant lexical evidence rather than flipping an aggregate score based on a message-wide count. Test the generated tone directives, because an internally bounded score can still drive the wrong behavior.

Reproducer: `test_unrelated_negatives_do_not_invert_sadness`. The single-negation counterpart was also confirmed through direct analysis.

**R5 — Detect an actual farewell before setting the closing phase.**

Both `Thank you, how do I deploy this?` and `I will deal with this later, but how do I fix the bug now?` produce `dialogue_phase=closing` and `Wrap up warmly. Summarize key points if appropriate.` Closing-token detection runs before need detection and matches `thank you` and `later` anywhere in the message. A token boundary prevents substring errors but does not distinguish a farewell from an ongoing request.

Use farewell context, and account for a continuing question or request before selecting closing. Preserve genuine farewell behavior with controls.

Reproducer: `test_ongoing_questions_do_not_close_dialogue`, two real stdio cases.

**R6 — Resolve console scripts through the installation's scripts directory.**

The CI matrix includes Windows using `actions/setup-python` and installs into that interpreter directly. For an executable such as `C:\hostedtoolcache\windows\Python\3.13\x64\python.exe`, the test constructs `...\x64\psych-coherence-mcp.exe`. The Windows installation scheme places console scripts in `...\x64\Scripts\psych-coherence-mcp.exe`. The console case therefore cannot launch the installed entry point in that CI layout. Linux success does not exercise this difference.

Use the interpreter's `sysconfig.get_path("scripts")` to locate the generated executable. The reproduction invokes the actual committed test's path-construction branch with Windows paths and captures its chosen command; it is a deterministic simulation, not a native Windows execution.

Reproducer: `test_windows_release_launcher_uses_scripts_directory`.

**Original review verification and reproducibility (before fixes)**

The review covered runtime analysis, generation constraints, memory/belief handling, response identity, bounded state, snapshot validation/migration, package entry points, CI, and existing regression coverage. Additional exploratory import probes exercised nested memory content through generation without finding a current-interpreter failure; speculative issues were not promoted into findings.

| Check | Result |
| --- | --- |
| Existing `.venv/bin/python -m pytest -q` | 130 passed in 10.51 seconds |
| Existing formatting, Ruff lint, strict mypy | Passed; 35 original Python files formatted, 12 source files type-checked |
| Integration script | 66/66 passed |
| Capability regression script | Passed |
| Adversarial script | 114 passed, 0 failed, 0 critical |
| Clean committed-source wheel build | Passed using `git archive HEAD` and isolated `pip wheel --no-deps` |
| Wheel inspection | 12 runtime Python modules, typing marker and console entry point present; no tests/examples/review package |
| Fresh runtime environment installation and `pip check` | Passed; import resolves under that environment's `site-packages` |
| Installed-wheel real stdio smoke checks | All 18 tools passed through module, console and compatibility launchers, from an unrelated directory |
| New review cases against installed wheel | **11 failed in 6.66 seconds**, each at the intended behavioral assertion; 10 actual stdio cases plus 1 Windows path simulation |
| Review reproducer formatting and lint | Passed |

The original checks asserted the desired behavior and failed on the reviewed commit. They have since moved into the default `tests/` testpaths and now serve as regressions. To rerun against the checkout's installed package:

```sh
.venv/bin/python -m pytest -q tests/test_review_findings.py tests/test_review_safety.py --tb=short
```

For the original review, the clean wheel and runtime environment were created under `/tmp/psych-bedbug-review-_3waps_d`. The historical installed-wheel reproduction, before the test file moved, was:

```sh
PSY_REVIEW_PYTHON=/tmp/psych-bedbug-review-_3waps_d/runtime/bin/python \
  .venv/bin/python -m pytest -q review/test_review_findings.py --tb=short
```

Its output is `/tmp/psych-bedbug-review-_3waps_d/wheel-reproductions.txt`. The wheel's SHA-256 is `77ca5a013c8104d891b00dd46760350eee316428d5f2c2de9e2743b0f19f7d57`. Temporary paths describe this local run and are not portable dependencies of the reproducer.

Native execution was Linux/Python 3.13.15 with the fresh runtime resolving MCP 1.30.0 and Pydantic 2.13.5. This pass did not run native Windows/macOS, other Python versions, a minimum-dependency matrix, remote GitHub Actions, or a downstream language model. The Windows finding is supported by actual path-construction simulation and the standard library's Windows installation scheme. No claim of a bug-free release follows from the passing checks.
