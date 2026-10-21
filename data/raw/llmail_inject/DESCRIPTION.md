# LLMail-Inject: email prompt-injection challenge submissions

**Snapshot:** `1063bdf01ec8762b812d5e06ee768a06faa5a6f7/` · downloaded 2026-10-20 · 10 files, 2.45 GB (large files verified against Hugging Face checksums, see `manifest.json`)
**Source:** Hugging Face [`microsoft/llmail-inject-challenge`](https://huggingface.co/datasets/microsoft/llmail-inject-challenge)
**Paper:** *LLMail-Inject: A Dataset from a Realistic Adaptive Prompt Injection Challenge* ([arXiv 2506.09956](https://arxiv.org/abs/2506.09956)), Microsoft and others
**Licence:** MIT

## What it is
Every attack submitted to Microsoft's LLMail-Inject challenge. Participants wrote an email designed to make an LLM email assistant send an email (`send_email` to a given address with a given body) while the assistant was only asked to do something harmless, such as summarise the inbox. Each submission records whether the email was retrieved, whether the level's defence flagged it, and whether the unauthorised send happened.

## Files (under `data/`)
| File | Size | Contents |
| --- | --- | --- |
| `raw_submissions_phase1.jsonl` | 1.67 GB | 370,724 submissions, 40 levels, 224 teams |
| `raw_submissions_phase2.jsonl` | 264 MB | 90,916 submissions, 30 levels, 99 teams |
| `labelled_unique_submissions_phase1.json` | 448 MB | 160,741 unique emails with a judge label |
| `labelled_unique_submissions_phase2.json` | 69 MB | 37,303 unique emails with a judge label |
| `scenarios.json` | 39 KB | The 4 scenarios: `user_query`, `task`, inbox `emails`, and `position` of the attacker email |
| `system_prompt.json` | 3 KB | The assistant's prompts: `email_client`, `tool_prompt` |
| `levels_descriptions.json` | 1 KB | Level letter → model and defence (phase 1 a–j, phase 2 k–v) |
| `objectives_descriptions.json` | 0.4 KB | Meaning of the five outcome flags |
| `emails_for_fp_tests.json` | 55 KB | 203 benign emails used for false-positive tests |

`README.md` is the dataset card.

## Record formats
**Raw submissions** (one JSON object per line):

| Field | Meaning |
| --- | --- |
| `RowKey`, `job_id` | Submission ids |
| `team_id` | Submitting team |
| `scenario` | Level code, e.g. `level1a` = scenario 1, defence letter a |
| `subject`, `body` | The attacker's email |
| `objectives` | JSON flags: `email.retrieved`, `defense.undetected`, `exfil.sent`, `exfil.destination`, `exfil.content` |
| `output` | **Not the assistant's reply**: an echo of the input ("Processed example output for prompt: …") or an error message |
| `scheduled_time`, `started_time`, `completed_time`, `Timestamp` | Job timing |

**Labelled unique submissions:** a JSON object keyed by the email text, formatted `Subject of the email: <subject>.   Body: <body>`. Each value has `attack_attempt` (True / False / Unclear, a few stored as booleans, lists or numbers in phase 1), `reason` (`judge` or `api_triggered`) and, for judge-labelled entries, `judge_answer` and `judge_category`.

**Levels** pair a model (Phi-3 or GPT) with a defence: Prompt Shield, TaskTracker, Spotlighting, LLM Judge, or all combined.

## Outcomes
| | Phase 1 | Phase 2 |
| --- | --- | --- |
| Submissions | 370,724 | 90,916 |
| Email not retrieved | 7,848 | 0 |
| Send triggered (`exfil.sent`) | 41,173 | 5,733 |
| Send with correct recipient and body | 24,456 | 3,717 |
| Send flagged by the defence (`defense.undetected` false) | 33,961 | 5,083 |
| No objectives recorded | 516 | 108 |

**Labels on unique emails** (`attack_attempt`; `reason` says who decided):

| | True | Unclear | False | Other | Decided by API trigger | Decided by judge |
| --- | --- | --- | --- | --- | --- | --- |
| Phase 1 | 125,977 + 1,399 boolean | 23,911 | 9,452 | 2 (list / number) | 21,394 | 139,347 |
| Phase 2 | 19,038 + 1,969 boolean | 13,796 | 2,500 | – | 3,165 | 34,138 |

## Things to know
- **Attack-heavy.** No submission involves a user asking to send an email, so this data cannot provide valid `send_email` examples.
- **Most sends were flagged by the defence.** `exfil.sent` appears to record the tool call even when the defence caught the email; to be audited.
- **Many near-duplicates.** Teams resubmitted variants; deduplicate to unique emails and split by team.
- **Benign material:** the 203 false-positive emails, plus about 12k unique emails the judge labelled as not attacks, can serve as harmless inbox content.

## Use in this project
Core source of BLOCK examples (sends) and attack text; benign emails feed ALLOW pairing. See `llmail_inject` in `label-schema/dataset_mappings.yaml`.
