# TOUCAN: agent runs on real MCP servers (benign)

**Snapshot:** `0df3cf37f2abefb380370cfb02eabea2a35ae782/` · downloaded 2026-10-21 · README plus 3 parquet shards, 434 MB (checksums in `manifest.json`)
**Source:** Hugging Face [`Agent-Ark/Toucan-1.5M`](https://huggingface.co/datasets/Agent-Ark/Toucan-1.5M), the first shard of each teacher subset: Kimi-K2 00000-of-00040, OSS 00000-of-00047, Qwen3 00000-of-00044. That is 3 of 131 shards, 35,227 runs.
**Paper:** *TOUCAN: Synthesizing 1.5M Tool-Agentic Data from Real-World MCP Environments* (arXiv 2510.01179, ICLR 2026)
**Licence:** Apache-2.0

## What it is
- **Runs:** ordinary user tasks (LLM-generated queries) solved by teacher models on about 500 real MCP servers, with real tool execution. No attacker is involved.
- **Columns:** `uuid`, `subset_name` (all single-turn-original here), `messages`, `question`, `available_tools`, `target_tools`, and the dataset's own quality assessments (`question_quality_assessment`, `response_quality_assessment` with `overall_score` 1–5), plus `metadata` (MCP servers and their info).
- **Message format:** the system prompt repeats the tool list. Assistant turns carry either `reasoning_content` or a `function_call` (name, JSON arguments). Tool outputs have role `function`.

## Use in this project
Converted (mappings 0.6.7) into 6,440 ALLOW step records from 3,054 runs on 362 servers:
- runs with `overall_score` 3.5 or higher;
- per primary server, up to 20 runs that call a tool with side effects (write, send, execute, pay, delete) plus 5 others;
- up to 3 steps per run, side-effect calls first, with about 10% final answers.

About 2,100 records are legitimate sensitive actions. The data is split by MCP server.

**Caveat:** it is benign by dataset design, not safety review. An LLM-judge screen for risky requests is still to do.
