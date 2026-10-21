# ingest/

The two deterministic steps that turn datasets into training data. Neither ever calls a model.

| Path | Role |
| --- | --- |
| `run.py` | **Step 1.** Raw (or derived / generated) input -> `data/processed/<dataset>/`. `python ingest/run.py [dataset]`; `--status` lists stale outputs |
| `build.py` | **Step 2.** Every licensed processed dataset -> `data/training/` + `data/jev/`. `--plan-splits` writes only the real-data split plan; `--status` says whether the view is current |
| [`convert/`](convert/README.md) | One converter per dataset (step 1) |
| [`common/`](common/README.md) | Shared by converters: paths, record building, rules, validation, text and tool helpers, output writing |
| [`assembly/`](assembly/README.md) | Step 2's stages: load, backfill, dedup, split, confidence, weights, Jev formatting, audits, coverage |
| [`tests/`](tests/README.md) | Tests for both steps |

Specs live outside the code: [label-schema/](../label-schema/README.md) (schema, mappings) and [config/build.yaml](../config/build.yaml).
Outputs are reproducible: the same inputs, config and code give byte-identical files.
