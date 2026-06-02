<div align="center">

# DeepRefine-Skill


[![PyPi](https://img.shields.io/badge/PyPi-v0.1.4-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.4/)
[![Python](https://img.shields.io/badge/Python-3.10,3.11,3.12-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.4/)
[![Paper](https://img.shields.io/badge/Paper-DeepRefine-b31b1b.svg)](https://arxiv.org/pdf/2605.10488)
[![Project](https://img.shields.io/badge/Project-DeepRefine-green.svg)](https://github.com/HKUST-KnowComp/DeepRefine)

</div>

Type `/deeprefine` in your AI coding assistant after you've built a **[graphify](https://github.com/safishamsi/graphify)** knowledge base — it patches `graphify-out/graph.json` from your session's query history to evolve your LLM-Wiki.

Works in **Cursor** (install the skill once with `deeprefine cursor install`). The same workflow is available from any terminal via the `deeprefine` CLI ([`deeprefine-cli` on PyPI](https://pypi.org/project/deeprefine-cli/)).

```
/deeprefine
```

**Typical flow:** `graphify .` → `graphify query "..."` → record the question → `/deeprefine`.

```bash
deeprefine history add --query "your question"   # or let the agent do this
```

That's it. Under `graphify-out/.deeprefine/` you get:

```
graphify-out/
├── graph.json                          updated graph (graphify reads this)
└── .deeprefine/
    ├── history.jsonl                   queries queued for refinement
    ├── refinement_results_*.jsonl      run logs
    └── graph.json.bak                  backup before each refine
```

> **Standalone repo.** Model code (`autorefiner`, `atlas_rag`) lives in a separate [DeepRefine](https://github.com/HKUST-KnowComp/DeepRefine) checkout.  
> `pip install deeprefine-cli` ships the CLI and `SKILL.md`. `deeprefine refine` still needs DeepRefine + `atlastune`, with default inference from your current API model setup; you can override with custom base URL and API key.

---

## News

- [2026/6/2] deeprefine-cli v0.1.4 has been released! Customize your LLM api.

---

## Quick start

| Step | What |
|:----:|------|
| 1 | Install [DeepRefine](https://github.com/HKUST-KnowComp/DeepRefine) in `atlastune` |
| 2 | `pip install deeprefine-cli` |
| 3 | `deeprefine cursor install` in your KB project |
| 4 | (Optional) start local vLLM, or use your API provider |
| 5 | `deeprefine history add` → `deeprefine refine` |

```bash
# 1) DeepRefine (once)
conda activate atlastune
cd /path/to/DeepRefine && pip install -e .

# 2) CLI (once per env)
pip install deeprefine-cli

# 3) Cursor skill (KB project root)
cd /path/to/your-kb-project
deeprefine cursor install

# 4) Optional local vLLM (each session, from DeepRefine repo)
bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-0.6b-emb.sh
bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-8b-vllm-reafiner.sh

# OR use your API provider (no local vLLM)
export DEEPREFINE_LLM_URL=your-llm-endpoint
export DEEPREFINE_EMBED_URL=your-embed-endpoint
export DEEPREFINE_LLM_API_KEY=your_llm_api_key
export DEEPREFINE_EMBED_API_KEY=your_embed_api_key
export DEEPREFINE_MODEL=your_llm_model
export DEEPREFINE_EMBED_MODEL=your_embed_model
# optional (if your provider uses one key for both):
# export DEEPREFINE_API_KEY=your_shared_api_key
# optional model overrides:

# 5) Refine
deeprefine history add --query "your question"
deeprefine refine
```

---

## Pipeline

| Stage | Tool | Input | Output |
|:-----:|------|-------|--------|
| Build | **graphify** | Project files | `graphify-out/graph.json` |
| Query | **graphify** | Questions | `graphify query "..."` |
| Refine | **deeprefine** | Graph + query history | Updated `graph.json`, logs |

```text
  project files
        │
        ▼ graphify
   graph.json ◄────────────────────────┐
        │                              │
        ▼ graphify query               │ deeprefine refine
   (Q&A session)                      │
        │                              │
        ▼ deeprefine history add       │
   history.jsonl ──────────────────────┘
        │
        ▼ graphify query (verify)
```

DeepRefine does not build the graph; it patches `graph.json` so later `graphify query` retrieves better.

---

## Repository layout

```text
DeepRefine-Skill/              ← this repo (PyPI: deeprefine-cli)
├── deeprefine_skill/          ← package (SKILL.md bundled)
└── scripts/deeprefine.py

DeepRefine/                    ← separate clone
├── autorefiner/
├── AutoSchemaKG/
└── scripts/vllm_serve/

your-kb-project/
└── graphify-out/
    ├── graph.json
    └── .deeprefine/           ← history, logs, FAISS cache
```

**Recommended sibling layout** (auto-detects `../DeepRefine` when `DEEPREFINE_REPO` is unset):

```text
www/code/
├── DeepRefine/
└── DeepRefine-Skill/
```

---

## Installation

### 1. DeepRefine (`atlastune`)

See [DeepRefine — Environment](https://github.com/HKUST-KnowComp/DeepRefine#environment).

```bash
conda activate atlastune
cd /path/to/DeepRefine
pip install -e .
```

### 2. CLI

| Method | Command |
|--------|---------|
| **PyPI** (recommended) | `pip install deeprefine-cli` |
| **Source** | `pip install -e /path/to/DeepRefine-Skill` |

```bash
deeprefine --help    # verify
```

### 3. DeepRefine path (optional)

Only if `DeepRefine` is not `../DeepRefine` and not found by walking up from cwd:

```bash
export DEEPREFINE_REPO=/path/to/DeepRefine
```

### 4. Inference

Default: use your API provider from environment.

Optional local vLLM (from the **DeepRefine** repo):

```bash
conda activate atlastune
bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-0.6b-emb.sh
bash /path/to/DeepRefine/scripts/vllm_serve/qwen3-8b-vllm-reafiner.sh
```

| Variable | Default |
|----------|---------|
| `DEEPREFINE_LLM_URL` | *(empty; SDK default endpoint)* |
| `DEEPREFINE_EMBED_URL` | *(empty; SDK default endpoint)* |
| `DEEPREFINE_API_KEY` | fallback to `OPENAI_API_KEY` |
| `DEEPREFINE_LLM_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_EMBED_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_MODEL` | `gpt-4.1-mini` |
| `DEEPREFINE_EMBED_MODEL` | `text-embedding-3-small` |

### 5. Cursor skill

Run at **KB project root** (folder with or that will have `graphify-out/`):

| Command | Scope |
|---------|-------|
| `deeprefine cursor install` | `.cursor/skills/` (this project) |
| `deeprefine cursor install --user` | `~/.cursor/skills/` (all projects) |
| `deeprefine install` | alias for `cursor install` |
| `deeprefine cursor uninstall` | remove skill |

---

## Workflow with graphify

**One-time**

```bash
pip install graphifyy deeprefine-cli    # deeprefine-cli in atlastune

cd /path/to/your-kb-project
graphify cursor install
deeprefine cursor install
```

**Each session** (KB project root)

| # | Action |
|:-:|--------|
| 1 | `graphify .` or `/graphify .` → `graphify-out/graph.json` |
| 2 | `graphify query "..."` |
| 3 | `deeprefine history add --query "..."` |
| 4 | `deeprefine refine` or `/deeprefine` |
| 5 | *(optional)* `graphify query "..."` to verify |

---

## Commands

All commands below run from **KB project root**.

| Command | Description |
|---------|-------------|
| `deeprefine history add --query "..."` | Record a query after graph Q&A |
| `deeprefine history list` | List all history entries |
| `deeprefine history list --pending` | List unrefined queries only |
| `deeprefine refine` | Refine all pending queries |
| `deeprefine refine --query "..."` | Refine one query (also recorded) |
| `deeprefine refine --rebuild-index` | Rebuild FAISS before refine |
| `deeprefine index --rebuild` | Rebuild FAISS cache only |
| `deeprefine cursor install \| uninstall` | Manage Cursor skill |

**Artifacts** (`graphify-out/.deeprefine/`)

| File | Purpose |
|------|---------|
| `history.jsonl` | Query history |
| `refinement_results_*.jsonl` | Refinement logs |
| `graph.json.bak` | Backup before refine |
| `reafiner.pkl` | FAISS index cache |

Cursor agent instructions: [SKILL.md](./SKILL.md) → installed as `.cursor/skills/deeprefine/SKILL.md`.

---

## Where to run what

| What | Where |
|------|-------|
| `pip install deeprefine-cli` | Anywhere (`atlastune` for refine) |
| `pip install -e .../DeepRefine` | DeepRefine repo |
| `graphify` / `deeprefine cursor install` | **KB project root** |
| `deeprefine refine` / `history` | **KB project root** |
| vLLM serve scripts | **DeepRefine repo** |

---

## License

MIT — see [LICENSE](./LICENSE).
