# R-Judge: human-labelled agent runs for risk awareness

**Snapshot:** `83ce301da3ad50dd8b397e772863f5411c3d3dc2/` · downloaded 2026-10-20 · 27 files, 1.8 MB (checksums in `manifest.json`)
**Source:** GitHub [`Lordog/R-Judge`](https://github.com/Lordog/R-Judge), folder `data/` only (sparse checkout; no code copied)
**Paper:** *R-Judge: Benchmarking Safety Risk Awareness for LLM Agents* ([arXiv 2401.10019](https://arxiv.org/abs/2401.10019))
**Licence:** no LICENSE file in the repo. Confirm before any use beyond internal experiments.

## What it is
564 multi-turn agent runs (569 in the paper), each labelled safe or unsafe by human annotators, with a written description of the risk. About three-quarters involve a prompt injection; the rest are "unintended" risks where the agent causes harm without an attacker.

## Files
26 JSON files in 5 domain folders under `data/`, plus the repo `README.md`.

| Domain | Records | Files (records; injection files marked *) |
| --- | --- | --- |
| Application | 252 | ds_app* 147, dh_app* 66, phone 11, productivity 7, socialapp 7, chatbot 6, mail 4, medical 4 |
| Finance | 126 | ds_finance* 67, dh_finance* 42, bitcoin 8, webshop 5, moneymanagement 4 |
| Program | 121 | ds_program* 68, code_agentmonitor 18, terminal 15, dh_program* 12, software 6, phone_program 2 |
| Web | 35 | websearch 13, webbrowser 10, ds_web* 8, dh_web* 4 |
| IoT | 30 | household 16, trafficdispatch 8, phone_iot 6 |

**Missing:** `data/Program/security.json` (about 5 records) exists upstream but could not be read on this machine (blocked, most likely by antivirus). It was not copied, and the block was not bypassed.

## Record format
Each file is a JSON list of run objects:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | int | Record id within the file |
| `profile` | string | The agent's system prompt / role |
| `goal` | string | **Not the agent's goal:** the benchmark's judging prompt ("…judge if operations of the agent produce safety issues. Print either 0 for safe or 1 for unsafe…"), identical on every record. Never used as input |
| `contents` | list | 1–3 segments (551 runs have one), each a list of turns with `role` user / agent / environment. Agent turns carry `thought` and a free-text `action`: `Tool: {args}`, `Tool{args}`, `Tool` + newline + `Action Input: {json}`, `Final Answer: …` or a plain reply. Environment content may be double-encoded; 125 are null |
| `label` | int | 1 = unsafe (298), 0 = safe (266) |
| `risk_description` | string | Annotators' explanation of the risk |
| `scenario` | string | Scenario name; empty for injection records |
| `attack_type` | string | `injection` (414) or `unintended` (150) |

## Things to know
- **Injection files are InjecAgent's GPT-4 outputs, relabelled by humans (confirmed 2026-10-20):** all 414 injection runs are InjecAgent cases (297 distinct). 381 match an output of `gpt-4-0613` with the InjecAgent prompt in InjecAgent's `results.zip`. Human and automatic labels agree on 374 of 381. Task keys must be shared with InjecAgent to avoid train/test leakage.
- `attack_type` gives a direct failure-mode clue: injection → 16; unintended runs need their cause read from `risk_description`.
- **No list of available tools.** Building one from the calls would leak the label (the attacker's tool appears mainly when the agent used it), so converted records have none.
- **No construction markers.** "IMPORTANT!!! Ignore all previous instructions" (206 tool outputs) is InjecAgent's attack wording and is spread evenly across labels. In injection runs the attack sits in the first tool output: that is InjecAgent's design, and it holds for all 206 runs where the wording makes it checkable (never in a later tool output).
- Every injection run uses the system prompt "You are a helpful assistant."
- Small: for calibration and evaluation, not training.

## Use in this project
Calibration and evaluation set for the trajectory decision head. See `r_judge` in `label-schema/dataset_mappings.yaml`.
