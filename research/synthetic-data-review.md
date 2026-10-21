# Data generation and synthetic data for agent security: state of the art

*Literature and industry review, October 2026. It is written for the Jev data pipeline (ALLOW / REVIEW / BLOCK on planned agent actions) but covers LLM synthetic data in general.*

**How to read this.** Section 1 defines the kinds of data. Sections 2–5 cover the literature: general LLM synthetic data, tool and agent trajectories, security-specific generation, and evaluation validity. Section 6 covers what industry is doing: frontier labs, platforms, vendors, data sources and standards. Section 7 lists where the field agrees. Section 8 turns that into recommendations for this project. Section 9 is the reading list.

**Caveat.** Many 2026 items are unreviewed preprints. Headline numbers are the authors' own, mostly taken from abstracts and summaries; check them against the papers before relying on them.

---

## 1. Kinds of data

Papers mix up terms. This review uses five kinds, which differ in who produced the agent's behaviour and who produced the label:

| Kind | Agent behaviour | Label | Examples |
| --- | --- | --- | --- |
| **Collected (human)** | Real users or attackers, in the wild or in a competition | Humans or outcome checks | Tensor Trust, HackAPrompt, LLMail-Inject |
| **Benchmark-run** | A real model acting in a built environment | Environment checker | AgentDojo, InjecAgent, ASB, MCPTox, AgentDyn |
| **Authored-synthetic** | An LLM writes the whole example, actions included | The specification it was written to, then verification | AgentAlign, AuraGen, StepGen, WildJailbreak, Constitutional Classifiers |
| **Hybrid** | LLM-authored scenarios; real models act, often with LLM-simulated tools | Checker or judge on what the agent actually did | InjecAgent (GPT-4-written cases plus real agent outputs), ToolEmu, APIGen-MT |
| **Adversarially generated** | An attacker model (often trained with RL) writes attacks against a target | Attack success against the target | Rainbow Teaming, RL-Hammer, CoER, GPT-Red |

The current sources map onto these kinds as follows:
- **Benchmark-run:** ToolSafe, MCPTox.
- **Hybrid:** InjecAgent, and R-Judge (a curated, human-relabelled InjecAgent subset).
- **Largely authored-synthetic:** ATBench.
- **Collected:** LLMail-Inject.

---

## 2. Synthetic data for LLMs in general

### 2.1 Generation
- **Self-generated instructions.** Self-Instruct and Evol-Instruct grow instruction sets from seed examples. Evol-Instruct also rewrites instructions to make them deeper and broader. **Magpie** (ICLR 2025) gives an aligned model only the template up to the user turn, so the model writes the user query itself. Its 4M generated pairs, filtered to 300K, rivalled Llama-3-8B-Instruct on some tasks. ([Magpie](https://arxiv.org/abs/2406.08464))
- **Diversity by conditioning.** **Persona Hub** builds about 1B web-derived personas, deduplicated with MinHash and embeddings, as "distributed carriers of world knowledge". Conditioning on a persona spreads generations across viewpoints; the paper's uses include synthetic tool functions. ([Persona Hub](https://arxiv.org/abs/2406.20094))
- **Seeded by documents ("generative teaching").** **AgentInstruct** / Orca-3 uses multi-agent flows that turn raw documents and code into 25M prompt–response pairs, tool use included. It reports large gains over Mistral-7B-Instruct. ([AgentInstruct](https://arxiv.org/abs/2407.03502))
- **Industrial pipelines.** Nemotron-4 340B used a generator plus a 5-attribute reward model for filtering; over 98% of its alignment data was synthetic (the reports word the scope differently). ([NVIDIA](https://blogs.nvidia.com/blog/nemotron-4-synthetic-data-generation-llm-training))
- **Generation from rules.** Constitutional AI, and **Constitutional Classifiers** (Anthropic, 2025): an LLM given a natural-language "constitution" of allowed and forbidden content generates the classifier's training data. The classifiers survived more than 3,000 hours of human red teaming, at a 0.38% higher refusal rate. ([Anthropic](https://www.anthropic.com/research/constitutional-classifiers))
- **Quality-diversity search.** **Rainbow Teaming** treats adversarial prompt generation as MAP-Elites: a grid of feature cells (risk category × attack style), each filled with its best prompt. Fine-tuning on the archive improved safety without hurting helpfulness. **RainbowPlus** keeps several elites per cell. ([Rainbow Teaming](https://arxiv.org/abs/2402.16822), [RainbowPlus](https://arxiv.org/abs/2504.15047))

### 2.2 Curation and verification
- **The common frame is generation → curation → evaluation** ([Long et al., ACL Findings 2024](https://aclanthology.org/2024.findings-acl.658/)). A 2025 survey finds agentic generation pipelines raise quality and diversity but cost much more compute ([survey](https://dl.acm.org/doi/10.1007/978-3-031-93418-6_9)).
- **Practitioners' consensus** ([DeepMind/Stanford, COLM 2024](https://arxiv.org/abs/2404.07503)): generating is easy; keeping data factual, faithful to the real distribution and unbiased is the hard part.
- **Verification stacks** (detailed in §3) combine format checks, execution checks and semantic checks by an LLM judge or a committee of judges.
- **LLM judges are biased** towards position, length, their own outputs and fabricated citations. Agreement with humans must be measured with chance-corrected statistics and order randomisation, not assumed ([survey](https://arxiv.org/abs/2411.15594), [2512.16041](https://arxiv.org/abs/2512.16041), [2606.19544](https://arxiv.org/abs/2606.19544)).
- **LLM-produced labels are noisy, and the noise is unlike human noise.** Practical mitigations:
  - sample the judge several times and keep only examples it labels the same way each time ([2406.17633](https://arxiv.org/abs/2406.17633));
  - use calibration methods built for LLM label noise ([SiDyP, KDD 2025](https://arxiv.org/abs/2505.19675)).

  This matters for a *calibrated* decision model.

### 2.3 Known limits
- **Subjectivity.** Synthetic data comes close to real data on objective classification tasks, but the gap widens as the task gets more subjective, partly because generated data is less diverse ([Li et al., EMNLP 2023](https://arxiv.org/abs/2310.07849)). Borderline ALLOW/REVIEW calls are subjective in exactly this sense.
- **Diversity is hard to measure and easy to lose.** There is no standard metric; proposals include DCScore, the Task2Vec coefficient and LLM clustering ([2410.15226](https://arxiv.org/abs/2410.15226), [MetaSynth](https://arxiv.org/abs/2504.12563)).
- **Model collapse.** Training repeatedly on a model's own outputs degrades it when synthetic data *replaces* real data. Accumulating real and synthetic data keeps error bounded ([Gerstgrasser et al. 2024](https://arxiv.org/abs/2404.01413)), though others argue accumulation only delays collapse. A 2025 position paper argues most collapse setups are unrealistic ([2503.03150](https://arxiv.org/abs/2503.03150)). For a classifier trained once on mixed data, the practical risk is homogenisation, not collapse.
- **Shortcuts and artefacts.** Older NLP work established this: hypothesis-only baselines in NLI, shortcut learning, and minimal-pair fixes such as contrast sets and counterfactually augmented data. Synthetic generators make these artefacts *more* likely, because one generator imposes one style.

---

## 3. Tool-use and agent trajectory generation

| Approach | What it does | Representative work |
| --- | --- | --- |
| **API / tool synthesis** | Invent or collect thousands of APIs, then generate calls and dialogues | ToolLLM/ToolBench (16k real APIs); **ToolACE** (26.5k self-evolved APIs, dual rule- and model-based verification, the target model's loss used to set difficulty; ICLR 2025) ([ToolACE](https://arxiv.org/abs/2409.00920)) |
| **Staged verification** | Each example passes format, then execution, then semantic checks | APIGen / xLAM |
| **Blueprint, then trajectory** | First a verified task plan with ground-truth actions, then a simulated agent–human conversation that follows it | **APIGen-MT** (NeurIPS 2025): xLAM-2 models beat GPT-4o and Claude 3.5 on τ-bench and BFCL ([APIGen-MT](https://arxiv.org/abs/2504.03601)) |
| **Real execution at scale** | Run teacher agents against real tool servers | **TOUCAN** (ICLR 2026): 1.5M trajectories from about 500 real MCP servers, 5 query generators, 3 teacher models, rule- and model-based checks ([TOUCAN](https://arxiv.org/abs/2510.01179)) |
| **Backward construction** | Let the agent act first, then write the instruction that matches what it did | **Learn-by-Interact** (ICLR 2025): up to +19.5% from training ([LbI](https://arxiv.org/abs/2501.10893)); OS-Genesis (GUI) |
| **LLM-simulated tools** | An LLM plays the tools, so any toolkit can be tried | **ToolEmu** (ICLR 2024): 68.8% of failures it found were real ([ToolEmu](https://arxiv.org/abs/2309.15817)) |
| **Executable synthetic environments** | Generate code-level environments (tools plus databases) that can be checked programmatically | **EnvScaler**, **ScaleEnv** (ICML 2026, "environment scaling curve"), **EnvFactory**, **Agent-World**, SynthTools ([EnvFactory](https://arxiv.org/abs/2605.18703), [ScaleEnv](https://arxiv.org/abs/2602.06820), [EnvScaler](https://arxiv.org/abs/2601.05808)) |
| **Simulated users** | An LLM plays the user; τ²-bench gives both user and agent tools in a shared environment | **τ²-bench** (ICML 2026 oral) ([τ²](https://arxiv.org/abs/2506.07982)) |

**Where the field is converging (2026).** Live production APIs are costly and unstable. LLM-simulated tools hallucinate. *Executable, programmatically verifiable synthetic environments* are the scalable middle ground, and training on more diverse environments improves results on unseen ones. The labels to trust come from checks on the environment's state, not from the generator's word.

---

## 4. Security-specific data generation

### 4.1 Collected attacks: realism and adaptivity
- **Competition data** (Tensor Trust, HackAPrompt, **LLMail-Inject**) is the only source of *adaptive human* attacks. LLMail-Inject had 839 participants, 461,640 submissions and 208,095 unique prompts over two phases.
- **Defences that look strong elsewhere do worse on it.** Meta-SecAlign still shows 32% attack success on LLMail-Inject ([LLMail-Inject](https://arxiv.org/abs/2506.09956)).
- **Its two phases support a time-based split** (train on phase 1, test on phase 2), which is closer to deployment than a random split ([2609.30657](https://arxiv.org/abs/2609.30657)).

### 4.2 Benchmark-run data, and its known flaws
- **The benchmarks.** AgentDojo, InjecAgent, ASB and MCPTox are standard. MCP-SafetyBench and MCPSecBench add MCP-specific attack taxonomies with 20 and 17 types ([MCP-SafetyBench](https://arxiv.org/abs/2512.15163), [MCPSecBench](https://arxiv.org/abs/2508.13220)).
- **"Firewalls or stronger benchmarks?"** (NeurIPS 2025): a simple firewall at the tool interface reaches near-zero attack success on AgentDojo, ASB, InjecAgent and τ-bench. The authors trace this to benchmark flaws: broken success metrics, implementation bugs and, above all, weak attacks. They propose fixes ([2510.05244](https://arxiv.org/abs/2510.05244)).
- **AgentDyn** (2026): AgentDojo-style tasks can be planned entirely from the user query. It adds open-ended tasks that need dynamic planning, *helpful third-party instructions*, 60 tasks and 560 injections. Almost every defence tested was either insecure or blocked too much ([AgentDyn](https://arxiv.org/abs/2602.03117)).
- **"Ignored, Not Refused"** (2026), an audit of 33k trajectories:
  - 76–80% of failed attacks were *ignored*, not refused;
  - changing only the system prompt moved InjecAgent attack success from 0.2% to 43%;
  - in 21.7% of AgentDojo runs the agent stayed safe but failed the user's task.

  Binary "attack succeeded" labels hide all of this ([2610.23254](https://arxiv.org/abs/2610.23254)).
- **The Agentic Benchmark Checklist** (NeurIPS 2025): flaws in task setup and rewards skew agent benchmarks by up to 100% relative ([ABC](https://arxiv.org/abs/2507.02825)).

### 4.3 Synthetic training data for injection defences and guard models
- **StruQ / SecAlign** (Berkeley/Meta). Take ordinary instruction-tuning data, inject a competing instruction into the data part, and train the model to prefer the response to the real instruction, using DPO for SecAlign. This is synthesis by *transforming* existing data, which is cheap and keeps utility. Hand-crafted attacks drop to near 0% success, but architecture-aware attacks break these fine-tuned defences ([SecAlign](https://arxiv.org/abs/2410.05451), [2507.07417](https://arxiv.org/abs/2507.07417)).
- **Instruction Hierarchy** (OpenAI, 2024) uses two kinds of training data:
  - *context synthesis* for aligned instructions: split a request across privilege levels, and the answer must be unchanged;
  - *context ignorance* for misaligned ones: the answer must match the answer without the lower-privilege text.

  This is a principled way to write labels by construction ([2404.13208](https://arxiv.org/abs/2404.13208)).
- **TaskTracker** (Microsoft, SaTML 2025): a synthesis procedure for arbitrarily diverse datasets (more than 500K examples). It detects "task drift" from the change in activations, with near-perfect AUC out of distribution ([TaskTracker](https://arxiv.org/abs/2406.00799)).
- **PromptShield** (CODASPY 2025): mixes conversational data with application-structured data and reports at a very low false-positive rate (0.1%), where PromptGuard catches only 9.4% of attacks ([PromptShield](https://arxiv.org/abs/2501.15145)).
- **InjecGuard / NotInject:** guards over-react to *trigger words* such as "ignore". NotInject is 339 benign samples full of trigger words; no open guard scored above 60% on it. MOF training reduces the bias ([InjecGuard](https://arxiv.org/abs/2410.22770)).
- **WildTeaming / WildJailbreak** (NeurIPS 2024): mines in-the-wild jailbreak tactics, composes them into 262K synthetic examples, and adds **contrastive benign** look-alikes against over-refusal ([WildTeaming](https://arxiv.org/abs/2406.18510)).
- **ShieldGemma:** a synthetic pipeline built for adversarial difficulty, diversity and counterfactual fairness expansion ([2407.21772](https://arxiv.org/abs/2407.21772)).
- **Granite Guardian:** human plus synthetic data, including function-calling hallucination risks.
- **gpt-oss-safeguard:** a policy-conditioned classifier that reads a written policy at inference time, so the policy can change without retraining.
- **LlamaFirewall:**
  - PromptGuard 2, an 86M DeBERTa detector;
  - AlignmentCheck, a few-shot chain-of-thought *auditor* that compares the agent's actions with the user's goal ([LlamaFirewall](https://arxiv.org/abs/2505.03574)).

### 4.4 Synthetic agent-safety trajectories: the closest work to Jev
- **AgentAlign** (2025): an LLM brainstorms *abstract behaviour chains* (1–5 steps over 42 abstract tool capabilities), guided by a harm taxonomy of 8 categories and 64 subcategories. The chains are instantiated as executable instructions in simulated environments, and **benign versions of the same chains** keep the model helpful. Safety on AgentHarm rose from 35.8% to 79.5% with little loss of helpfulness ([AgentAlign](https://arxiv.org/abs/2505.23020)).
- **AuraGen + Safiron** (ICLR 2026): synthesise *benign* trajectories, **inject risks labelled by category at calibrated difficulty**, and filter with a reward model. Safiron is a *pre-execution* guard: it outputs harmless/risky, a risk category and an explanation, trained with SFT then GRPO, plus an adapter that normalises different agents' input formats. It ships with Pre-Exec Bench ([2510.09781](https://arxiv.org/abs/2510.09781)). Structurally this is Jev's problem.
- **StepGuard / StepGen** (2026): generates **pairs of trajectories that share a context and diverge at the risky step**, one safe and one unsafe action, which are minimal pairs at the decision point. Balance-GRPO evens out learning between the safe and unsafe classes. Attack success on AgentDojo and AgentDyn fell 77.3%, with utility down 2.8 points ([2608.24777](https://arxiv.org/abs/2608.24777)).
- **ATBench** (2026): 1,000 trajectories built from heterogeneous tool pools with a *delayed-trigger* protocol (the risk appears several steps later), rule- and LLM-based filtering, and a **full human audit** ([2604.02022](https://arxiv.org/abs/2604.02022)).
- **ToolSafe / TS-Guard** (2026): a step-level guard trained and evaluated on TS-Bench ([2601.10156](https://arxiv.org/abs/2601.10156)).
- **TraceSafe-Bench** (2026): *general frontier LLMs consistently beat specialised safety guards* at analysing multi-step tool-calling traces ([2604.07223](https://arxiv.org/abs/2604.07223)).
- **DreamGuard** (2026): a runtime guard with a risk-aware world model, calibrated on held-out trajectory splits ([2608.05695](https://arxiv.org/abs/2608.05695)).

**The shared recipe:** taxonomy → benign base trajectory → injected or branched risk at a known step → automatic filtering (reward model or judge) → human audit → a step-level label with category and rationale.

### 4.5 Adversarially generated attacks
- **Automated red teaming:** LM-generated red teaming (Perez et al. 2022), then quality-diversity search (Rainbow Teaming).
- **RL attackers:**
  - **RL-Hammer** (Meta) trains an attacker from scratch with GRPO against black-box targets: 98% attack success on GPT-4o, and 72% on GPT-5 with Instruction Hierarchy ([code](https://github.com/facebookresearch/rl-injector));
  - **PISmith** adds fixes for sparse rewards ([2603.13026](https://arxiv.org/abs/2603.13026));
  - **AutoInject** generates suffixes for AgentDojo ([2602.05746](https://arxiv.org/abs/2602.05746)).
- **Co-evolution of attacker and defender** (2026):
  - **CoER/CoRL** frames the problem as a Markov game with pools of past opponents. The defender is fine-tuned only on demonstrations verified safe *and* task-completing. Adaptive attack success fell from 41.3% to 0.2% ([2609.07529](https://arxiv.org/abs/2609.07529));
  - **AdvSim2Real** co-evolves the curriculum, the attacker and a web agent in a web world model ([2610.08773](https://arxiv.org/abs/2610.08773));
  - **OpenAI GPT-Red** runs self-play RL red teaming in connector environments. It found fake tool messages, fake system warnings, multi-hop chains and *self-replicating* injections, which now feed back into training ([OpenAI](https://alignment.openai.com/misalignment-reports/self-replicating-prompt-injections-exist/)).
- **Evaluation consequence.** **"The Attacker Moves Second"** (OpenAI, Anthropic, Google DeepMind and academic co-authors, 2025) bypassed 12 published defences with adaptive attacks, mostly above 90% success, against defences that had reported near zero. RL and search beat gradient methods ([2510.09023](https://arxiv.org/abs/2510.09023)).

### 4.6 Defences by design (context for Jev)
- **CaMeL** (Google DeepMind) separates control flow from data flow and attaches capability metadata to values, so injected data cannot change the program flow. It is provably secure on 77% of AgentDojo tasks, against 84% task completion undefended ([2503.18813](https://arxiv.org/abs/2503.18813)).
- **Meta's "Agents Rule of Two":** within a session, an agent should have at most two of: untrusted input, access to sensitive data, and external side effects.

A learned decision model like Jev is a *complement* to these, not a replacement: it is the human-in-the-loop-style check for when all three are needed.

---

## 5. Evaluation validity: the part the field gets wrong most often

1. **Random splits overstate generalisation.**
   - **"When Benchmarks Lie"** (2026): across 18 datasets, standard cross-validation inflates AUC by 8.0–16.5 points compared with **leave-one-dataset-out**. Per-dataset gaps range from 1 to 25 points.
   - A probe identifies the *source dataset* with **96.6%** accuracy, and 28–44% of top SAE features are dataset shortcuts.
   - Standard domain-generalisation fixes did not close the gap ([2602.14161](https://arxiv.org/abs/2602.14161)).
2. **Curated hard negatives don't transfer.** **PIDS-Bench** (2026): a detector with held-out F1 above 0.98 still misclassifies about a third of *externally sourced* benign security-adjacent text. Hard-negative augmentation removes over-defence on curated stress sets but **not on external ones**, and the gap doesn't shrink as the augmentation pool grows. The authors call this *provenance-sensitive over-defence* ([2609.15017](https://arxiv.org/abs/2609.15017)).
3. **Static attacks overstate robustness.** Adaptive attacks (§4.5) are needed before claiming security.
4. **Attack success hides behaviour.** Report ignored, refused and complied separately, together with task completion ("Ignored, Not Refused").
5. **Benchmark bugs and weak attacks** (Firewalls paper, ABC checklist).
6. **LLM judges and simulators need their own validation:** ToolEmu's 68.8% valid-failure rate, the τ²-bench simulator's error rates, and judge-bias studies.
7. **Synthetic-on-synthetic evaluation measures how well the model learned the generator.** Several 2026 papers explicitly downgrade results obtained this way.

---

## 6. Industry practice

*Sources here are company posts, product documentation, model cards and trade press. Most are not peer-reviewed. Deal values and dates come from press reports and acquirers' filings as reported, and should be checked before citing.*

### 6.1 Frontier labs: hardening models with generated attacks
All three major labs describe the same loop: **generate attacks automatically (increasingly with RL-trained attackers) → train the agent model against them → add classifiers and confirmations around it → repeat continuously.**

- **OpenAI.**
  - *ChatGPT Atlas* (December 2025): an RL-trained LLM attacker searches for injections that play out over long, multi-step browser workflows. Each new class of successful attack is used to adversarially train updated agent models, and the attack traces also improve monitoring and system-level defences. OpenAI says this has to be continuous, not a one-time fix ([OpenAI](https://openai.com/index/hardening-atlas-against-prompt-injection)).
  - *GPT-Red* is its self-play red-teaming framework (§4.5).
  - **Promptfoo** (open-source red-teaming tool, reportedly used by over 25% of the Fortune 500) was acquired in March 2026 for OpenAI's Frontier agent platform and stays open source ([SecurityBoulevard](https://securityboulevard.com/2026/03/openai-acquires-security-startup-promptfoo-to-fortify-ai-agents)).
- **Anthropic** (browser use, November 2025):
  - **RL training on simulated web pages carrying injections**, rewarding Claude for spotting and refusing them even when they sound authoritative;
  - **classifiers over all untrusted content** in the context window, looking for hidden text, manipulated images and deceptive UI;
  - site permissions, confirmation before risky actions, and blocked high-risk site categories.

  Reported attack success against the mitigations fell from 23.6% to 11.2% (the second figure is from secondary coverage). Anthropic states prompt injection is "far from solved" ([Anthropic](https://www.anthropic.com/research/prompt-injection-defenses)).
- **Google** (Gemini and Workspace): defence in depth. The layers:
  - **adversarial training on generated attack data** ("substantially improved Gemini 2.5's resistance");
  - proprietary injection classifiers;
  - "security thought reinforcement", markdown sanitisation and URL redaction;
  - a user-confirmation framework and user notifications;
  - automated red teaming, human red teams, live hacking events and an **AI Vulnerability Reward Program** (up to $30k; indirect injection that causes rogue actions or exfiltration is in scope, plain jailbreaks are not).

  Sources: [Google](https://blog.google/security/mitigating-prompt-injection-attacks/), [Workspace](https://blog.google/security/google-workspaces-continuous-approach-to-mitigating-indirect-prompt-injections/), [AI VRP](https://www.theregister.com/2025/10/07/google_ai_bug_bounty/).
- **Meta:** LlamaFirewall (PromptGuard 2 classifier, AlignmentCheck auditor, CodeShield), the **Agents Rule of Two** design guideline, RL-Hammer, and SecAlign.

### 6.2 Platforms: guard APIs and runtime hooks
- **Microsoft.**
  - **Prompt Shields** in Azure AI Content Safety detect direct and *indirect* attacks (documents, plugin results, web pages, email), alongside **Spotlighting**.
  - **Copilot Studio external threat detection:** before each tool call, the agent sends the prompt, recent chat history, tool name and inputs to a registered endpoint. That endpoint must answer **approve or block within one second**; on timeout a configured default applies. There is no partial or "modify" decision, and **tool outputs are not scanned**. Partners include Microsoft Defender, Zenity, CrowdStrike (via Pangea's AIDR) and Palo Alto Prisma AIRS ([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/external-security-webhooks-interface-developers), [Zenity](https://docs.zenity.io/integration/cps-inline-webhook.html), [CrowdStrike](https://aidr-docs.crowdstrike.com/docs/aidr/collectors/agentic/copilot-studio)).
  - **PyRIT** is its open-source red-teaming framework (attacker model, target, scorer), with multi-turn, PAIR and cross-prompt injection (XPIA) orchestrators. A June 2026 Cloud Security Alliance evaluation found gaps in agent state tracking ([PyRIT](https://arxiv.org/abs/2410.02828), [CSA](https://cloudsecurityalliance.org/artifacts/evaluating-pyrit-for-agentic-ai-red-teaming)).
- **AWS.** Bedrock Guardrails prompt-attack checks (JAILBREAK / PROMPT_INJECTION / PROMPT_LEAKAGE, each with a confidence threshold), callable from **AgentCore Policy**. Tool calls are authorised deterministically by **Cedar** policies, so an unauthorised call is denied even if an injection influenced the agent ([AWS docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)).
- **Google Cloud.** **Model Armor** sanitises MCP `tools/call` requests and responses, `prompts/get` and tool errors. `tools/list` (where tool-description poisoning lives) passes through **unsanitised** ([Model Armor](https://docs.cloud.google.com/model-armor/model-armor-mcp-google-cloud-integration)).
- **NVIDIA.**
  - NeMo Guardrails (runtime), NeMo Auditor (pre-deployment scanning, built around **garak**) and **Safe Synthesizer / Data Designer** (synthetic training data). Its earlier "Safety for Agentic AI" blueprint (garak scan → safety post-training → guardrails) was deprecated in April 2026 ([NVIDIA](https://build.nvidia.com/nvidia/safety-for-agentic-ai/modelcard)).
  - NVIDIA acquired synthetic-data company **Gretel** in March 2025 for a reported nine figures ([TechCrunch](https://techcrunch.com/2025/03/19/nvidia-reportedly-acquires-synthetic-data-startup-gretel)).
- **IBM Granite Guardian** and **OpenAI gpt-oss-safeguard** (§4.3): open guard models, one trained on human plus synthetic data, the other policy-conditioned.
- **Cisco AI Defense** (February 2026 expansion): runtime inspection of agent actions and MCP traffic (unauthorised tool use, memory poisoning), an AI bill of materials, an MCP catalogue, and multi-turn algorithmic red teaming ([Cisco](https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2026/m02/cisco-redefines-security-for-the-agentic-era.html)).

### 6.3 Specialist vendors and consolidation
The independent AI-security vendors were mostly bought in 2025–26:

| Company | Acquirer | Reported |
| --- | --- | --- |
| Lakera (Guard, Red, Gandalf) | Check Point | ~$300M, September 2025 |
| Protect AI (LLM Guard, scanners) | Palo Alto Networks | $634.5M, closed July 2025 |
| Prompt Security | SentinelOne | August 2025 |
| CalypsoAI | F5 | $180M, September 2025 |
| Invariant Labs (Guardrails, MCP-scan) | Snyk | June 2025 |
| Promptfoo | OpenAI | March 2026 |
| Gretel (synthetic data) | NVIDIA | March 2025 |

Sources: [SecurityWeek](https://www.securityweek.com/check-point-to-acquire-ai-security-firm-lakera/), [SiliconANGLE](https://siliconangle.com/2025/09/11/f5-acquires-ai-security-provider-calypsoai-180m/), [Latio](https://pulse.latio.tech/p/unpacking-the-2025-ai-security-acquisitions), [tech.eu](https://tech.eu/2025/06/24/snyk-acquires-ai-security-pioneer-invariant-labs-for-a-new-era-in-ai-safeguards/).

What the acquired products show about data practice:
- **Lakera** trained its defences on its crowdsourced game, **Gandalf**: over 80M attack patterns reported. With the UK AISI it released **b3**, the Backbone Breaker Benchmark: 10 "threat snapshots" of individual agent LLM calls, paired with **19,433 crowdsourced attacks** from *Gandalf: Agent Breaker*. The attacks cover system-prompt exfiltration, phishing-link insertion, malicious code, denial of service and unauthorised tool calls. Across 31 LLMs, better reasoning improved security but model size did not ([b3](https://www.nasdaq.com/press-release/lakera-launches-open-source-security-benchmark-llm-backends-ai-agents-2025-10-28)).
- **Protect AI's** open DeBERTa injection classifier (v2) is the typical open-source recipe: **aggregate public datasets** (the card lists their licences), plus injections written from papers, competitions and community feedback. Its limitations are stated: English only, no jailbreak detection, false positives on system prompts ([model card](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2)).
- **Invariant** named "tool poisoning" and "MCP rug pulls". MCP-scan checks MCP configurations and *pins tool hashes* to catch silent description changes ([Snyk](https://labs.snyk.io/resources/snyk-labs-invariant-labs)).

### 6.4 Where industry attack data comes from
| Source | Examples | What it gives |
| --- | --- | --- |
| **Crowdsourced games** | Gandalf (80M+ attacks), Gandalf: Agent Breaker → b3 | Huge volumes of human adversarial creativity, gamified and cheap |
| **Sponsored competitions** | Gray Swan × UK AISI agent red-teaming (March–April 2025: ~1.8M attempts, 62k successful breaks, 22 models); **Indirect Prompt Injection Arena** 2026 (with UK AISI, US CAISI and frontier labs: 13 models, 464 red teamers, 272k+ attacks; *no model immune*); HackAPrompt; LLMail-Inject | Adaptive human attacks against real agents, judged at scale. The data is shared with AISI/CAISI; an attack dataset and the **ART benchmark** are released ([Gray Swan](https://www.grayswan.ai/blog/uk-aisi-x-gray-swan-agent-red-teaming-challenge-results-snapshot), [paper](https://arxiv.org/abs/2603.15714), [CAISI](https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)) |
| **Bug bounties** | Google AI VRP and other labs' programmes | Rare, high-value real exploits |
| **Automated, increasingly RL, red teaming** | OpenAI Atlas and GPT-Red, Google automated red teaming, Promptfoo, PyRIT, garak, Cisco algorithmic red teaming | Continuous fresh attacks that become adversarial-training data |
| **Production telemetry** | Vendors' "threat intelligence" (Lakera, Cisco, Palo Alto, CrowdStrike) | The moat: real traffic and real benign hard negatives. Rarely published |
| **Human-data and RL-environment vendors** | Turing, Mercor (bought Sepal AI and Deeptune, which builds enterprise-app simulation gyms), Handshake AI; environment builders Prime Intellect (Environments Hub, 2,500+ environments, open `verifiers`), Mechanize, HUD (MIT-licensed SDK), Veris | Expert demonstrations and graders for agent training. An "RL environments" market grew through 2025–26 ([rl-list](https://www.rl-list.com/), [Pavlov's List](https://pavlovslist.com/)) |

### 6.5 Standards and government evaluation
- **OWASP Top 10 for Agentic Applications (2026)**, announced December 2025: ASI01 *Agent Goal Hijack* (injected content in documents, email, web pages and tool outputs) through ASI10 *Rogue Agents*. The MS taxonomy v2 cross-references ASI01, ASI03 and ASI04 ([summary](https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026)).
- **NIST AI 100-2e2025** (March 2025): the adversarial-ML taxonomy and terminology for predictive and generative AI ([NIST](https://csrc.nist.gov/pubs/ai/100/2/e2025/final)).
- **US CAISI:**
  - *agent hijacking evaluations* on AgentDojo (an Inspect port, "agentdojo-inspect", is published). Lessons: frameworks need continuous expansion, evaluations must adapt to new defences, and **multi-attempt** attack success is more realistic;
  - an AI Agent Standards Initiative, reported for February 2026; secondary sources only ([NIST](https://www.nist.gov/node/1872381), [data.gov](https://catalog.data.gov/dataset/agentdojo-inspect)).
- **UK AISI:** co-ran the Gray Swan challenges and b3.

### 6.6 What industry practice adds to the academic picture
1. **The deployment contract is narrower than research assumes.** The decision must come before the tool call, as **allow or block** (no modify), within **about 1 second**. It sees the prompt, history and tool name and arguments. Tool outputs are often *not* scanned (Copilot Studio), and `tools/list` often isn't sanitised (Model Armor).
2. **Defence in depth is the norm**: model-level adversarial training, classifiers on untrusted content, deterministic authorisation (Cedar, Rule of Two, CaMeL-style), user confirmation for risky actions, and continuous red teaming. No vendor claims one classifier is enough.
3. **The best data is human and adversarial**, collected through games, competitions and bounties, then multiplied by automated red teaming and synthesis. Purely synthetic attack data is not what the leaders rely on.
4. **Production telemetry is the moat**, which explains why the acquirers were platform companies with traffic.
5. **Over-defence is a commercial risk.** "The Autonomy Tax" (2026): defence-trained models *timed out on 99% of benign agent tasks* (against 13% for baselines). They showed 25–71% benign over-refusal and were still bypassed by simple attacks, because they learned surface attack patterns ([2603.19423](https://arxiv.org/abs/2603.19423)).
6. **Policy conditioning and deterministic policy are converging with learned judgement**: gpt-oss-safeguard takes a written policy as input, and AgentCore pairs probabilistic guardrails with Cedar.

---

## 7. Where the field agrees (October 2026)

1. **Specify, then generate.** Start from a taxonomy or specification grid (AgentAlign, AuraGen, Rainbow Teaming, Constitutional Classifiers) so labels are fixed by construction and coverage and balance are controlled.
2. **Ground in real material.** Real tool schemas and servers (TOUCAN, MCPTox), real documents (AgentInstruct, Learn-by-Interact), real attack tactics (WildTeaming, LLMail-Inject). Pure generation from nothing drifts.
3. **Execute where possible, simulate where necessary.** Executable synthetic environments beat LLM-simulated tools for label reliability; check labels against environment state.
4. **Minimal or contrastive pairs at the decision point.** StepGen's shared-prefix branches, AgentAlign's benign chains, WildJailbreak's contrastive benign examples, Instruction Hierarchy's two kinds of training data. This is the main defence against shortcuts and over-refusal.
5. **Verify in layers.** Format and rule checks, then execution, then an independent judge or reward model, then a human audit sample. Never trust the generator's label alone.
6. **Train with adversaries in the loop.** Static attack sets age quickly. RL or co-evolved attackers generate the hard positives, and their outputs become training data.
7. **Train balanced.** Balance-GRPO and calibrated difficulty explicitly guard against a model that blocks everything or allows everything.
8. **Evaluate on held-out real data from a different provenance.** That means leave-one-dataset-out or leave-one-source-out, time-based splits (LLMail-Inject phases), externally sourced benign sets (PIDS-Bench) and adaptive attacks. Report over-defence on real benign traffic, not curated look-alikes.
9. **General frontier LLMs are strong baselines** for trajectory judgement (TraceSafe, ATBench). A specialised model has to beat them on cost, latency or calibration.
10. **Keep the real data.** Accumulate rather than replace; synthetic data fills gaps and should not displace real data.
11. **Industry runs layered defences continuously** (§6): adversarial training, classifiers, deterministic authorisation, confirmations and red teaming that never stops. Its most valued data is adversarial human data (games, competitions, bounties) multiplied by automated attackers, plus private production telemetry.

---

## 8. What this means for Jev

**The proposed plan matches the state of the art.** The recipe (taxonomy grid, seeds from real sources, minimal pairs at the decision point, verification, real held-out evaluation) is essentially AuraGen plus StepGen plus AgentAlign. Specific adjustments the literature supports:

1. **Use AuraGen's structure:** generate benign base trajectories first, then *inject* a categorised risk at a chosen step with calibrated difficulty, then branch the decision step into ALLOW / BLOCK (and REVIEW) variants, as in StepGen. This gives the shared-prefix minimal pairs that fix the InjecAgent shortcut directly.
2. **Ground tools in real schemas.** Take tool lists and descriptions from MCPTox's real servers, TOUCAN-style real MCP servers, and InjecAgent and ATBench tool pools from the *train split* only.
3. **Prefer executable environments to LLM-simulated tools wherever labels depend on state**: modes 17 (confirmation), 19 (scope) and 11 (delayed effect). EnvScaler or ScaleEnv-style generated sandboxes, or a small AgentDojo-style suite, make the label checkable.
4. **Add an adversarial generator.** An RL or search attacker (RL-Hammer, PISmith style) against Jev itself, or against agent models, produces hard BLOCK positives. Keep a pool of past attackers (CoER) so training doesn't overfit the latest one.
5. **Label outcome types, not just decisions.** Add ignored / refused / complied to `outcome` ("Ignored, Not Refused"), so Jev learns that ignoring an injection *and finishing the task* is the target ALLOW.
6. **Plan for provenance-sensitive over-defence** (PIDS-Bench). Synthetic look-alikes will improve over-defence on synthetic look-alikes, but maybe not on real benign traffic. Real external benign sets are needed: AgentDyn-style helpful third-party instructions, NotInject, and logged real agent traffic if any becomes available.
7. **Make leave-one-source-out the headline metric.** This means implementing the planned dataset-identity probe: the 96.6% dataset-identification result shows how strong source signals are. Report each source held out in turn alongside the current splits.
8. **Use adaptive-attack evaluation before any robustness claim** ("The Attacker Moves Second").
9. **Account for calibration with LLM labels.** Jev is meant to be calibrated, and synthetic labels carry structured noise. Keep the per-rule confidence and provenance already in the schema, mark synthetic labels with their own rule ids, filter on judge self-consistency, and calibrate *only* on real held-out data (R-Judge, human-audited subsets).
10. **Benchmark a frontier LLM as a judge** on the same evaluation sets. TraceSafe and ATBench suggest it is a strong baseline that Jev must beat or match more cheaply.
11. **Diversify generators and personas** (Persona Hub style conditioning, several generator model families), and measure diversity rather than assume it.
12. **Check the licences and terms of use** of generator models: many providers restrict using outputs to train competing models. And keep the existing source-licence gaps (ToolSafe, R-Judge, MCPTox) on the open-items list.

**Further adjustments from industry practice (§6):**

13. **Design to the deployment contract.** For the Copilot Studio hook: decide before the tool call, return allow or block, **within 1 s**, from the prompt, history and tool call. That means:
    - a small, fast model at serving time, with frontier models used offline for labelling and as a judge;
    - an explicit timeout default (fail closed or fail open);
    - REVIEW → block mapping stays as decided.

    Because the hook doesn't scan tool outputs, Jev's own judgement of the *planned call in its context* carries the decision. The separate tool-output labels (`<event>:tool_result`) are for deployments that can pass outputs in.
14. **Plan the telemetry flywheel early.** The vendors' advantage is production traffic. Design consent, redaction and review so that logged decisions (especially overridden blocks, i.e. false positives) become labelled records, with their own `source` and provenance.
15. **Add competition and crowdsourced data as sources**, after checking licences:
    - the Gray Swan / UK AISI agent red-teaming and IPI Arena attack datasets and the ART benchmark;
    - Lakera/AISI **b3** (19k crowdsourced attacks on agent LLM calls).

    These provide the adaptive human attacks synthetic data can't.
16. **Measure over-defence like a product metric.** Report the benign-task completion and timeout rate of agents *with Jev in the loop*, not only classifier false-positive rates (the Autonomy Tax result).
17. **Report against OWASP ASI01–ASI10** as well as the MS taxonomy, so results map to how enterprise buyers talk. Use CAISI-style multi-attempt attack success on `agentdojo-inspect` for comparable numbers.
18. **Consider policy as an input.** Policy-conditioned judging (gpt-oss-safeguard) and deterministic layers (Cedar, Rule of Two) suggest a product direction for Jev: take a customer policy, such as allowed recipients, payment limits or confirmation rules, as context. That is also how modes 17 and 19 become decidable at all.

**Gaps in the literature this project could fill:**
- No published dataset combines decision-time step labels, a full taxonomy mapping, per-label provenance and confidence, and evaluation by held-out source.
- No study measures how a guard trained on synthetic data *transfers to real data* for agent tool calls specifically; PIDS-Bench covers text detectors only.

---

## 9. Reading list (by priority for this project)

**Read first:**
- AuraGen / Safiron, *Building a Foundational Guardrail for General Agentic Systems via Synthetic Data* (ICLR 2026): https://arxiv.org/abs/2510.09781
- StepGuard / StepGen (2026): https://arxiv.org/abs/2608.24777
- AgentAlign (2025): https://arxiv.org/abs/2505.23020
- When Benchmarks Lie (2026): https://arxiv.org/abs/2602.14161
- PIDS-Bench (2026): https://arxiv.org/abs/2609.15017
- The Attacker Moves Second (2025): https://arxiv.org/abs/2510.09023
- Ignored, Not Refused (2026): https://arxiv.org/abs/2610.23254

**Agent and tool data generation:**
- APIGen-MT: https://arxiv.org/abs/2504.03601
- ToolACE: https://arxiv.org/abs/2409.00920
- TOUCAN: https://arxiv.org/abs/2510.01179
- Learn-by-Interact: https://arxiv.org/abs/2501.10893
- ToolEmu: https://arxiv.org/abs/2309.15817
- τ²-bench: https://arxiv.org/abs/2506.07982
- EnvScaler: https://arxiv.org/abs/2601.05808
- ScaleEnv: https://arxiv.org/abs/2602.06820
- EnvFactory: https://arxiv.org/abs/2605.18703

**Injection defences and guard data:**
- SecAlign: https://arxiv.org/abs/2410.05451
- Instruction Hierarchy: https://arxiv.org/abs/2404.13208
- TaskTracker: https://arxiv.org/abs/2406.00799
- PromptShield: https://arxiv.org/abs/2501.15145
- InjecGuard / NotInject: https://arxiv.org/abs/2410.22770
- WildTeaming: https://arxiv.org/abs/2406.18510
- ShieldGemma: https://arxiv.org/abs/2407.21772
- LlamaFirewall: https://arxiv.org/abs/2505.03574
- Constitutional Classifiers: https://www.anthropic.com/research/constitutional-classifiers
- ToolSafe / TS-Guard: https://arxiv.org/abs/2601.10156
- TraceSafe: https://arxiv.org/abs/2604.07223
- ATBench: https://arxiv.org/abs/2604.02022

**Adversaries and co-evolution:**
- Rainbow Teaming: https://arxiv.org/abs/2402.16822
- RainbowPlus: https://arxiv.org/abs/2504.15047
- RL-Hammer: https://github.com/facebookresearch/rl-injector
- PISmith: https://arxiv.org/abs/2603.13026
- CoER / CoRL: https://arxiv.org/abs/2609.07529
- AdvSim2Real: https://arxiv.org/abs/2610.08773
- OpenAI GPT-Red: https://alignment.openai.com/misalignment-reports/self-replicating-prompt-injections-exist/

**Benchmarks and their critiques:**
- Firewalls or Stronger Benchmarks: https://arxiv.org/abs/2510.05244
- AgentDyn: https://arxiv.org/abs/2602.03117
- Agentic Benchmark Checklist: https://arxiv.org/abs/2507.02825
- LLMail-Inject: https://arxiv.org/abs/2506.09956
- MCP-SafetyBench: https://arxiv.org/abs/2512.15163
- MCPSecBench: https://arxiv.org/abs/2508.13220

**Defences by design:**
- CaMeL: https://arxiv.org/abs/2503.18813
- Agents Rule of Two: https://ai.meta.com/blog/practical-ai-agent-security/

**Industry:**
- OpenAI, Hardening Atlas against prompt injection: https://openai.com/index/hardening-atlas-against-prompt-injection
- Anthropic, Prompt injection defences (browser use): https://www.anthropic.com/research/prompt-injection-defenses
- Google, Gemini layered defence: https://blog.google/security/mitigating-prompt-injection-attacks/
- Google Workspace, continuous approach: https://blog.google/security/google-workspaces-continuous-approach-to-mitigating-indirect-prompt-injections/
- Copilot Studio external threat detection: https://learn.microsoft.com/en-us/microsoft-copilot-studio/external-security-webhooks-interface-developers
- AWS AgentCore Policy guardrails: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html
- Google Model Armor for MCP: https://docs.cloud.google.com/model-armor/model-armor-mcp-google-cloud-integration
- Lakera/AISI b3 benchmark: https://www.nasdaq.com/press-release/lakera-launches-open-source-security-benchmark-llm-backends-ai-agents-2025-10-28
- Gray Swan × UK AISI results: https://www.grayswan.ai/blog/uk-aisi-x-gray-swan-agent-red-teaming-challenge-results-snapshot
- IPI Arena paper: https://arxiv.org/abs/2603.15714
- CAISI competition insights: https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition
- PyRIT: https://arxiv.org/abs/2410.02828
- Protect AI classifier card: https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2
- The Autonomy Tax: https://arxiv.org/abs/2603.19423
- NIST AI 100-2e2025: https://csrc.nist.gov/pubs/ai/100/2/e2025/final

**General synthetic data:**
- Long et al. survey: https://aclanthology.org/2024.findings-acl.658/
- Best Practices and Lessons Learned: https://arxiv.org/abs/2404.07503
- Magpie: https://arxiv.org/abs/2406.08464
- Persona Hub: https://arxiv.org/abs/2406.20094
- AgentInstruct: https://arxiv.org/abs/2407.03502
- Synthetic data for text classification, potential and limitations: https://arxiv.org/abs/2310.07849
- Accumulating real and synthetic data: https://arxiv.org/abs/2404.01413
- Model collapse position paper: https://arxiv.org/abs/2503.03150
- LLM-as-a-Judge survey: https://arxiv.org/abs/2411.15594
- Calibrating classifiers on LLM-generated noisy labels (SiDyP): https://arxiv.org/abs/2505.19675
