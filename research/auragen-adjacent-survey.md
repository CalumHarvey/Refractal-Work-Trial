# Generation approaches adjacent to AuraGen: survey and usefulness

*Written 21 October 2026. It extends §4.4 of [synthetic-data-review.md](synthetic-data-review.md) and covers **generation methods only**, not released datasets.*

**Method.**
- Read the AuraGen / Safiron paper ([2510.09781](https://arxiv.org/abs/2510.09781)), including its related work.
- Pulled the 35 papers that cite it (Semantic Scholar).
- Read the generation sections of the ones that build training data.
- Added adjacent generators from outside the citation graph.

Numbers are the authors' own.

**What "useful" means here.** A method is useful if it produces step-level ALLOW / REVIEW / BLOCK records on a *planned* action, for the four focus categories: **shell commands, unauthorised tool calls, prompt injection and benign activity**. It must also be a proven, buildable recipe, and it must avoid the project's known failure modes:
- labels a shortcut can predict, such as tool identity;
- BLOCKs whose cause is not visible at decision time;
- no REVIEW signal;
- generator-family overlap with the test set (ATBench).

---

## 1. AuraGen (the reference point)

**Pipeline.**
1. An LLM is given an environment, tools and constraints, and writes a query plus a safe trajectory.
2. An injector LLM takes that trajectory, one of 8 risk categories and one of four operators:
   - **single-step perturbation**: one action becomes harmful;
   - **multi-step corruption**: a contiguous run of actions is replaced;
   - **new-branch diversion**: the trajectory is cut and a harmful ending is appended;
   - **bridged-branch diversion**: middle actions are replaced but the original final action is kept, as a deceptive adversary would.
3. A reward model scores each sample from 1 to 5 on causal consistency, postcondition continuity, rationality, justification sufficiency and risk matching. A linear SVM over the scores decides keep or discard, and beats simple thresholds.

Tools are rebuilt from GPT Store and MCP listings. The generator is Mixtral-8×22B, and about 20k samples were produced. Training mixes of more than 1:4 risky:benign stopped helping. "Calibrated difficulty" amounts to an easy/hard split made with the SFT model.

**Assessment: Medium–High.** It is the simplest *transformational* generator: take a benign trajectory and corrupt it. The four operators give structural variety that the other methods lack, especially bridged-branch diversion.

Three gaps for this project:
- **The injector edits the action, not the cause.** A BLOCK can appear with no poisoned output or injected message in the context. That is exactly what teaches "this tool is bad".
- **Labels are per trajectory**, not per step.
- **No minimal pairs.** The benign source and the corrupted copy are not kept as a contrastive pair.

**Use:** the four operators and the five-criterion filter, inside a frame that fixes these three gaps (StepGen, §2.1).

---

## 2. Generation approaches, grouped by how the data is produced

### 2.1 Authored by an LLM, with tool outputs simulated

| Approach | How it generates | Evidence it works | Fit for this project | Rating |
| --- | --- | --- | --- | --- |
| **StepGen** (StepGuard, [2608.24777](https://arxiv.org/abs/2608.24777)) | **Taxonomy-sampled episode.** A risk source, failure mode and harm type are sampled, along with 8–15 tools from about 9.2k real MCP tool specs. **Planner.** Two calls draft a scenario, then compile it into a JSON plan. Every argument carries a **parameter lineage tag** (user / tool / system), and the plan must have **exactly one unsafe anchor**, or it is replanned (up to 3 tries). **Rollout.** A thought generator and an action generator alternate. Deterministic tools answer by rule and the rest are LLM-simulated. Injection-type risks are planted *in the environment turn* at the anchor, with a marker. **Branching.** The prefix is kept and the suffix re-rolled as **Refuse** and **Aware** (continue safely with filtered arguments), plus an independent **benign tool-reuse** trajectory using the same tools. **QC.** A rule validator checks format, schema, lineage, anchor and marker. An LLM auditor scores 6 axes (0–3); a group is kept at ≥14 with no zero axis, regenerated once at 10–13, and dropped below 10. | Yield: 96% pass the validator and 32% the auditor, so **31% end to end**. Ablations: prefix supervision lifts trajectory accuracy and F1 from 80.4/82.0 to 83.8/83.4; **benign tool reuse lifts TS-Bench-Harm F1 from 69.2 to 75.2**. GLM-5.1 is the generator. | **The closest match to this problem.** The cause is planted in the context (fixing AuraGen's gap). Shared-prefix branches make minimal pairs. Benign tool reuse directly breaks "this tool means BLOCK". **Lineage tags define an unauthorised call** (an argument whose origin is a tool output, not the user). Each step gets a label. *Gaps:* binary only (no REVIEW); no shell; simulated outputs; training labels never audited by humans. | **High: the base frame** |
| **AgentDoG / ATBench planner** ([2601.18491](https://arxiv.org/abs/2601.18491), [2604.02022](https://arxiv.org/abs/2604.02022)) | Sample a risk configuration (8 sources × 14 failure modes × 10 harms) and a safe or unsafe outcome. A planner writes a task plan with a **risk injection point**. An orchestrator drives the query, agent and tool-response generation step by step. ATBench adds a **delayed-trigger** protocol: the risk is planted early and appears several steps later. QC: rule plus LLM filters (about 52% kept); four verifiers vote; humans review disputes. | 100k+ trajectories, but labels are per trajectory. | A sound method, and delayed trigger is the standard way to produce delayed-effect cases (mode 11). **But ATBench is the test set**: copying its generator makes training data in the test set's style, so scores rise without real generalisation. No contrastive branches. | **Medium**, but avoid copying it closely |
| **AgentAlign** ([2505.23020](https://arxiv.org/abs/2505.23020)) | An LLM brainstorms **abstract behaviour chains** (1–5 steps over 42 abstract tool capabilities, guided by 8 harm categories and 64 subcategories). Each chain is instantiated as a concrete request in a simulated environment, and **benign twins** of the same chains are generated. | +35.8 to +79.5 points safety on AgentHarm with utility kept. | Good for **principal-misuse BLOCKs** (the user is the attacker) and their benign twins. Not injection. It produces refusal responses, so guard labels have to be derived. | **Medium** |
| **JANUS** ([2607.19913](https://arxiv.org/abs/2607.19913)) | A multi-agent factory: a Manager directs an Instructor, ToolDesigner, Grader, EnvInjector (risk in tool outputs), Decomposer (spreads one risk across turns), Executor and Reviewer. Tools are fully simulated, with rejection sampling for the target risk pattern. Labels per prefix: **Safe / Unsafe / Potential Unsafe**. | 75k examples. **No ablation of the synthesis itself.** The agent model is an uncensored Qwen. | The role decomposition is a useful engineering pattern, and "Potential Unsafe" is a REVIEW-like label. The method itself is less proven than StepGen. | **Low–Medium** |
| **MATE** ([2609.22724](https://arxiv.org/abs/2609.22724)) | A **knowledge base** of 158 apps from official documentation and policies. Instructions are constrained to documented functions. Trajectories are conditioned on an intended-violation tag and a policy. Augmentation adds **mismatched trajectory/policy pairs** (labelled no violation) and sets of several policies. QC: structure check, then LLM repair, then human review. | **The clearest sim-to-real ablation in this set:** removing grounding *and* repair drops real-device accuracy from 75.9% to 46.9%, and removing either alone also hurts. | Mobile GUI, so the domain is wrong. But it gives the strongest evidence that **grounding generation in real tool documentation** and an LLM repair pass matter. Policy conditioning fits mode 17/19 (confirmation and scope) decisions. | **Medium** (the principle) |

### 2.2 Executed against real or replayable environments

| Approach | How it generates | Evidence | Fit | Rating |
| --- | --- | --- | --- | --- |
| **Safety Sentry** ([2607.13594](https://arxiv.org/abs/2607.13594)) | Nine **self-hosted services** in Docker (Gitea, Rocket.Chat, ownCloud, NocoDB, Zammad, ERPNext, OpenEMR, Vaultwarden, Mailu) with seeded content. An LLM authors tasks from 7 template families; some are routine, others built to create risky decision points (cross-principal approval, grey compliance cases). Each task gets up to 3 **persona memories** tied to concrete arguments or entities: *cautious* (confirm before anything irreversible), *permissive* (routine work pre-cleared) and *adversarial* (memory poisoning). A task agent runs with **real tools and no safety judgement**. Every proposed call becomes a pre-execution snapshot. Two LLM annotators assign **Execute / Ask / Refuse** plus one of 14 triggers; the authors arbitrate. | **92% human agreement** on the fully audited test split. Removing memory examples drops accuracy on memory-conditioned cases from 87.5% to 74.3%. One whole service is held out for out-of-distribution testing. | **The only proven method that produces REVIEW labels systematically.** Memory and context make the same call ALLOW, REVIEW or BLOCK, which yields three-way contrastive sets. Real execution gives realistic benign steps. A task agent with no safety role yields natural benign traffic. *Gaps:* enterprise apps only, with no shell service, though one can be added; injection is limited to memory poisoning. | **High** (REVIEW, benign, unauthorised calls) |
| **SEAD / DART** ([2609.34518](https://arxiv.org/abs/2609.34518)) | Tasks with a **controlled initial state, replayable tools and an executable check** across Filesystem, **Terminal**, PostgreSQL and Web (187 malicious tasks adapted from MT-AgentRisk, plus benign tasks from OpenAgentSafety). The attacker runs **tree search over executed prefixes**, splitting a harmful goal into locally plausible instructions. Node value combines introspection, feedback and executed progress, with UCT search, depth 8 and 25 nodes. **Labelling rule:** the *closure action*, the earliest action that completes the harmful objective (judged by an LLM), is BLOCK; earlier actions are PASS; later actions are dropped. | Executable attack success 48%; the trained defender reduces it to 4%. The defender was trained on Filesystem and Terminal only and generalises to the held-out PostgreSQL and Web domains. | **The only executed, checkable method that covers shell.** It produces state-dependent harm, where a routine-looking command is harmful given earlier changes. The closure rule is a clean way to assign step labels. *Costs:* an abliterated attacker model, real sandboxes and an expensive search. The data is very imbalanced (about 8% BLOCK). | **Medium–High for shell**; Low elsewhere |

### 2.3 Transforming existing labelled data

| Approach | How it generates | Evidence | Fit | Rating |
| --- | --- | --- | --- | --- |
| **PROACT-Agent** ([2609.34415](https://arxiv.org/abs/2609.34415)) | Takes existing trajectory corpora (R-Judge, ToolSafety, ATBench, AgentAlign). **Progressive unrolling:** each prefix becomes a labelled state, and a parser model finds the first unsafe boundary. **Rationale fill-in** where the source lacks one. **Committee adjudication:** 4 models vote, and an arbitrator settles any disagreement. **Monotonic causal consistency:** once a prefix is unsafe, later prefixes are dropped, which fixes the "safety drift" of contradictory step labels. | 155,780 states. 91.5% unsafe-class F1 under **complete source holdout**. No human study of where the boundaries were placed. | Cheap, because it reuses trajectories the project already has: it is the established way to turn ATBench and R-Judge trajectory labels into step labels. *Adjust:* PROACT puts the boundary after an observation, but Jev decides *before the call*, so anchor the boundary on the action. | **High** (cheap step-label generation) |
| **StepSafe** ([2610.20960](https://arxiv.org/abs/2610.20960)) | Three landmarks per unsafe trajectory: **signal** (the risk is first observable), **boundary** (the violating step) and **last preventable step**. Before signal: Continue. Signal to boundary: **Ask**. Boundary to last preventable step: Stop. Safe trajectories are Continue throughout. **Paired benign variants** share the goal and prefix but differ in *one permission, recipient, provenance fact or action*. **Red teaming driven by errors:** the guard's training errors are grouped by category, and persona agents write new tasks for the gaps. | Removing red teaming lowers Youden's J from 53.0 to 51.7. The landmarks come from one LLM annotator. | The landmark rule is a **principled way to place REVIEW**. **One-fact paired variants are the right minimal pairs for unauthorised calls**: same call, recipient authorised or not. Red teaming driven by errors is a good later stage. | **Medium–High** (labelling rule and pair design) |
| **ToolRosetta** ([2610.24055](https://arxiv.org/abs/2610.24055)) | Programmatically **re-renders each labelled JSON tool call as a shell command or a Python call** (and optionally removes the rationale). **Round-trip parsing** checks that the request, history, label and effect are unchanged. | Shell rendering raised false positives in 4 of 5 specialised guards by 21–47 points, while StepGuard and frontier guards stayed stable. | **The cheapest shell generator**: every existing label carries over by construction, and it removes the "shell means BLOCK" shortcut. *Limit:* it changes surface form only, so it does not create native shell risks such as destructive deletes, `curl \| sh` or exfiltration via `scp`. | **High for shell surface form** |
| **Paired counterfactual edits** (Shortcut Sensitivity, [2610.22243](https://arxiv.org/abs/2610.22243)) | Small controlled edits with labels fixed: rename tools, use opaque aliases, reword marker strings, format-only placebos. | Rewording a marker changed blocking by 8.3 points, and aliases by 11.5, beyond the placebo effect. Exact-tool lookup F1 fell from 0.90 to 0.50 under domain holdout. In LinuxArena, *command length* predicts the label. | Cheap augmentation against shortcuts and a matching invariance test. Directly relevant to the tool-identity shortcut and future shell data. | **Medium** |

### 2.4 Adversarial and feedback loops

| Approach | How it generates | Fit | Rating |
| --- | --- | --- | --- |
| **HASTE** ([2610.02920](https://arxiv.org/abs/2610.02920)) | Co-evolves safety specifications and attack cases from sparse threat reports. | Useful later for new attack classes; not a first-stage generator. | **Low (now)** |
| **DART search** (§2.2) and **StepSafe red teaming** (§2.3) | Search or persona agents aimed at where the target or guard currently fails. | The established way to get hard positives once a base set exists. | **Medium (stage 2)** |

### 2.5 AuraGen's own related work

Its related-work section covers LLM content guards (Llama Guard, WildGuard, ShieldGemma, Granite Guardian), agent-guard methods (GuardAgent, AGrail, ShieldAgent, AgentSpec) and general synthetic text data (Magpie, MetaSynth, DataGen). **None of these generate agent trajectories**, so they are low value here. The established hybrid baseline that it does not cite, **InjecAgent / ToolEmu** (LLM-written cases, real agents, emulated tools), remains the project's default recipe and fits within StepGen's frame.

---

## 3. Coverage by focus category

| Category | Best approach | Runner-up | Note |
| --- | --- | --- | --- |
| **Prompt injection** | StepGen (cause planted at the anchor, Refuse/Aware branches) | AuraGen operators as anchor variants | Require the injected content to be visible in `input` |
| **Unauthorised tool calls** | StepGen lineage tags + StepSafe one-fact pairs | Safety Sentry cross-principal templates | The label depends on argument origin and authorisation, not on the tool |
| **Shell commands** | ToolRosetta re-rendering (cheap) + DART/SEAD-style executed Terminal sandbox (native risks) | Safety Sentry pipeline with a shell container added | No AuraGen-line method generates native shell risks without execution |
| **Benign activity** | StepGen benign tool reuse + Safety Sentry task agent on real services | AgentAlign benign twins | Benign data must use the *same tools* as the BLOCKs |
| **REVIEW** | Safety Sentry persona memory + StepSafe landmarks | JANUS "Potential Unsafe" | Only these produce three-way labels |

---

## 4. Recommended composite (all parts already demonstrated)

1. **Base frame: StepGen.** Plan with lineage tags and exactly one anchor, plant the cause in the environment turn, branch shared prefixes into BLOCK / safe variants, and add a benign trajectory reusing the same tools. Draw tools from real MCP specs (the project already has TOUCAN servers), as MATE's grounding ablation supports.
2. **Use AuraGen's four operators as anchor types** inside that frame, for variety (especially bridged-branch diversion). Filter with AuraGen's five criteria or StepGen's six-axis auditor, plus a rule validator. Budget for roughly 30% end-to-end yield.
3. **Add REVIEW with Safety Sentry-style context conditioning** (cautious / permissive / adversarial memory or policy). Place REVIEW with StepSafe's landmarks (signal to boundary).
4. **Shell, in two parts:**
   - ToolRosetta re-rendering of all existing labelled calls into shell and Python;
   - a small executed Terminal sandbox with DART-style closure-action labelling for native shell risks.

   Add command length to the shortcut audit.
5. **Step-label existing trajectories with PROACT** (unroll, committee adjudication, monotonic consistency), anchored on the action rather than the observation.
6. **Later:** red teaming driven by errors (StepSafe), aimed at where the trained model fails.

**Avoid:** copying the ATBench/AgentDoG planner closely (it overlaps the test set's style), and fully simulated multi-agent factories without data ablations (JANUS).

**Caveat common to all of them:** apart from Safety Sentry's test split and MATE's review stage, none of these methods report a human audit of their *training* labels. The project's planned audit of about 200 records per rule stays necessary.
