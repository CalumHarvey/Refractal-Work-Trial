# data/derived/

**Relabelled real data:** runs whose content is real but whose step labels were located by rules or a
model. Converters read them like raw downloads. Not rebuildable for free: they cost model calls and hold
human checks.

| Folder | Holds |
| --- | --- |
| `atbench_steps/<run>/` | A PROACT run over ATBench: `boundaries.jsonl` (each run's first unsafe action, and how it was located), `human_check.csv` and `human_check_transcripts.md` (for the reviewer), `human.jsonl` (imported human decisions, which override the located boundaries), `manifest.json` |

Written by `python -m generate proact` (or the pipeline's `proact` stage). Converted by `ingest/run.py atbench_steps`.
