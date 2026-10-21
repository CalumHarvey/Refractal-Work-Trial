# ingest/tests/

Tests for steps 1 and 2. Run everything from the project root with `.venv/Scripts/python -m pytest`.

| File | Covers |
| --- | --- |
| `test_io.py` | Deterministic output and atomic swaps |
| `test_atbench.py`, `test_r_judge.py`, `test_toolsafe.py`, `test_injecagent.py`, `test_mcptox.py`, `test_benign.py` | One converter each (TOUCAN, ToolACE, When2Call share `test_benign.py`) |
| `test_generated_sources.py` | The relabelled and synthetic sources: grid split, followers, licence states, `atbench_steps` and `gen_inject` converters, data kinds |
| `test_assembly.py` | Step 2: confidence, splits, dedup, backfill, weights, Jev events and findings, audits, the licence gate |
