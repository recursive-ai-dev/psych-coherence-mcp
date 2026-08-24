# Psychological Coherence MCP: Experiment Notes

## Scope

The repository includes a deterministic four-turn simulation about workplace stress. It compares:

1. generation briefs produced with the MCP (`results/mcp_experiment_results.json`); and
2. manually written generic-assistant baselines (`results/baseline_results.json`).

Run `python examples/run_experiment.py` and `python examples/generate_baseline.py` to regenerate those files.

## Observations

### Persona stability

The baseline responses use a generic helpful-assistant voice. The MCP briefs consistently provide persona voice markers, formality and verbosity targets, formative context, and an explicit response approach. These constraints give a downstream model concrete material with which to maintain a stable character.

### Emotional calibration

The baseline tends to move quickly into practical advice. The MCP analysis identifies lexical distress signals and emits directives such as acknowledging emotion before problem-solving, lowering activation, or limiting the number of options presented.

### Dialogue state

Each turn updates topic state, dialogue phase, short-term context, and the blended user profile. The generated phase guidance therefore changes as the conversation moves from opening and information gathering toward problem solving or closing.

### Coherence reporting

The experiment records topic, memory, belief, profile-stability, and composite coherence scores. These scores are transparent heuristic diagnostics; they are not externally validated measurements of human conversational quality.

## Limitations

This fixture demonstrates that the server produces evolving, internally consistent constraints. It does **not** establish a statistically significant improvement in model outputs: the baseline is hand-authored, no downstream model responses are scored blindly, and the scenario contains only four turns. A stronger evaluation would use multiple models, randomized conversations, human raters, predefined rubrics, and repeated trials.

## Conclusion

The experiment supports the narrower claim that the MCP supplies structured state and persona guidance that a stateless prompt does not. Whether that guidance improves a particular model's final responses remains an empirical question for a controlled downstream evaluation.
