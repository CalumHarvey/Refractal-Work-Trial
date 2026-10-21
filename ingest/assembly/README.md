# ingest/assembly/

Step 2: combines the processed datasets into the training view (`data/training/`) and the Jev view
(`data/jev/`). `build_view.build()` runs the stages in this order:

| Module | Stage |
| --- | --- |
| `config.py` | Reads config/build.yaml: licence gate, source roles and data kinds, build fingerprint |
| `load.py` | Loads processed datasets, refusing stale, mixed-version or tampered inputs |
| `backfill.py` | Fills missing failure modes from deterministic rules |
| `dedup.py` | Collapses records with identical model input, keeping the strongest provenance |
| `split.py` | Group-aware splits; the InjecAgent grid; derived records follow their seeds (`EXCLUDED` when seeds disagree); counts by data kind |
| `split_plan.py` | The frozen real-data split plan (`data/splits/plan.json`) and drift from it |
| `confidence.py` | Resolves each label's confidence from its provenance rule and the calibration registry |
| `weights.py` | Training weights: confidence x source balance x class balance x hard-negative multiplier |
| `derive.py` | Derived fields: is_attack, effects, action surface, context available |
| `jev_format.py` | Records -> Jev input events (`refractal.agent-trace.v1`) and expected findings (`refractal.agent-trace-finding.v1`) |
| `leakage_audit.py` | Overlap, near-duplicate, tool-name shortcut and marker audits |
| `coverage.py` | Coverage matrix: records per failure mode x channel x decision x surface x context |
| `build_view.py` | Runs everything above and writes both folders atomically; `plan_splits()` for `--plan-splits` |
