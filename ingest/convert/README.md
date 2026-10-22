# ingest/convert/

One module per dataset; `ingest/run.py` discovers them automatically. Each defines `iter_source(snapshot)`,
`to_record(original_id, item, revision)`, a `RULES` set whose ids match the dataset's rules in
[label-schema/dataset_mappings.yaml](../../label-schema/dataset_mappings.yaml), and `report_extras(records)`.

| Module | Dataset | Kind | Granularity |
| --- | --- | --- | --- |
| `atbench.py` | ATBench (Apache-2.0) | real | trajectory |
| `injecagent.py` | InjecAgent cases + the authors' model outputs (MIT) | real | step |
| `toucan.py` | TOUCAN benign MCP runs (Apache-2.0) | real | step |
| `toolace.py` | ToolACE benign calls (Apache-2.0) | real | step |
| `when2call.py` | When2Call (CC BY 4.0) | real | step |
| `redcode.py` | RedCode-Exec risky shell / Python execution (CC BY 4.0), hosted on real TOUCAN shell tools | real | step |
| `toolsafe.py` | ToolSafe / TS-Bench (no licence: evaluation only) | real | step |
| `r_judge.py` | R-Judge (no licence: evaluation only) | real | trajectory |
| `mcptox.py` | MCPTox (no licence: evaluation only) | real | step |
| `atbench_steps.py` | PROACT steps from ATBench runs (`data/derived/atbench_steps/<run>/`) | relabelled_real | step |
| `gen_inject.py` | Generated injection groups (`data/generated/gen_inject/<run>/`), three records per group | synthetic | step |

To add a dataset: add its entry and rules to the mappings, its licence and source to config/build.yaml,
a module here, and a test in ingest/tests/.
