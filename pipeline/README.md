# pipeline/

One command for the whole pipeline: `python -m pipeline`. It calls the other packages in order and prints
a summary per stage. Settings: [config/pipeline.yaml](../config/pipeline.yaml); every value can be
overridden with a flag (`--help`).

| Stage | Calls | Model calls |
| --- | --- | --- |
| `convert` | `ingest/run.py` for every dataset whose output is missing or stale | No |
| `plan_splits` | `ingest/build.py --plan-splits` | No |
| `libraries` | `generate.libraries` | No |
| `proact` | `generate.proact`: resumes the PROACT run | Yes |
| `generate` | `generate.inject`: grows the run to the configured groups per side | Yes |
| `build` | Converts whatever changed (e.g. new runs), then `ingest/build.py`: combines everything into `data/training/` and `data/jev/` | No |
| `deliver` | `deliver`: selection and sending to Jev | No |
| `experiment` | `experiments.mvp.run` (only with `--experiment` or when listed in the config) | Only with `--reference` |

| Module | What it does |
| --- | --- |
| `stages.py` | One function per stage, plus `Settings` |
| `__main__.py` | Command line: stage choice (`--stages`, `--from`, `--skip`, `--offline`, `--experiment`, `--list`), model-stage sizes, delivery mode and selection |
| [`tests/`](tests/README.md) | Tests |

**On a daily quota stop** in a model stage, with `on_quota: continue` (the default), the remaining model
stages are skipped. Build and deliver still run with the data generated so far, and the command exits 3.
Running it again later resumes from the cache.
