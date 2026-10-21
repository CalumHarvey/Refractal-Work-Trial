# pipeline/tests/

| File | Covers |
| --- | --- |
| `test_pipeline.py` | Stage choice and order (`--stages`, `--from`, `--skip`, `--offline`, `--experiment`); config overrides reaching the stages and the delivery selection; a quota stop skipping later model stages but still building and delivering (exit 3); a failed stage stopping the pipeline (exit 1). Stages are replaced by recorders, so nothing heavy runs |
