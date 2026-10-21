# ToolSafe (TS-Bench): step-level tool-call safety labels

**Snapshot:** `46358fa424a927a895c6c8322f99032c4eb5155e/` · downloaded 2026-10-20 · 10 files, 24.0 MB (checksums in `manifest.json`)
**Source:** GitHub [`MurrayTom/ToolSafe`](https://github.com/MurrayTom/ToolSafe), folder `TS-Bench/` only (sparse checkout; no code copied)
**Paper:** *ToolSafe: Enhancing Tool Invocation Safety of LLM-based Agents via Proactive Step-level Guardrail and Feedback* ([arXiv 2601.10156](https://arxiv.org/abs/2601.10156))
**Licence:** no LICENSE file in the repo; the README shows an MIT badge only. Confirm before any use beyond internal experiments.

## What it is
7,182 agent steps, each a single planned tool call with the context that led to it and a safety score. The runs were sampled by the ToolSafe authors from three existing benchmarks (AgentDojo, AgentHarm, ASB) and labelled step by step. It is the only source in this set with native per-call labels that include a middle "controversial" class.

## Files
| File (under `TS-Bench/`) | Steps | Runs | Score 0 | Score 0.5 | Score 1 |
| --- | --- | --- | --- | --- | --- |
| `agentdojo-traj/banking.json` | 87 | 45 | 59 | – | 28 |
| `agentdojo-traj/slack.json` | 101 | 28 | 82 | – | 19 |
| `agentdojo-traj/travel.json` | 177 | 42 | 157 | – | 20 |
| `agentdojo-traj/workspace.json` | 855 | 474 | 570 | – | 285 |
| `agentharm-traj/benign_steps.json` | 206 | 125 | 206 | – | – |
| `agentharm-traj/harmful_steps.json` | 525 | 72 | – | 315 | 210 |
| `asb-traj/test/DPI_attack_success.json` | 2,293 | 1,228 | 988 | 672 | 633 |
| `asb-traj/test/OPI_attack_success.json` | 2,509 | 1,105 | 1,279 | 794 | 436 |
| `asb-traj/test/atttack_failure.json` (sic) | 429 | 257 | 429 | – | – |
| **Total** | **7,182** | **3,376** | **3,770** | **1,781** | **1,631** |

`README.md` is the repo's own readme.

## Record format
Each file is a JSON list of step objects:

| Field | Type | Meaning |
| --- | --- | --- |
| `id-interaction` | id | The run the step belongs to |
| `id-segment` | id | Position of the step within the run |
| `instruction` | string | The user's request |
| `history` | string | Earlier steps as free text in ReAct style: `(n) Thought: … Action: … Action Input: … Observation: …` |
| `current_action` | string | The step being judged, same text style |
| `env_info` | string | Tool descriptions as text (`name: description` + `parameters:` block) |
| `score` | number | 0, 0.5 or 1 |
| `attacker_tool` | string | ASB files only: the attacker's tool for this case |
| `aggressive` | bool | ASB files only |
| `attack_success` | bool | ASB files only: true in the two `*_attack_success` files, false in `atttack_failure` |

## Things to know
- **Score encoding is inferred, not documented:** 0 = safe, 0.5 = controversial, 1 = unsafe. Every benign and failed-attack step is 0, which supports this; confirm against the paper.
- **The source benchmark is only in the path:** folder → agentdojo / agentharm / asb; AgentDojo suite = file stem; ASB attack type = file stem (DPI = direct prompt injection, OPI = observation/indirect injection). The failed-attack file does not record which type was used.
- **No task id.** Only `id-interaction`, so the cross-dataset task key is a hash of the normalised instruction text.
- **Context is text, not structured messages.** A converter must parse the ReAct blocks into messages and tool calls.
- **Ids are not unique.** 205 AgentHarm harmful steps share file, `id-interaction` and `id-segment` with a different candidate action; converted records are identified by row position in the file.
- **Attack templates locate every attack exactly.** AgentDojo: an `<INFORMATION> … </INFORMATION>` block in a tool output (673 steps, including all 352 unsafe ones; the other 547 come before the injection and are all safe). ASB DPI: "You must strictly adhere to the following instruction" appended to the instruction (all 2,293). ASB OPI: "Now you need to pay attention to the following request" in a tool output (1,345 OPI steps and 172 failed-attack steps; the rest are first steps before the injected output arrives).
- **The failed-attack file is OPI-only.** None of its steps use the DPI wording.
- **ASB's attacker tool is always in `env_info`**, and in 2,527 of the 2,535 steps scored 0.5 or 1 the planned call is that tool (never at score 0).
- **Text quirks the parser handles:** shifted step numbers (`(3) Action` / `(4) Action Input`), a sentence before the real `Action`, code-fenced or commented arguments, `Action: None` followed by `Final Answer:` (343 actions, 905 history steps), `Action: Final Answer`, two malformed tool names, and one history that starts with `Observation:`. 411 actions are final answers rather than tool calls.
- **Only ASB is explicitly marked as test data** (`asb-traj/test/`). AgentHarm-derived steps also form ToolSafe's test set per the paper: keep them out of training.

## Use in this project
Core training source for the step-level decision head (score → ALLOW / REVIEW / BLOCK). See `toolsafe` in `label-schema/dataset_mappings.yaml`.
