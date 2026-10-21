# data/splits/

`plan.json`: the frozen split (train / validation / test / holdout) of every real record. It is written
by `ingest/build.py --plan-splits` (or the pipeline's `plan_splits` stage) before generation, so the
seed libraries draw only on train-side records and keys.

Generated records never depend on it for safety: at build time they take their seeds' actual split. The
plan only decides which seeds generation may use. Each build reports drift from it
(`split_plan` in data/training/report.json).
