# config/

Every setting the pipeline reads. Changing `build.yaml` (or the mappings, or any `ingest/` code) makes
the training view stale until it is rebuilt; `ingest/build.py --status` says so.

| File | Read by | Controls |
| --- | --- | --- |
| `build.yaml` | `ingest/build.py` (step 2) | Licence gate (`include: true / false / eval_only`, `seed`, `seeds_from`); each source's role (train / holdout / derived), data `kind` and split ratios; the InjecAgent grid split; seed splits for non-record seeds; the split plan path; weighting; Jev export settings (REVIEW mapping, finding shape, failure mode -> threat category table); audit markers |
| `generation.yaml` | `generate/` | Gemini models per role (all Gemini 3.5 Flash-Lite for now), rate limits, cache and fallbacks; pinned runs; seed library sizes; PROACT agreement; injection operators, attack mix, which contexts suit which attacks, and the QC keep threshold |
| `deliver.yaml` | `deliver/` | What is sent to Jev (splits, data kinds, datasets) and how (placeholder endpoint, auth environment variable, batch size, dry run) |
| `pipeline.yaml` | `pipeline/` | Which stages `python -m pipeline` runs, the PROACT and generation runs and sizes, delivery and experiment settings, and what happens on a model quota stop |

Command-line flags override `deliver.yaml` and `pipeline.yaml` values for one run without editing them.
