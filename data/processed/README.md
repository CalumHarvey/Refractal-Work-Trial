# data/processed/

Step 1's output (`ingest/run.py`): one folder per dataset, holding records in the project's schema.
Each dataset is kept separate here; nothing is split or combined yet. Rebuildable at any time.

| File (per dataset) | Holds |
| --- | --- |
| `records.jsonl` | One schema record per line |
| `rejects.jsonl` | Items that failed conversion or validation, with the reasons |
| `report.json` | Counts, rule hits, label summary and dataset-specific reconciliation checks |
| `samples/<rule>.jsonl` | Up to 20 records per rule, for spot checks and audits |
| `manifest.json` | The mappings, schema, code fingerprint and input revision that produced it |

Each folder is replaced atomically by its run (`<dataset>.tmp` / `.old` are left only by an interrupted run).
`ingest/run.py --status` lists what is stale.
