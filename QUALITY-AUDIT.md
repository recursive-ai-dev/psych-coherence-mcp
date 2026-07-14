# Code Quality Audit Report

### 1. Substring Matching Bugs in Phase, Need, and Trigger Detection
1. **File(s) and line numbers**: `server.py`, lines 812-814 (`detect_needs`), lines 837-839 (`detect_triggers`), lines 1042-1044 (`update_dialogue_phase`).
2. **The specific problem**: The use of `any(ind in text_lower for ind in indicators)` performs raw substring matching. Indicator words like "hi" will match inside "this", "own" matches "down", and "rush" matches "crush".
3. **Why it matters**: The system will erroneously detect greetings, needs, and emotional triggers during completely unrelated conversations, throwing off the dialogue phase and generation constraints with false emotional vulnerability or closing signals.
4. **The proposed fix**: Use word-boundary regular expressions instead of the `in` operator. Pre-compile a regex for each category (e.g., `re.compile(r'\b(?:' + '|'.join(map(re.escape, indicators)) + r')\b')`) and use `.search(text_lower)` to check for exact word matches.
5. **Overlap**: Touches `detect_needs`, `detect_triggers`, and `update_dialogue_phase`. No overlap with other items.

### 2. False Continuations in Topic Tracking Due to Substring Matching
1. **File(s) and line numbers**: `server.py`, line 1012 (`update_topic_state`).
2. **The specific problem**: The condition `any(kw in previous for kw in topics[:3])` uses a raw substring check. If `previous` is the topic "python programming", and the new keyword is "on", it evaluates to True because "on" is a substring of "python".
3. **Why it matters**: The system will falsely identify completely unrelated topics as continuations of the previous topic, preventing the dialogue phase from correctly shifting and incorrectly inflating the topic confidence score.
4. **The proposed fix**: Change the condition to ensure whole-word matches against the previous topic. For example: `any(kw == previous or kw in previous.split() for kw in topics[:3])`.
5. **Overlap**: None.

### 3. Memory Access Count Mutated for Discarded Memories
1. **File(s) and line numbers**: `server.py`, lines 1779-1786 (inside `psy_generate_response`), and lines 1918-1929 (`psy_recall`).
2. **The specific problem**: The relevance loops iterate over all memories and immediately increment `mem.access_count` if `relevance > 0.1` (or `0.05`), but the results are then sliced to only keep the top 5 (`relevant_memories = relevant_memories[:5]`).
3. **Why it matters**: Memories that score highly but rank 6th or lower still get their `access_count` permanently incremented. Since `access_count` boosts future relevance scores, these discarded memories will artificially snowball in score over time, displacing genuinely relevant memories without ever actually being injected into the LLM context.
4. **The proposed fix**: Remove the `mem.access_count += 1` line from the initial relevance computation loop. Instead, after sorting and slicing the top `max_results`, iterate over the final selected memory objects and increment their `access_count`.
5. **Overlap**: None.

### 4. Duplicate Appends in Topic History
1. **File(s) and line numbers**: `server.py`, lines 1025-1027 (`update_topic_state`).
2. **The specific problem**: When shifting to a new topic, the code appends `previous` to `state.topic_history`, and then immediately appends `new_topic`. However, `previous` was already appended to `topic_history` when it originally became the `current_topic`.
3. **Why it matters**: This inserts duplicate sequential entries of the previous topic into the history (e.g., `['A', 'A', 'B']`). In `compute_coherence_score`, `topic_total` uses the length of this array, and sequential duplicates aren't counted as topic changes. This artificially inflates the `topic_coherence` score, making the session seem more coherent than it actually is.
4. **The proposed fix**: Delete the line `state.topic_history.append(previous)` (line 1025). Just assign `state.current_topic = new_topic` and append `new_topic` to the history.
5. **Overlap**: None.

### 5. Unhandled Empty String Crash in `humanize_text`
1. **File(s) and line numbers**: `server.py`, lines 1391-1393.
2. **The specific problem**: If the original text contained only punctuation (e.g., `"."`), the `extract_sentences` filter will yield an empty `processed_sentences` list, making `humanized` an empty string `""`. The code then attempts to access `humanized[0]`, causing an `IndexError`.
3. **Why it matters**: A user submitting a single punctuation mark or a string that gets entirely filtered out by the tokenizer will crash the MCP server with an unhandled exception instead of degrading gracefully to a blank response.
4. **The proposed fix**: Add a length/truthiness check before applying the persona starter: `if humanized and random.random() < 0.25 and voice.get("preferred_starters"):`.
5. **Overlap**: None.

### 6. Uppercase Ratio Logic Fails to Exclude Sentence Starters
1. **File(s) and line numbers**: `server.py`, lines 580-584 (`compute_linguistic_features`).
2. **The specific problem**: Despite the comment stating it excludes first characters of sentences, the implementation extracts all alphabetic characters from the raw text and checks `.isupper()`, completely failing to filter out the sentence starters.
3. **Why it matters**: The `uppercase_ratio` metric will be artificially inflated for all well-formatted inputs because standard capitalization is penalized. This skews downstream heuristics that rely on this feature to detect shouting or intense emotional expression.
4. **The proposed fix**: To accurately exclude first characters, iterate over the list returned by `extract_sentences(text)`. For each sentence, strip leading whitespace, remove the first character if it's alphabetic, and concatenate the remainders. Then compute the uppercase ratio on that filtered string.
5. **Overlap**: None.

### 7. Redundant Datetime Parsing and Evaluation in Loops
1. **File(s) and line numbers**: `server.py`, lines 949-950 (`compute_memory_relevance`) and lines 1089-1090 (`compute_coherence_score`).
2. **The specific problem**: Both functions evaluate `utc_now()` and parse string timestamps into datetimes via `parse_timestamp` inside a loop iterating over all long-term memories.
3. **Why it matters**: For sessions with hundreds of accumulated memories, calling system time and executing ISO string-to-datetime parsing on every loop iteration during every response turn creates unnecessary CPU overhead and introduces minor time drift across the loop.
4. **The proposed fix**: Capture the current time once outside the loop (`now = utc_now()`). Inside the loop, subtract the parsed memory timestamp from `now`.
5. **Overlap**: Touches `compute_memory_relevance` and `compute_coherence_score`.

### 8. Redundant Regex Compilation in Tokenizer
1. **File(s) and line numbers**: `server.py`, lines 558-559 (`tokenize`).
2. **The specific problem**: The regex `re.sub(r"^[^\w]+|[^\w]+$", "", t.lower())` is defined and evaluated dynamically inside a loop for every single word in the text.
3. **Why it matters**: `tokenize` is a foundational utility called multiple times per request (during linguistic feature extraction, emotion analysis, trait analysis, etc.). Forcing the regex engine to parse and evaluate the pattern for every word adds up to significant wasted overhead.
4. **The proposed fix**: Hoist the regex compilation to the module level (e.g., `TOKEN_CLEANUP_RE = re.compile(r"^[^\w]+|[^\w]+$")`), and use `TOKEN_CLEANUP_RE.sub("", t.lower())` inside the loop.
5. **Overlap**: None.

### 9. Redundant Set Instantiations in Linguistic Features
1. **File(s) and line numbers**: `server.py`, lines 590, 595, 600 (`compute_linguistic_features`).
2. **The specific problem**: The sets `first_person`, `hedges`, and `intensifiers` are defined directly inside the function body.
3. **Why it matters**: These sets are allocated and populated in memory every single time `compute_linguistic_features` is called, creating unnecessary garbage collection overhead on every turn.
4. **The proposed fix**: Move the definitions of `first_person`, `hedges`, and `intensifiers` to the module level as global constants.
5. **Overlap**: None.
