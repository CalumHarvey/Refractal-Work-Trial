# data/generated/

**Synthetic data** (content a model wrote on top of real seeds) and the seed libraries it is built from.
Not rebuildable for free: it costs model calls and holds human reviews.

| Folder | Holds |
| --- | --- |
| `libraries/<side>/` | Seeds. `contexts.jsonl` holds real TOUCAN histories; `attacks.jsonl` holds InjecAgent attacker instructions and LLMail emails. `train` seeds feed training data; `diagnostic` seeds (held out) feed the Tier 3 split. Rebuilt by `python -m generate libraries` |
| `gen_inject/<run>/` | A generation run: `groups.jsonl` (every group, kept or rejected with reasons), `review_*.csv` and `review_groups.md` (review sheets), `review.jsonl` (imported review answers), `manifest.json`. Converted by `ingest/run.py gen_inject` |
| `archive/` | Old runs kept for reference and never converted |

When a dataset has several runs, `pins` in config/generation.yaml chooses the one that is converted.
