<div align="center">

# DeepRefine-Skill

<p align="center">
    <img src="./assets/icons.png" width="20%" style="max-width: 80;">
</p>

[![PyPi](https://img.shields.io/badge/PyPi-v0.1.7-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.7/)
[![Python](https://img.shields.io/badge/Python-3.10,3.11,3.12-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.7/)
[![Paper](https://img.shields.io/badge/Paper-DeepRefine-b31b1b.svg)](https://arxiv.org/pdf/2605.10488)
[![Project](https://img.shields.io/badge/Project-DeepRefine-green.svg)](https://github.com/HKUST-KnowComp/DeepRefine)

<img src="assets/harness.png" alt="workflow" width="360">

</div>

Type `/deeprefine` in your AI coding assistant after you've built a **[graphify](https://github.com/safishamsi/graphify)** knowledge base — it evolves `graphify-out/graph.json` from your session's Q&A so later retrieval improves.

```
/deeprefine
```

**Typical flow:** `graphify .` → `graphify query "..."` → `/deeprefine`.

---

## Two refinement modes

| | **Agent mode** (default) | **CLI mode** |
|---|--------------------------|--------------|
| **Trigger** | Cursor `/deeprefine` | `deeprefine refine` |
| **Loop** | Same control flow as `Reafiner.refine()` | Full `Reafiner` in DeepRefine |
| **Retrieval** | `graphify query` + k-hop from `graph.json` | FAISS + embeddings |
| **LLM** | Your session model (Cursor/agent) | vLLM or API (`DEEPREFINE_*`) |
| **Extra setup** | `pip install deeprefine-cli` only | DeepRefine repo + `atlastune` + API/vLLM |

---

## News

- **[2026/6/2] v0.1.7** — Cursor skill + `deeprefine refine` with configurable API. And strict DeepRefine agent loop.

---

## Quick start (agent mode)

| Step | What |
|:----:|------|
| 1 | `pip install deeprefine-cli` |
| 2 | `deeprefine cursor install` in your KB project |
| 3 | `graphify .` then `graphify query "..."` |
| 4 | Cursor chat: `/deeprefine` |

```bash
pip install deeprefine-cli graphify

cd /path/to/your-kb-project
deeprefine cursor install
graphify cursor install   # if not already
```

Then in your agent CLI:
```bash
/graphify .
/graphify query "your question"
/deeprefine
```

No `history add` required for `/deeprefine` — the agent records results via `deeprefine loop finish`.

---

## Quick start (CLI mode — FAISS + API/vLLM)

Requires [DeepRefine](https://github.com/HKUST-KnowComp/DeepRefine) in `atlastune` and inference configured.

```bash
conda activate atlastune
cd /path/to/DeepRefine && pip install -e .
pip install deeprefine-cli

cd /path/to/your-kb-project
deeprefine cursor install   # optional

# API (example)
export DEEPREFINE_LLM_URL=https://your-provider/v1
export DEEPREFINE_EMBED_URL=https://your-provider/v1
export DEEPREFINE_LLM_API_KEY=...
export DEEPREFINE_EMBED_API_KEY=...
export DEEPREFINE_MODEL=your-llm-model
export DEEPREFINE_EMBED_MODEL=text-embedding-3-small

# OR local vLLM (from DeepRefine repo)
# bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-0.6b-emb.sh
# bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-8b-vllm-reafiner.sh

deeprefine history add --query "your question"
deeprefine refine
```

---

## Agent loop (what `/deeprefine` must do)

Matches `Reafiner.refine()` in [DeepRefine](https://github.com/HKUST-KnowComp/DeepRefine) (`autorefiner/src/reafiner.py`):

```text
for step in 1..4:
  [Step: N]
  hop 1: graphify query "<question>"
  hop 2+: k-hop expand from prior entities (read graph.json)
  LLM → <judge>Yes</judge> or <judge>No</judge>
  stop if Yes

if len(history) <= 1 and Yes:
  early exit — no graph patch
else:
  LLM → <abduction>...</abduction>
  LLM → <refinement>insert_edge(...)|...</refinement>
  deeprefine loop validate --trace-file ...
  deeprefine apply --trace-file ... --refinement-file ...
  deeprefine loop finish --trace-file ...
```

Full rules and prompts: [SKILL.md](./SKILL.md) (installed to `.cursor/skills/deeprefine/SKILL.md`).

---

## Pipeline

```text
  project files
        │
        ▼ graphify
   graph.json ◄──────────────────────────────┐
        │                                    │
        ▼ graphify query "..."               │
   (session Q&A)                             │
        │                                    │
        └─► deeprefine refine ───────────────┘
        │
        ▼ graphify query "..."
```

DeepRefine does not build the graph; it patches `graph.json` so later `graphify query` retrieves better.

---

## Artifacts

```text
graphify-out/
├── graph.json
└── .deeprefine/
    ├── history.jsonl              # query history (CLI refine / loop finish)
    ├── loop_trace_<query_id>.json # agent loop audit (required for apply)
    ├── refinement_actions_*.txt   # <refinement> block from agent
    ├── refinement_results_*.jsonl # run logs
    ├── graph.json.bak             # backup before apply/refine
    └── cache/reafiner.pkl         # FAISS cache (CLI mode only)
```

---

## Repository layout

```text
DeepRefine-Skill/              ← this repo (PyPI: deeprefine-cli)
├── deeprefine_skill/
│   ├── SKILL.md               # bundled; copied on cursor install
│   ├── agent_loop.py          # trace validation (Reafiner rules)
│   └── ...
└── SKILL.md

DeepRefine/                    ← separate clone (CLI refine only)
├── autorefiner/
└── scripts/vllm_serve/

your-kb-project/
└── graphify-out/ ...
```

**Recommended sibling layout** (auto-detects `../DeepRefine` when `DEEPREFINE_REPO` is unset):

```text
www/code/
├── DeepRefine/
└── DeepRefine-Skill/
```

---

## Installation

### CLI package

| Method | Command |
|--------|---------|
| **PyPI** | `pip install deeprefine-cli==0.1.7` |
| **Source** | `pip install -e /path/to/DeepRefine-Skill` |

```bash
deeprefine --help
# Expect: cursor, history, index, refine, apply, loop
```

### Cursor skill

At **KB project root**:

| Command | Scope |
|---------|-------|
| `deeprefine cursor install` | `.cursor/skills/` (this project) |
| `deeprefine cursor install --user` | `~/.cursor/skills/` (all projects) |
| `deeprefine install` | alias for `cursor install` |

After upgrading the package, re-run `deeprefine cursor install` to refresh the skill.

### DeepRefine repo (CLI mode only)

```bash
conda activate atlastune
cd /path/to/DeepRefine && pip install -e .
# optional if not ../DeepRefine:
export DEEPREFINE_REPO=/path/to/DeepRefine
```

### Inference env (CLI mode)

| Variable | Default |
|----------|---------|
| `DEEPREFINE_LLM_URL` | *(empty; SDK default)* |
| `DEEPREFINE_EMBED_URL` | *(empty; SDK default)* |
| `DEEPREFINE_API_KEY` | fallback to `OPENAI_API_KEY` |
| `DEEPREFINE_LLM_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_EMBED_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_MODEL` | `gpt-4.1-mini` |
| `DEEPREFINE_EMBED_MODEL` | `text-embedding-3-small` |

---

## Commands

Run from **KB project root** (directory containing `graphify-out/graph.json`).

### Agent loop

| Command | Description |
|---------|-------------|
| `deeprefine loop init --query "..."` | Create `loop_trace_<id>.json` template |
| `deeprefine loop validate --trace-file T` | Check trace matches `Reafiner.refine()` |
| `deeprefine loop finish --trace-file T` | Log results + mark `history.jsonl` refined |
| `deeprefine apply --trace-file T --refinement-file F` | Apply `<refinement>` to `graph.json` |

### CLI refine (FAISS)

| Command | Description |
|---------|-------------|
| `deeprefine history add --query "..."` | Record a query |
| `deeprefine history list` | List history |
| `deeprefine history list --pending` | Unrefined only |
| `deeprefine refine` | Refine all pending |
| `deeprefine refine --query "..."` | Refine one query |
| `deeprefine refine --rebuild-index` | Rebuild FAISS first |
| `deeprefine index --rebuild` | Rebuild FAISS cache only |

### Cursor

| Command | Description |
|---------|-------------|
| `deeprefine cursor install \| uninstall` | Manage `/deeprefine` skill |

---

## Workflow with graphify

**One-time**

```bash
pip install graphify deeprefine-cli

cd /path/to/your-kb-project
graphify cursor install
deeprefine cursor install
```

**Each session**

| # | Action |
|:-:|--------|
| 1 | `graphify .` → `graphify-out/graph.json` |
| 2 | `graphify query "..."` |
| 3 | `/deeprefine` in Cursor *(recommended)* |
| 4 | *(optional)* `graphify query "..."` to verify |

**Terminal-only alternative:** `deeprefine history add` → `deeprefine refine` (needs DeepRefine + API/vLLM).

---

## Where to run what

| What | Where |
|------|-------|
| `pip install deeprefine-cli` | Any Python env |
| `pip install -e .../DeepRefine` | `atlastune` (CLI refine) |
| `graphify` / `deeprefine cursor install` | **KB project root** |
| `/deeprefine`, `deeprefine loop`, `deeprefine apply` | **KB project root** |
| `deeprefine refine` | **KB project root** + DeepRefine + inference |
| vLLM scripts | **DeepRefine repo** |

---

## License

MIT — see [LICENSE](./LICENSE).
