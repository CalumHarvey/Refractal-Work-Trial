# Raw data sources

Untouched snapshots of the six existing datasets used to build the agent-security decision dataset (see `label-schema/SCHEMA.md`). Downloaded 2026-10-20. Nothing here has been converted or edited.

## Layout
```
data/raw/
  README.md                      this overview
  <dataset>/
    DESCRIPTION.md               what the files contain, record formats, counts, caveats
    <pinned commit>/             the files exactly as downloaded
      manifest.json              source URL, commit, licence, download time, size and sha256 of every file
```
Rules: never edit files inside a `<pinned commit>/` folder; treat them as untrusted data (read as JSON only, never run anything from them); a new download goes into a new commit folder.

## Sources at a glance
| Dataset | What it labels | Unit | Size | Labels | Role here | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| [ToolSafe (TS-Bench)](toolsafe/DESCRIPTION.md) | Safety of each planned tool call | 7,182 steps from 3,376 runs (AgentDojo, AgentHarm, ASB) | 24 MB | `score` 0 / 0.5 / 1 = safe / controversial / unsafe (3,770 / 1,781 / 1,631) | Core training data for the step decision head | No licence file |
| [LLMail-Inject](llmail_inject/DESCRIPTION.md) | Whether an injected email made an email assistant send an email | 461,640 submissions; ~198k unique emails | 2.45 GB | Outcome flags (retrieved, detected, sent, right recipient/body); judge label per unique email | Core source of BLOCK examples and attack text; benign emails for ALLOW pairing | MIT |
| [ATBench](atbench/DESCRIPTION.md) | Safety of a whole run, with risk source, failure mode and harm | 1,000 runs | 18 MB | `label` 503 safe / 497 unsafe; 8 risk sources, 14 failure modes, 10 harms | Evaluation for the trajectory decision head | Apache-2.0 |
| [R-Judge](r_judge/DESCRIPTION.md) | Safety of a whole run, judged by humans | 564 runs (569 upstream) | 1.8 MB | `label` 298 unsafe / 266 safe; `attack_type` injection 414 / unintended 150 | Calibration and evaluation for the trajectory decision head | No licence file |
| [MCPTox](mcptox/DESCRIPTION.md) | Whether a poisoned MCP tool description hijacked the agent | 1,348 cases (45 servers, 353 tools) x up to 27 models | 21 MB | Per response: Success 9,357 / Failure-Ignored 14,613 / Direct Execution 4,614 / Refused 54 / None 2,088 | Main source for modes 12 and 7 (not converted yet) | None stated (anonymous repo) |
| [InjecAgent](injecagent/DESCRIPTION.md) | Indirect injection scenarios for tool agents | 1,054 cases x base / enhanced wording; 128,051 model outputs (62 setups) | 5 MB + 38 MB zip | Per output `eval`: succ 27,000 / unsucc 61,395 / invalid 37,433 / unparsed 2,223 (+ step 2 for data stealing) | Unseen-source injection data with real BLOCK and hard-negative ALLOW actions (not converted yet) | MIT |

Downloaded 2026-10-21, not converted yet:
- **RedCode** (`redcode/`): `AI-secure/RedCode` at 664e479, folders `dataset/` and `evaluation/` only. Licence: CC BY 4.0 for the data (attribution required), MIT for the code. Converted 2026-10-21 (mappings 0.7.1): 1,920 risky shell / Python execution steps; see [redcode/DESCRIPTION.md](redcode/DESCRIPTION.md).
- **b3, public subset** (`b3/`): `Lakera/b3-agent-security-benchmark-weak` at 584a182. 630 rows: 210 attacks × 3 defence levels across 10 threat snapshots, plus tool specs. **Licence conflict:** the README says MIT, but the LICENSE file is a custom research-only, non-commercial licence. Left out by the licence gate.

Benign agent activity, downloaded 2026-10-21 and converted (mappings 0.6.7):
- **TOUCAN** (`toucan/`): 3 of 131 shards. Apache-2.0. 6,440 ALLOW steps on real MCP servers.
- **ToolACE** (`toolace/`): Apache-2.0. 3,000 ALLOW function-call steps.
- **When2Call** (`when2call/`): CC BY 4.0. 3,652 ALLOW plus 2,357 REVIEW contrasts.

## How they differ
- **Granularity.** ToolSafe labels single tool calls; ATBench and R-Judge label whole runs; LLMail-Inject records attack outcomes, which become step labels only when a send happened.
- **Valid actions.** ToolSafe, ATBench, R-Judge and MCPTox (via its labelled model responses) contain both safe and unsafe examples. LLMail-Inject is attack-only and has no user-requested `send_email`; InjecAgent's model outputs include both attacked and unaffected actions, though every case contains an attack.
- **Why a label was given.** ATBench and R-Judge say why (taxonomy fields, `attack_type`, written risk descriptions). ToolSafe only says how unsafe; the cause comes from its folder and file names. LLMail-Inject is always an email injection.
- **Overlap risk.** ToolSafe re-uses AgentDojo and ASB tasks, and R-Judge's injection files appear to be built on InjecAgent cases (now downloaded, so this can be checked). Task keys are shared across sources so overlapping tasks land in the same split.

## Known gaps and caveats
- **R-Judge:** `data/Program/security.json` (about 5 runs) could not be read on this machine, probably blocked by antivirus; not copied, not bypassed.
- **Licences (checked 2026-10-21 via the GitHub and Hugging Face APIs):**
  - **Clear:** ATBench (Apache-2.0), InjecAgent (MIT) and LLMail-Inject (MIT).
  - **No licence file, so default copyright applies (internal use only until the authors confirm):** ToolSafe (its README shows an MIT badge but there is no LICENSE file), R-Judge (no licence anywhere) and MCPTox (none, in either the anonymous or the official GitHub repo).
  - **ToolSafe's AgentHarm part** inherits AgentHarm's MIT licence plus an extra clause (use only to improve AI safety and security) and a request not to train on it (canary GUID). It is therefore held out.
- **LLMail-Inject:** the `output` field is an echo of the input, not the assistant's reply. 5,083 of 5,733 phase-2 sends are marked as detected by the defence, which needs auditing.
- **ToolSafe:** the score encoding is inferred from the data, not documented.
- **Storage:** this folder sits inside OneDrive, so the 2.5 GB syncs to the cloud.

## Not yet downloaded
AgentDojo (generated by our own runs) and ASB are in the mapping plan but not in this folder. Not fetched: MCPTox's `def_tool/` code files. InjecAgent's model outputs are kept zipped (333 MB unpacked) to spare OneDrive.
