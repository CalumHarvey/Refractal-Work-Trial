# data/training/

Written by `ingest/build.py` (step 2); replaced whole on every build, so do not edit by hand.

Real, relabelled real (PROACT) and synthetic data combined and split, licensed datasets only:

| File | Holds |
| --- | --- |
| `train.jsonl`, `validation.jsonl`, `test.jsonl`, `holdout.jsonl`, `diagnostic.jsonl` | One flat row per record: identity (record_id, dataset, source, `data_kind`, split, head, group_ids), `input`, the record's decision, auxiliary labels, resolved label confidence and status, training weight, provenance, and a pointer to its Jev trace |
| `report.json` | Split counts by data kind, source and decision; leakage, near-duplicate and shortcut audits; followers (derived records and where their seeds put them); split-plan drift; coverage matrix; weights; confidence status |
| `manifest.json` | Build fingerprint, inputs (each processed dataset's checksum and versions), file checksums |

Synthetic records only ever land in `train` (or `diagnostic`, from held-out seeds); `test` holds real and relabelled real data.
