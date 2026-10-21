# ingest/common/

Helpers every converter shares. Changing any file here changes the step-1 code fingerprint, so every
processed dataset is reported stale until it is converted again.

| Module | Provides |
| --- | --- |
| `paths.py` | Project locations; `raw_snapshot()` finds a dataset's pinned input (data/raw, data/derived or data/generated); `has_input()`; schema and mappings versions |
| `record.py` | `Record`: builds one record; labels can only be set together with their provenance |
| `rules.py` | `RuleSet`: registers converter rule functions under the mapping YAML's rule ids and keeps the two in sync |
| `validate.py` | `problems()`: JSON Schema checks plus invariants the schema cannot express |
| `io.py` | Deterministic JSON (`dumps`), `read_jsonl`, the code fingerprint, atomic folder swap, and `Output`, which writes a processed dataset |
| `manifest.py` | `processed_state()`: is a processed dataset current, stale or missing? |
| `text.py` | Normalisation and hashing, so group keys line up across datasets |
| `tools.py` | Tool-list parsing and the `side_effects` keyword table |
| `react.py` | Parser for ReAct-style agent transcripts (ToolSafe, InjecAgent) |
