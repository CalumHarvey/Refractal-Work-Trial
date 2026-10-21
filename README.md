# Agent-security decision data pipeline

Builds labelled data for **Jev**, a model that decides whether an AI agent's next action should be
allowed or blocked. Real security datasets, relabelled real data (PROACT steps) and synthetic data
(generated injections) are converted into one record format, labelled against the Microsoft AI Red Team
taxonomy of agentic failure modes (v2.0), split without leakage, and delivered to Jev in its own formats.

## Structure

![Agent-security data framework](research/data-framework.svg)

*The full framework design ([research/data-framework.md](research/data-framework.md)). Implemented so far, as the MVP:*
- *licence-gated splits;*
- *PROACT unrolling of ATBench;*
- *generation stages G1–G3 with QC, for the tool-output injection channel;*
- *the evaluation tiers;*
- *delivery to Jev.*

*Not yet built: G4 context triples, G5 executed shell, and ToolRosetta re-rendering.*

How the code runs it, stage by stage:

```
data/raw ──convert──► data/processed ──plan_splits──► data/splits/plan.json
                            ▲                                  │
                            │                 libraries · proact · generate   (generate/, Gemini, cached)
                            │                                  ▼
                            └──── build converts new runs ── data/derived (PROACT) + data/generated (synthetic)
data/processed ──build──► data/training + data/jev ──deliver──► data/delivery ──► Jev API
```

## Run it

```bash
.venv/Scripts/python -m pipeline
```

That runs every stage in [config/pipeline.yaml](config/pipeline.yaml):

| Stage | What it does |
| --- | --- |
| `convert` | Converts every dataset whose processed output is missing or stale |
| `plan_splits` | Freezes the real-data splits |
| `libraries` | Builds the seed libraries |
| `proact` | Finds the first unsafe step in each ATBench run |
| `generate` | Generates synthetic injection groups |
| `build` | Combines everything into `data/training/` and `data/jev/` |
| `deliver` | Selects by split, kind and dataset, and sends to Jev (a dry run unless `--send`) |

Useful variants:

| Command | Effect |
| --- | --- |
| `python -m pipeline --offline` | No model calls (skips `proact` and `generate`) |
| `python -m pipeline --stages build deliver` | Rebuild and deliver only |
| `python -m pipeline --kinds real relabelled_real --send` | Send to Jev without synthetic data |
| `python -m pipeline --groups 200` | Grow the synthetic run to 200 train-side groups |
| `python -m pipeline --list` | Show which stages would run |

Model stages need `GEMINI_API_KEY`. Real delivery needs `JEV_API_KEY`. Full flags: `python -m pipeline --help`.

## Layout

| Folder | Holds |
| --- | --- |
| [`pipeline/`](pipeline/README.md) | The single command that runs every stage in order |
| [`ingest/`](ingest/README.md) | Step 1 (`run.py`: raw data -> records) and step 2 (`build.py`: records -> training view + Jev view) |
| [`generate/`](generate/README.md) | Everything that calls a model: PROACT boundaries, synthetic injections, human review sheets |
| [`deliver/`](deliver/README.md) | Selection by split / data kind / dataset, packaging, and the (placeholder) Jev API client |
| [`experiments/`](experiments/README.md) | The MVP experiment: does generated data help on real held-out data? |
| [`config/`](config/README.md) | All settings: build, generation, delivery, pipeline |
| [`label-schema/`](label-schema/README.md) | The record schema, dataset mappings and the schema guide |
| [`data/`](data/README.md) | Every dataset, intermediate and output, by stage |
| [`research/`](research/README.md) | Literature reviews, the data framework and the MVP plan |

## Three kinds of data

Every record has a `data_kind`:
- **`real`**: converted directly from a downloaded dataset.
- **`relabelled_real`**: real content with new step labels (PROACT on ATBench).
- **`synthetic`**: content a model wrote on top of real seeds.

They are counted separately in every build report and can be selected separately for delivery.
Synthetic data only ever goes to train (or the diagnostic split); test is real and relabelled real data.

## Licences

Only datasets with a clear licence enter training or delivery. ToolSafe, R-Judge and MCPTox have none:
they are evaluation-only, never trained on, never used as seeds and never sent to an external model.
See `licences` in [config/build.yaml](config/build.yaml).

## Tests

```bash
.venv/Scripts/python -m pytest
```
