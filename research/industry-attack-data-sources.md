# How agent-security companies obtain attack data

*Industry review, October 2026. Sources are company posts, reports, product documentation, filings and trade press. Vendor figures are self-reported and largely unverified; deal values are as reported.*

## Summary

Companies get attack data through eight channels, often several at once:

1. **Crowdsourced attack games.** Free public games where players try to trick an AI system; every attempt is logged.
2. **Sponsored competitions.** Prize-funded events, often co-run with government AI institutes and frontier labs, which share the data with sponsors.
3. **Bug bounties and live hacking events.** Paid reports of real exploits in shipped products.
4. **In-house offensive research teams.** They find novel attack classes and publish them at security conferences.
5. **Production telemetry.** Attacks seen in customer traffic flowing through a vendor's guardrail or proxy.
6. **In-the-wild scanning and honeypots.** Sweeping the public web for planted injections, and decoy systems that attract attackers.
7. **Automated and RL red teaming.** Attacker models generate fresh attacks continuously; the results feed adversarial training and attack libraries.
8. **Public datasets, papers and acquisitions.** Aggregating open datasets and academic attacks, and buying companies that already hold data, communities or tools.

Two patterns recur:
- **Pure-play vendors** relied on games and telemetry, and were mostly acquired by platform companies with traffic.
- **Frontier labs** rely on automated RL red teaming plus bounties and sponsored competitions.

---

## 1. Crowdsourced attack games

- **Lakera, Gandalf** (now Check Point):
  - a public game where players try to make an LLM reveal a password, with levels of increasing defence;
  - the company says it has 80M+ attack patterns, and its handbook cites a "database of nearly 30 million LLM attack data points";
  - part of it is released on Hugging Face (`gandalf_ignore_instructions`, `gandalf_summarization`, `mosscap_prompt_injection`, and the *Gandalf the Red* sets: ~279k raw prompts, ~36k deduplicated with attack-category labels);
  - the paper describes Gandalf as "a crowd-sourced, gamified red-teaming platform designed to generate realistic, adaptive attack datasets" ([Gandalf the Red](https://arxiv.org/abs/2501.07927), [HF collection](https://huggingface.co/collections/Lakera/gandalf)).
- **Lakera, Gandalf: Agent Breaker:** an agent-focused version. With the UK AI Security Institute it became the **b3 benchmark**: 19,433 crowdsourced attacks across 10 "threat snapshots" of individual agent LLM calls. The attacks cover system-prompt exfiltration, phishing links, malicious code, denial of service and unauthorised tool calls ([b3](https://www.nasdaq.com/press-release/lakera-launches-open-source-security-benchmark-llm-backends-ai-agents-2025-10-28)).
- **Why games work:** large volumes, real human creativity, adaptive attackers (each level's defence forces new tactics), and almost no cost per sample. The weaknesses: the targets are toys (password reveal), and labels are noisy because collection is automatic; Lakera notes noise in one dataset card.

## 2. Sponsored competitions

| Competition | Organiser and partners | Scale | Data |
| --- | --- | --- | --- |
| **Agent Red-Teaming Challenge** (March–April 2025) | Gray Swan with UK AISI (funding and judging) | ~1.8M attack attempts, 62k successful breaks, 22 anonymised models, $171.8k prizes | Results published; the challenge preceded the IPI Arena |
| **Indirect Prompt Injection Arena** (2026) | Gray Swan with UK AISI, US CAISI and frontier labs | 13 frontier models, 464 red teamers, 272k+ attacks; "no model immune" | Full dataset shared with UK AISI and US CAISI; an attack dataset and the **ART benchmark** released ([paper](https://arxiv.org/abs/2603.15714), [CAISI](https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)) |
| **Pangea Prompt Injection Challenge** (March 2025) | Pangea (bought by CrowdStrike, September 2025, ~$212M per its 10-Q) | ~330k attempts, 300M+ tokens, 800+ players from 85 countries, 3 rooms of increasing difficulty | Report: about 1 in 10 attempts beat basic guardrails, and a prompt that failed 99 times could succeed on the 100th ([Pangea report](https://info.pangea.cloud/hubfs/research-report/defending-against-prompt-injection-2025.pdf), [SEC 10-Q](https://www.sec.gov/Archives/edgar/data/1535527/000153552725000033/crwd-20251031.htm)) |
| **HackAPrompt 1.0 / 2.0** | Learn Prompting. 1.0 was with OpenAI, Scale AI and Hugging Face; 2.0 adds a track with jailbreaker Pliny | 2.0: ~100 challenges in 5 tracks, including web-use agents, $500k in prizes | Pliny-track data announced to be open-sourced ([Decrypt](https://decrypt.co/323351/how-to-trick-chatgpt-and-get-paid-50000)) |
| **LLMail-Inject** (2024–25) | Microsoft, with academic partners | 839 participants, 461,640 submissions, 208,095 unique prompts | Fully released ([paper](https://arxiv.org/abs/2506.09956)) |
| **huntr** | Protect AI's AI/ML bug bounty community (10k+ researchers), now Palo Alto Networks | — | Moving from an open-source bug bounty to a **challenge-based competition platform** ([huntr FAQ](https://blog.huntr.com/huntr-2-0-faq)) |

**Why competitions work:** they target realistic agents (tools, email, browsing) rather than toy secrets, they produce verified successes judged automatically and then appealed by humans, and the data comes with government and lab validation. Sponsors usually get the full data first.

## 3. Bug bounties and live hacking events

- **Google AI Vulnerability Reward Program** (October 2025): up to $20k base, $30k with multipliers. Indirect injection causing *rogue actions* or *exfiltration* is in scope; direct jailbreaks and content issues are not ([The Register](https://www.theregister.com/2025/10/07/google_ai_bug_bounty/)).
- **Microsoft Copilot AI bounty and Zero Day Quest:** Copilot bounties paid to live-event participants, with **+100% multipliers for zero-click prompt injection leading to data exfiltration** and for remote code execution via untrusted input, and a $5M prize pool ([MSRC](https://www.microsoft.com/en-us/msrc/bounty-m365-copilot), [BleepingComputer](https://www.bleepingcomputer.com/news/microsoft/microsoft-announces-5-million-prize-pool-for-zero-day-quest-hacking-contest/)).
- Other labs run bounty programmes, and huntr covered the open-source AI/ML stack.
- **What bounties give:** few but high-value, confirmed, real-product exploit chains with impact assessed.

## 4. In-house offensive research teams

Vendors run research labs that find attack classes, publish them (often at Black Hat or DEF CON), and add them to their detection and red-teaming libraries:
- **Zenity Labs, "AgentFlayer"** (Black Hat 2025): zero- and one-click exploit chains against ChatGPT Connectors, Copilot Studio, Cursor with a Jira MCP server, Salesforce Einstein, Gemini and Microsoft Copilot. Examples include a poisoned document that makes the assistant search connected storage for secrets and exfiltrate them via image URLs, and CRM records that redirect customer email ([CSO Online](https://csoonline.com/article/4036868/black-hat-researchers-demonstrate-zero-click-prompt-injection-attacks-in-popular-ai-agents.html)).
- **HiddenLayer, "Policy Puppetry"** (April 2025): prompts disguised as policy files (XML, INI, JSON) bypassed safeguards across models from eight providers. It was vendor-reported and not independently replicated ([SecurityWeek](https://www.securityweek.com/all-major-gen-ai-models-vulnerable-to-policy-puppetry-prompt-injection-attack/amp/)).
- **Invariant Labs** (now Snyk): named "tool poisoning" and "MCP rug pulls"; MCP-scan pins tool hashes ([Snyk Labs](https://labs.snyk.io/resources/snyk-labs-invariant-labs)).
- **Mindgard:** an attack library built from about ten years of Lancaster University research, extended by PhD researchers and offensive specialists and mapped to MITRE ATLAS ([Mindgard](https://mindgard.ai/ai-attack-library)).
- **Palo Alto Unit 42**, **Cisco** (Robust Intelligence's algorithmic red teaming) and the **Microsoft AI Red Team** (PyRIT) do the same at larger scale.

## 5. Production telemetry

Vendors that sit in the traffic path (a guardrail API, proxy, browser extension or agent-platform hook) see real attacks and real benign traffic:
- **Pillar Security, "State of Attacks on GenAI"** (October 2024): telemetry from 2,000+ production AI apps over three months. It reports 20% of jailbreak attempts bypassed guardrails, 90% of successful attacks leaked data, and 57.6% of apps were customer-support bots ([Pillar](https://pillar.security/resources/the-state-of-attacks-on-genai)).
- **Palo Alto Unit 42, "Fooling AI Agents: Web-Based Indirect Prompt Injection Observed in the Wild"** (March 2026): payloads *as found in telemetry*, not constructed. One case is a hidden payload on a review site that made an AI ad-review agent approve non-compliant ads (December 2025). Secondary coverage cites 22 payload techniques, with intents from anti-scraping to forced purchases and data destruction ([Unit 42](https://unit42.paloaltonetworks.com/ai-agent-prompt-injection.md), [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-indirect-prompt-injection-in-the-wild-2026/)).
- **Runtime hooks as sensors.** Microsoft Copilot Studio's external threat-detection webhook sends every planned tool call (prompt, history, tool name and inputs) to partners for an allow/block decision within 1 second. Zenity, CrowdStrike (Pangea's AIDR) and Palo Alto Prisma AIRS all plug in ([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/external-security-webhooks-interface-developers)). Each decision point doubles as a data point for the vendor.
- **"Threat intelligence" claims** by Cisco, Lakera, Palo Alto and CrowdStrike rest on this traffic. It is rarely published, and it is the main reason security platforms bought the specialist vendors in 2025–26:

  | Company | Acquirer | Reported |
  | --- | --- | --- |
  | Lakera | Check Point | ~$300M |
  | Protect AI | Palo Alto Networks | $634.5M |
  | Prompt Security | SentinelOne | not disclosed |
  | CalypsoAI | F5 | $180M |
  | Pangea | CrowdStrike | ~$212M |
  | Invariant Labs | Snyk | not disclosed |

## 6. In-the-wild scanning and honeypots

- **Google:** threat-intelligence teams swept the public web for known indirect-injection patterns, using pattern matching, then Gemini classification, then manual review to remove false positives. They found mostly low-sophistication injections (pranks, SEO, tone changes) but a rising malicious trend; secondary coverage cites a 32% rise ([Google](https://blog.google/security/prompt-injections-web/)).
- **Forcepoint and others** report hidden instructions on live sites, such as a fixed $5,000 PayPal.me transfer request, or an HTML comment telling the agent to leak an API key ([CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-indirect-prompt-injection-in-the-wild-2026/)).
- **Palisade Research, LLM Agent Honeypot:**
  - decoy SSH servers seeded with prompt injections, plus response-time analysis (LLM agents answer in about 1.7 s), to catch *AI* attackers;
  - about 8.1M hacking attempts flagged 8 potential AI agents over three months ([paper](https://arxiv.org/abs/2410.13919)).
- **Incident sharing:** the Linux Foundation / Open Secure AI Alliance **SAFE** (Shared AI Findings Exchange), led by NVIDIA, Cisco, CrowdStrike, Hugging Face and Red Hat, proposes confidential collection of agentic AI incidents and near misses ([SecurityWeek](https://www.securityweek.com/cybersecurity-alliance-drafts-safe-guidelines-for-sharing-ai-incident-data/)). CoSAI (OASIS) publishes guidance but runs no incident database.

## 7. Automated and RL red teaming

- **Frontier labs:**
  - OpenAI trains an **RL attacker** that finds multi-step injections against ChatGPT Atlas; each new attack class goes into adversarial training ([OpenAI](https://openai.com/index/hardening-atlas-against-prompt-injection)). Its **GPT-Red** self-play framework found fake tool messages, fake system warnings and *self-replicating* injections ([OpenAI](https://alignment.openai.com/misalignment-reports/self-replicating-prompt-injections-exist/));
  - Anthropic trains with RL on **simulated web pages carrying injections** ([Anthropic](https://www.anthropic.com/research/prompt-injection-defenses));
  - Google uses "dynamic, machine-learning-driven frameworks" that generate and iterate attack payloads ([Google](https://blog.google/security/google-workspaces-continuous-approach-to-mitigating-indirect-prompt-injections/));
  - Meta released **RL-Hammer**.
- **Tools that generate attacks for customers:**
  - Promptfoo (bought by OpenAI, March 2026);
  - Microsoft **PyRIT** (attacker model, target and scorer; multi-turn, PAIR and cross-prompt injection orchestrators);
  - NVIDIA **garak** / NeMo Auditor;
  - Cisco algorithmic red teaming;
  - Mindgard and Giskard.

  Each run against a customer system also produces attack data.
- **Synthetic data platforms:** NVIDIA bought **Gretel** (March 2025) and ships Data Designer / Safe Synthesizer. Anthropic's **Constitutional Classifiers** are trained on attacks and content generated from a written constitution.

## 8. Public datasets, papers and acquisitions

- **Open classifiers are usually trained on aggregated public data.** Protect AI's DeBERTa injection model (v2) combines public Hugging Face datasets (its card lists their licences) with injections written from papers, competitions and community feedback (LLM Guard users). It states its limits: English only, no jailbreaks, false positives on system prompts ([model card](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2)).
- **Academic benchmarks** (AgentDojo, InjecAgent, ASB, MCPTox and others) and released competition data feed vendors' attack libraries and evaluations. US CAISI runs agent-hijacking evaluations on an Inspect port of AgentDojo ([data.gov](https://catalog.data.gov/dataset/agentdojo-inspect)).
- **Acquisitions buy data, communities and pipelines,** not just products: Gandalf with Lakera, huntr with Protect AI, the challenge dataset and AIDR with Pangea, Gretel's synthesis stack with NVIDIA.

---

## Comparison of channels

| Channel | Volume | Realism of target | Adaptivity | Label quality | Who relies on it |
| --- | --- | --- | --- | --- | --- |
| Games | Very high (millions) | Low to medium (toy secrets; agent snapshots in newer games) | High | Noisy (automatic) | Lakera |
| Competitions | High (100k–2M) | High (real agents and tools) | High | High (judged, with appeals) | Gray Swan, Pangea, Microsoft, AISI/CAISI, labs |
| Bounties | Very low | Very high (shipped products) | High | Very high | Google, Microsoft, other labs |
| Research teams | Low | High | — | High | Zenity, HiddenLayer, Invariant, Unit 42, Mindgard |
| Telemetry | Very high | Highest (real traffic) | Real attackers | Weak unless reviewed | Pillar, Palo Alto, Cisco, CrowdStrike, Check Point |
| Web scanning and honeypots | Medium | Highest (in the wild) | Real attackers | Needs manual review | Google, Unit 42, Forcepoint, Palisade |
| Automated / RL red teaming | Unlimited | Depends on environment | Adapts to the target | Automatic (success judged) | OpenAI, Anthropic, Google, Meta, tool vendors |
| Public datasets | Medium | Mixed | Static | Mixed | Open-source classifiers, smaller vendors |

**Observations:**
- **Labs generate and buy; vendors observe.** Labs depend on RL attackers plus paid human red teams and bounties. Vendors' advantage was what they saw in real traffic and gamified communities.
- **Human data is still valued.** Every major player still pays for human adversarial data (competitions, bounties, live events), even with automated attackers.
- **Real attacks look different from benchmark attacks.** In-the-wild injections are currently low-sophistication but rising: SEO, ad approval, purchases, payment requests. That is a different mix from benchmark attacks focused on exfiltration.
- **Little of this is shared.** Telemetry and full competition datasets mostly stay private or go to government institutes. Public releases are subsets: Gandalf datasets, LLMail-Inject, b3 and the ART benchmark.

---

## How labs and vendors label attack data

### Who decides that an attack worked
| | Frontier labs | Security vendors | Competitions and games (run by either) |
| --- | --- | --- | --- |
| **Unit labelled** | The **outcome of an episode** in an environment the lab controls: did the agent take the adverse action? | The **input text**: is this content an attack, and which kind? | A **submission**, scored by the game or the judge |
| **Success signal** | Environment state or grader. The RL attacker's reward is the target taking the adverse action (GPT-Red, the Atlas attacker); Anthropic rewards the agent for spotting and refusing planted injections on simulated pages | Detector verdicts in telemetry (Pillar, Palo Alto, CrowdStrike, Cisco), then analyst triage for reported cases (Unit 42) | **Mechanical checks:** password extracted (Gandalf), "Access Granted" (Tensor Trust), exact target phrase (HackAPrompt), secret revealed (Pangea), system flags (LLMail-Inject: retrieved, detected, sent, right recipient, right content). **LLM judges** per target behaviour, calibrated by UK AISI, with **human appeals** (Gray Swan); a stricter judge filters the ART benchmark. **Scoring functions** per threat snapshot (b3) |
| **Where the label comes from** | *By construction*: the lab planted the injection, so the attack and its location are known. Success is judged by environment checks or model graders | *Observed*: unknown content classified after the fact by detectors, classifiers and analysts | *Verified outcome*, automatic first and then human-reviewed where prizes depend on it |

### What the label contains
- **Labs:** mostly **binary success or refusal per episode**, and harm category for policy violations. Human red-team data adds richer fields. Anthropic's public red-team release (38,961 attacks) has a red teamer's **Likert self-rating of success**, a **preference-model harmlessness score** and **crowdworker tags** on a 1,000-attempt sample. OpenAI's external red teaming uses rubrics, example score levels and pass/fail thresholds (secondary report). Labelled data becomes *training signal* (adversarial training, RL reward, classifier data), not a published taxonomy.
- **Vendors:** **technique and intent taxonomies** for detection and reporting.
  - Lakera classifies Gandalf attacks by *trigger* (following HackAPrompt's 29-technique taxonomy) using active learning, on 36k deduplicated prompts.
  - Unit 42 labels in-the-wild payloads by technique (22 reported) and **intent and severity** (anti-scraping and SEO through purchases and data destruction).
  - Google's web sweep uses pattern matching, then Gemini classification, then **manual review**, with categories running from pranks and SEO to exfiltration and destruction.
  - Mindgard maps its library to **MITRE ATLAS** and OWASP.
  - Open classifiers (Protect AI) inherit **binary labels from the source datasets** they aggregate.
- **Competitions:** success plus the **target behaviour or objective** (44 behaviours in ART; 5 objective flags in LLMail-Inject), the model attacked, and the player. Some add a technique taxonomy afterwards (HackAPrompt).

### Benign data and negatives
- **Labs** get negatives for free: every episode where the agent completes the user task without the adverse action. They also label over-refusal against held-out benign tasks.
- **Vendors** have huge volumes of mostly *unlabelled* benign traffic. Explicit benign sets are small and curated (Gandalf the Red's BasicUser: 1,000 UltraChat prompts; BorderlineUser: 60 hand-written). Over-defence is measured on these.
- **Competitions** mostly record attacks only. Failed attempts are labelled "unsuccessful", not "benign".

### Weaknesses of each
- **Outcome labels** (labs, competitions) say whether an attack *worked against that model*, not whether the text is hostile. The same prompt flips label across models, and even across retries: Pangea saw prompts fail 99 times and succeed on the 100th.
- **Content labels** (vendors) depend on the detector that produced them, so novel attacks the detector missed are under-represented. They are only as good as the analyst review applied.
- **Automatic collection is noisy:** Lakera notes noise in a Gandalf set, and LLMail-Inject judge labels include an "Unclear" class.
- **Taxonomies don't line up across organisations:** HackAPrompt techniques, Unit 42 intents, ATLAS techniques, OWASP ASI categories, behaviour lists.

---

## Publicly available sources of this kind

*Checked in this research unless marked "verify". Licences vary and several are gated or research-only; check each before use.*

**Crowdsourced games**
- **Lakera Gandalf datasets** (Hugging Face, `Lakera/`):
  - `gandalf_ignore_instructions`, `gandalf_summarization` and `mosscap_prompt_injection`;
  - **Gandalf-RCT**: 279,675 prompts in 36,286 sessions from 15,448 users, PII removed, with a 36k deduplicated subset carrying attack-category predictions;
  - code and classification labels in `github.com/lakeraai/dsec-gandalf` ([collection](https://huggingface.co/collections/Lakera/gandalf), [paper](https://arxiv.org/abs/2501.07927)).
- **b3 / Gandalf: Agent Breaker:** 19,433 crowdsourced attacks on 10 agent threat snapshots, released open source. Repository and licence to verify ([paper](https://arxiv.org/abs/2510.22620)).
- **Tensor Trust:** 563k+ attacks and 118k+ defences from an online game, with prompt-hijacking and prompt-extraction benchmarks; data and code via tensortrust.ai/paper ([paper](https://arxiv.org/abs/2311.01011)).

**Competitions**
- **LLMail-Inject** (Microsoft): 461,640 submissions with objective flags and judge labels, on Hugging Face `microsoft/llmail-inject-challenge` ([paper](https://arxiv.org/abs/2506.09956)).
- **HackAPrompt 1.0:** all submissions, gated on Hugging Face as `hackaprompt/hackaprompt-dataset`, plus a 29-technique taxonomy ([dataset](https://huggingface.co/datasets/hackaprompt/hackaprompt-dataset), [paper](https://arxiv.org/abs/2311.16119)).
- **HackAPrompt 2.0, Pliny track:** `hackaprompt/Pliny_HackAPrompt_Dataset` on Hugging Face ([dataset](https://www.huggingface.co/datasets/hackaprompt/Pliny_HackAPrompt_Dataset/tree/main)).
- **Gray Swan IPI Arena:** a partial attack dataset on Hugging Face (`sureheremarv/ipi_arena_attacks`) and the open-source competition environment (`github.com/grayswansecurity/ipi_arena_os`), including 95 successful attacks on Qwen. The full data went only to UK AISI and US CAISI ([paper](https://arxiv.org/abs/2603.15714)).
- **Gray Swan ART benchmark:** 44 agent deployment settings, curated from 1.8M challenge submissions. Its public status is unclear: the paper says it is released, a later report calls it private ([paper](https://arxiv.org/abs/2507.20526)).
- *Verify:* SaTML 2024 LLM Capture-the-Flag competition dataset (ETH SPY Lab).

**Human red teaming**
- **Anthropic red-team attempts:** 38,961 transcripts with success ratings, harmlessness scores and tags, in `github.com/anthropics/hh-rlhf` (`red-team-attempts`). Licence unclear ([paper](https://arxiv.org/abs/2209.07858)).
- **"Ignored, Not Refused" corpus:** 33,000 agent trajectories (InjecAgent and AgentDojo) labelled by failure mode (ignored, refused or complied), with the judge prompt ([paper](https://arxiv.org/abs/2610.23254)).

**In the wild**
- **In-the-wild jailbreak prompts** (CCS 2024): 15,140 prompts, 1,405 of them jailbreaks, from Reddit, Discord, websites and open datasets (December 2022 to December 2023). On Hugging Face as `TrustAIRLab/in-the-wild-jailbreak-prompts`, MIT code, research only ([repo](https://github.com/verazuo/jailbreak_llms)).
- **Palisade LLM Agent Honeypot:** a public dashboard of statistics, not raw data (ai-honeypot.palisaderesearch.org) ([paper](https://arxiv.org/abs/2410.13919)).
- **Reports with examples but no datasets:** Unit 42's in-the-wild indirect injection report, Google's web sweep, the Pangea challenge report, Pillar's State of Attacks.

**Aggregated detector datasets** (built partly from the above)
- deepset/prompt-injections, jackhhao/jailbreak-classification, Harelix/Prompt-Injection-Mixed-Techniques-2024 and OpenSafetyLab/Salad-Data (these four are among the sources on Protect AI's model card).
- PromptShield (`hendzh/PromptShield`); NotInject (benign trigger-word set).

**Case and incident catalogues**
- MITRE ATLAS case studies; OWASP Agentic Top 10 example scenarios. *Verify:* AI Incident Database (incidentdatabase.ai), AVID.
