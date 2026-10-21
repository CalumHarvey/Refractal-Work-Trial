# ATBench: whole-run safety labels with a risk taxonomy

**Snapshot:** `4476ef92ed8f85c8d58d8a5b9dfdf55aa7893138/` · downloaded 2026-10-20 · 2 files, 18.3 MB (checksum verified against Hugging Face, see `manifest.json`)
**Source:** Hugging Face [`AI45Research/ATBench`](https://huggingface.co/datasets/AI45Research/ATBench) (Shanghai AI Lab, AgentDoG project)
**Papers:** ATBench ([arXiv 2604.02022](https://arxiv.org/abs/2604.02022)); AgentDoG ([arXiv 2601.18491](https://arxiv.org/abs/2601.18491))
**Licence:** Apache-2.0

## What it is
1,000 complete agent runs, each labelled safe or unsafe as a whole and annotated with where the risk came from, how the agent failed, and what harm resulted. Runs are synthetic but realistic, with real-looking tool schemas.

## Files
| File | Contents |
| --- | --- |
| `ATBench/test.json` | 1,000 runs (the current release) |
| `README.md` | Dataset card |

Not downloaded: the legacy 500-run release (`ATBench500/test.json`, also mirrored at the repo root) and the figures.

## Record format
`test.json` is a JSON list of run objects:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | int | Run id |
| `tool_used` | list | Tools available in the run: name, description, parameter schema (3.16 per run on average) |
| `contents` | list | The run, wrapped in one extra list: `contents[0]` is the list of turns. Roles: `user` (1,546 turns), `agent` (4,492, with thought and action), `environment` (2,971, tool results). 9.01 turns per run on average, 2 to 62 |
| `label` | int | 0 = safe (503), 1 = unsafe (497) |
| `risk_source` | string | Where the risk came from: 8 categories, or `benign` |
| `failure_mode` | string | How the agent failed: 14 categories, or `benign` |
| `real_world_harm` | string | Resulting harm: 10 categories, or `benign` |
| `reason` | string | One-line explanation of the label |

**Risk sources on unsafe runs:** inherent agent failures 135, indirect prompt injection 77, unreliable or misinformation 64, malicious user instruction or jailbreak 61, tool-description injection 52, corrupted tool feedback 44, direct prompt injection 39, malicious tool execution 25.

**Failure modes on unsafe runs:** unconfirmed or over-privileged action 71, failure to validate tool outputs 67, unauthorised information disclosure 52, flawed planning or reasoning 46, inaccurate or unverified information 40, insecure interaction or execution 39, tool misuse in context 38, inefficient or wasteful execution 37, incorrect tool parameters 36, procedural deviation or inaction 28, choosing a malicious tool 18, instructions for harmful activity 12, malicious executables 10, harmful or offensive content 3.

## Things to know
- **Safe runs come in two kinds.** 250 have `benign` in all three taxonomy fields. The other 253 carry a real risk source the agent handled correctly (e.g. an injection it ignored): these are hard negatives at the run level.
- The dataset card recommends using the fine-grained taxonomy only on unsafe runs.
- Labels apply to the whole run; there is no marker for which step went wrong.

## Use in this project
Evaluation set for the trajectory decision head; its taxonomy fields map to attack vectors and failure modes. See `atbench` in `label-schema/dataset_mappings.yaml`.
