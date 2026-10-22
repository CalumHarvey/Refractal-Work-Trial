# Public datasets for agent security decisions: survey and decisions

*21 October 2026. This covers the datasets surveyed for Jev's ALLOW / REVIEW / BLOCK decisions on an agent's next action, across the four target categories: risky shell commands, unauthorised tool calls, prompt injection, and benign agent activity.*

**Basis of the figures:**
- **Downloaded datasets:** licences checked against each repository's licence files (2026-10-21); counts are the converted record counts in `data/processed/` (mappings 0.7.1).
- **Candidates not downloaded:** details come from their papers and repositories as reviewed during the survey, and were not re-verified.

## 1. Summary

| | Shell commands | Unauthorised tool calls | Prompt injection | Benign activity |
| --- | --- | --- | --- | --- |
| **Licensed data in the build** | RedCode (1,920, all BLOCK / REVIEW) | Injection-driven calls only (InjecAgent, ATBench) | InjecAgent, ATBench, PROACT steps, generated groups | TOUCAN, ToolACE, When2Call, plus the ALLOW halves of injection sets |
| **Evaluation only (no licence)** | none | ToolSafe (ASB attacker tools), MCPTox | ToolSafe, R-Judge, MCPTox | ToolSafe benign steps |
| **Main gap** | No benign shell use: 88% of train shell actions are BLOCK or REVIEW | No permission / scope cases: an authorised vs unauthorised version of the *same* call | Few distinct attack wordings in agent form; no adaptive (human red-team) attacks in agent context | No real production traffic; few benign shell or high-impact calls |
| **Fill with** | Benign shell twins (generated); shell renderings of existing calls | Policy-conditioned triples and one-fact pairs (generated) | LLMail and text-pool attacks planted into real contexts (generated); competition data | More TOUCAN shards; production logs later |

## 2. Datasets downloaded and converted

| Dataset | Licence | Category | Unit | Records | Balance (decision) | Labelling method | Use |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **InjecAgent** (+ authors' model outputs) | MIT | Injection, unauthorised calls | step | 10,596 | 5,462 ALLOW / 5,134 BLOCK | Benchmark checker on 62 model setups' outputs; kept only where the first action agrees with the checker | Train (grid split: A×A train, B×B test) |
| **ATBench** | Apache-2.0 | Injection, tool misuse, disclosure, principal misuse | trajectory | 1,000 | 503 / 497 | Generated runs with taxonomy labels, rule + LLM filtering and a full human audit | Train 70% / test 30% (trajectory head) |
| **ATBench steps (PROACT)** | derived from ATBench | as ATBench | step | 2,144 | 2,122 / 22 (rule boundaries + 2 judged runs so far) | Run label given; first unsafe step located by rules, then agreeing LLM judges, with human checks overriding | Follows each run's split |
| **RedCode-Exec** | CC BY 4.0 (attribution) | **Shell / code execution** | step | 1,920 | 1,140 BLOCK / 780 REVIEW | Risky by benchmark design (container checks in the authors' harness); BLOCK vs REVIEW per category is ours. 450 code-quality cases excluded | Train, whole categories held out |
| **TOUCAN** (3 of 131 shards) | Apache-2.0 | Benign (real MCP execution) | step | 6,440 | all ALLOW | Benign by construction; the dataset's own response-quality score ≥ 3.5 | Train, split by server |
| **ToolACE** | Apache-2.0 | Benign (synthetic APIs) | step | 3,000 | all ALLOW | Benign by construction | Train (minor share) |
| **When2Call** | CC BY 4.0 | Benign; call-vs-ask decisions | step | 6,009 | 3,652 ALLOW / 2,357 REVIEW | Multiple-choice design: the correct reply is ALLOW, an unwarranted call is REVIEW | Train, split by tool set |
| **Generated injections** | from TOUCAN, InjecAgent, LLMail | Injection, benign tool reuse | step | 6 (smoke test) | 4 / 2 | By construction; rule checks, judge model, human review gates | Train (diagnostic from held-out seeds) |
| **LLMail-Inject** | MIT | Injection (email) | outcome | not built (1,500 + 665 emails used as seeds) | attack-only | Outcome flags + LLM judge on unique emails | Attack text for generation only: one tool and one target would be a shortcut |
| **ToolSafe / TS-Bench** | none (MIT badge, no licence file); AgentHarm part has a no-training request | Injection, attacker tools, harmful requests | step | 7,182 | 3,770 / 1,781 REVIEW / 1,631 BLOCK | Step-level annotation, 0 / 0.5 / 1 (safe / controversial / unsafe) | **Evaluation only** (Tier 2) |
| **R-Judge** | none | Injection, unintended risk | trajectory | 564 | 266 / 298 | Human annotation | **Evaluation only** |
| **MCPTox** | none (anonymous and official repos) | Tool-description poisoning (MCP) | step | 5,654 | 2,590 / 923 REVIEW / 2,141 BLOCK | Authors' labels on about 30k responses from up to 27 models | **Evaluation only** |
| **b3 (public subset)** | conflict: README says MIT, LICENSE file is research-only and non-commercial | Agent LLM-call attacks | — | — | — | Crowdsourced attacks (Gandalf: Agent Breaker) | **Excluded** |

## 3. Candidates not downloaded

| Dataset | Licence (as surveyed) | Category | Why not (yet) |
| --- | --- | --- | --- |
| AgentDojo | not checked here | Injection in realistic suites | Needs running (an environment, not a dataset). Its runs already arrive through ToolSafe (evaluation only); our own runs would be licensed |
| ASB (Agent Security Bench) | not checked here | Injection, memory poisoning, backdoors | Same: arrives through ToolSafe; the only source for modes 1, 5 and 14 |
| AgentHarm | MIT + safety-use clause + no-training canary | Harmful user requests | No-training request: evaluation only |
| OS-Harm | Apache-2.0, with a request not to train | Computer-use harm | Visual / CUA; no-training request |
| WildJailbreak, Qualifire, jayavibhav | not verified | Text-only jailbreak / injection | No action to decide on; kept in the text pool for planting into contexts and for a separate injection scanner |
| Gandalf (ignore / summarization / mosscap) | MIT | Adaptive human injection text | Text only; good attack-pool material |
| Tensor Trust | BSD-2-Clause | Adaptive human injection text | Text only; attack-pool material |
| ctf-satml24 | MIT | Competition injections | Text only |
| HackAPrompt | MIT (gated) | Competition injections | Gated download; text only |
| IPI Arena attacks | MIT (95 public) | Indirect injection against agents | Very small public release |
| NotInject | MIT | Benign text full of trigger words | Over-defence test set; text only |
| PromptShield, deepset, jackhhao, Salad | Apache-2.0 | Injection / jailbreak text | Text only |
| Gandalf-RCT | research-only, non-commercial | Adaptive attacks | Licence |
| ART benchmark, Ignored-Not-Refused corpus | not released | Agent red teaming | Not available |

## 4. Overlap between sources, and what was done

| Overlap | Effect if ignored | Handling |
| --- | --- | --- |
| R-Judge's 414 injection runs are 297 InjecAgent cases (GPT-4 outputs relabelled by humans) | InjecAgent training would contain R-Judge evaluation cases | Those cases are excluded from InjecAgent (checked on every run) |
| ToolSafe is built from AgentDojo, ASB and AgentHarm runs | The same task could sit in train and test under two names | Task keys hash the normalised instruction, so the same task gets the same key across sources |
| InjecAgent is fully crossed (17 user tasks × 62 attacks) | One connected group: no clean held-out data | Grid split: test has unseen tasks *and* unseen attacks |
| ATBench, AgentDoG and StepGuard come from one generator family | In-family scores look like generalisation | Treated as one source in leave-one-source-out evaluation; the family's generator is not copied |
| Generated records reuse real seeds (TOUCAN contexts, InjecAgent / LLMail attacks) | Synthetic children of test seeds in train | Generated records take their seeds' split; seeds in different splits exclude the record |
| RedCode cases run on TOUCAN's real shell tools | The host tool specs are shared | Intentional: the tool names then appear on benign steps too |
| Generic queries recur across MCPTox servers | Near-duplicates across splits | Query-hash task keys plus grouping by server |

## 5. Balance and coverage

- **Decision balance in licensed training data** (current build):
  - ALLOW dominates through the benign sets.
  - Step-level BLOCK comes mainly from InjecAgent, RedCode, and the PROACT and generated additions.
  - REVIEW comes from When2Call (non-security) and RedCode's weaker categories.
- **Taxonomy coverage.** Of the 19 single-agent security modes, licensed step-level data carries:
  - **through real data:** 16 (cross-domain injection) and 22 (excessive agency) at volume, and RedCode's 18, 19, 20 and 21;
  - **through ATBench and PROACT:** 2, 12, 18, 20, 21 and principal misuse.

  Mode 19 (permissions) has only RedCode's 60 records. Modes 1, 5, 7, 8, 11, 13, 14, 15, 17 and 23 have little or no licensed step data. The build's coverage matrix (`data/training/report.json` → `coverage`) tracks this per cell.
- **Known shortcuts in sources:**
  - InjecAgent: any call to a non-user tool is BLOCK.
  - Final answers are almost always ALLOW.
  - ATBench uses 5 fixed injection strings.
  - Shell actions are almost always BLOCK.

  Each is either measured by the build audit or targeted by generated matched pairs.

## 6. Filling the gaps

| Gap | Public | Synthetic | Red team |
| --- | --- | --- | --- |
| Benign shell use | More TOUCAN shards (shell / terminal MCP servers) | Benign twins of RedCode cases (same command family, harmless target); shell renderings of existing labelled calls (both classes) | — |
| Unauthorised calls (permission / scope) | AgentDojo and ASB runs of our own (licensed) | Policy-conditioned ALLOW / REVIEW / BLOCK triples; one-fact pairs (same call, recipient authorised or not) | Internal exercises against our own agents' permissions |
| Injection variety | Gandalf, Tensor Trust, LLMail as attack text | Planting real attack text into real contexts (the generation pipeline) | Competition data where licensed (IPI Arena); RL red teaming against Jev |
| Adaptive attacks | Competition releases | — | The only real source: human red teams and RL attackers, kept as held-out evaluation |
| Real benign traffic | — | — | Production or shadow logs, once available |

## 7. When synthetic data is safe to use for evaluation

1. **Never as the headline.** Synthetic test data mostly measures how well a model learned the generator. In this pipeline synthetic records never enter test; they form a separate `diagnostic` split, reported apart.
2. **Diagnostic use is acceptable when** it covers a cell with no real test data, is built only from held-out seeds (none in train or validation), and is labelled by construction with an audited rule precision.
3. **Headline results use real data from another source**: held-out real sets (InjecAgent B×B, ATBench test, RedCode held-out categories, held-out benign servers), plus internal transfer checks on the evaluation-only sets.
4. **Over-defence is measured on real benign data**, not on synthetic look-alikes, which overstate how well false positives transfer.
5. **Check that the generator is invisible.** A classifier that can tell real from synthetic records in the same cell means the synthetic set carries artefacts. The realism probe for this is still to build.
