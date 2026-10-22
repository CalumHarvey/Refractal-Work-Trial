# data/

Every dataset, intermediate and output of the pipeline lives here; each folder has its own README.
`python -m pipeline` runs the whole flow. Data flows in one direction:

```
raw/ ──ingest/run.py──► processed/ ──ingest/build.py --plan-splits──► splits/
                            ▲                                           │
                            │                          python -m generate (Gemini, via cache/)
                            │                                           ▼
                            └──── ingest/run.py <dataset> ─── derived/ (relabelled real) + generated/ (synthetic)
processed/ ──ingest/build.py──► training/ + jev/ ──python -m deliver──► delivery/ (and Jev)
```

Everything except `raw/`, `derived/`, `generated/` and `cache/` can be rebuilt from code.

**Three kinds of data** are kept apart: in folders, in every training row (`data_kind`), and in the build
report's counts (`splits.<split>.by_kind`).

| Kind | What it is | Where its runs live | Example |
| --- | --- | --- | --- |
| `real` | Converted directly from a downloaded dataset | `raw/` | TOUCAN, InjecAgent, ATBench runs |
| `relabelled_real` | Real content, new labels: a rule or model only decides where each label goes | `derived/` | PROACT steps from ATBench runs |
| `synthetic` | Content a model wrote (on top of real seeds) | `generated/` | Generated injection groups |

`ingest/run.py --status` and `ingest/build.py --status` say what is out of date. Never edit files by hand.

| Folder | What it holds | Written by | Safe to delete? |
| --- | --- | --- | --- |
| [`raw/`](raw/README.md) | Untouched downloads, one pinned snapshot per dataset (`raw/<dataset>/<commit>/` with a `manifest.json` of checksums). Treat them as untrusted data: read only, never run anything from them. See `raw/README.md` and each `DESCRIPTION.md`. | Manual download | **No** (re-downloading needs approval) |
| `processed/` | One folder per dataset, step 1's output: `records.jsonl` (schema records), `rejects.jsonl`, `report.json`, `samples/` (examples per rule) and `manifest.json` (the versions and code that made it). Each dataset is kept separate; nothing is split yet. | `ingest/run.py` | Yes, rebuild with `ingest/run.py` |
| `splits/` | `plan.json`: the frozen split of every real record. Generation draws its seeds from the train side only. | `ingest/build.py --plan-splits` | Yes, but re-plan before generating more |
| `derived/` | Relabelled real data: PROACT runs (`atbench_steps/<run>/`), read by the converters like raw downloads (see below). | `python -m generate proact …` | **No** (it cost model calls and holds human reviews) |
| `generated/` | Synthetic data and its seed libraries, read by the converters like raw downloads (see below). | `python -m generate …` | **No** (it cost model calls and holds human reviews) |
| `cache/llm/` | Every Gemini reply, one JSON file per request, by model. Re-running a generation step is free and gives the same answers. | `generate/llm.py` | Yes, but the next run makes (and pays for) every call again |
| `training/` | Step 2's training view, with real, relabelled and synthetic data combined: `train` / `validation` / `test` / `holdout` / `diagnostic.jsonl` (one flat row per record, with `data_kind`, resolved label confidence and weight), `report.json` (split counts by kind and source, leakage and shortcut audits, followers, coverage matrix) and `manifest.json`. Licensed data only. Synthetic data only ever lands in train (or diagnostic); test holds real and relabelled real data. | `ingest/build.py` | Yes, rebuild with `ingest/build.py` |
| `jev/` | The same splits in Jev's formats: `<split>/events.jsonl` (`refractal.agent-trace.v1` input events), `<split>/findings.jsonl` (the expected `refractal.agent-trace-finding.v1` finding per trace) and `<split>/index.jsonl` (the local link from each trace to its record, kind, weight and confidences; never sent), plus `manifest.json`. Always made in the same build as `training/`. | `ingest/build.py` | Yes, rebuild with `ingest/build.py` |
| `delivery/` | One folder per delivery to Jev: the request bodies actually sent (or written, in a dry run), Jev's replies, the selection and a manifest. | `python -m deliver` | Yes (a record of what was sent) |

## derived/ and generated/

| Subfolder | Holds |
| --- | --- |
| `derived/atbench_steps/<run>/` | A PROACT run (relabelled real). `boundaries.jsonl` has the first unsafe action of each ATBench run (from rules or agreeing judges). `human_check.csv` / `human_check_transcripts.md` are for the reviewer; `human.jsonl` holds the imported human decisions. Converted by `ingest/run.py atbench_steps`. |
| `generated/libraries/<side>/` | Seed libraries. `contexts.jsonl` holds real TOUCAN histories; `attacks.jsonl` holds InjecAgent attacker instructions and LLMail emails. The `train` side feeds training data; the `diagnostic` side (held-out seeds) feeds the Tier 3 diagnostic split. |
| `generated/gen_inject/<run>/` | A generation run (synthetic). `groups.jsonl` has every generated group, kept or rejected with reasons. `review_*.csv` / `review_groups.md` are review sheets; `review.jsonl` holds the imported review answers. Converted by `ingest/run.py gen_inject`. |
| `generated/archive/` | Old runs kept for reference and never converted (e.g. the first mixed-model smoke run). |

Each run folder has a `manifest.json`: the models and prompt versions used, counts, the libraries or raw snapshot it came from, and a `revision` that changes whenever the run's content changes. When a dataset has several runs, `pins` in `config/generation.yaml` chooses which one is converted.

## Licences

Only datasets with `include: true` in `config/build.yaml` enter `training/` and `jev/`. ToolSafe, R-Judge and MCPTox are `eval_only`: they are processed for internal evaluation but never trained on, never used as generation seeds and never sent to Gemini. b3 is excluded. The source licences are listed in `raw/README.md`.

## Storage note

This folder sits inside OneDrive (about 3.5 GB, mostly `raw/`). Sync can briefly lock a folder while the pipeline swaps in a new output, which shows up as a `PermissionError` on a rename. Re-run that dataset if it happens, or move `data/` out of the synced folder.
