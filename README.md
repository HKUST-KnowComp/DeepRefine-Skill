<div align="center">

# DeepRefine-Skill

<table style="border: none; margin: 0 auto; padding: 0; border-collapse: collapse;">
<tr>
<td align="center" style="vertical-align: middle; padding: 10px; border: none; width: 250px;">
  <img src="./assets/icons3.png" alt="DeepRefine Logo" width="200" style="margin: 0; padding: 0; display: block;"/>
</td>
<td align="left" style="vertical-align: middle; padding: 10px 0 10px 30px; border: none;">
  <pre style="font-family: 'Courier New', monospace; font-size: 16px; color: #0EA5E9; margin: 0; padding: 0; text-shadow: 0 0 10px #0EA5E9, 0 0 20px rgba(14,165,233,0.5); line-height: 1.2; transform: skew(-1deg, 0deg); display: block;">██████╗ ███████╗███████╗██████╗ ██████╗ ███████╗███████╗██╗███╗   ██╗███████╗
██╔══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║████╗  ██║██╔════╝
██║  ██║█████╗  █████╗  ██████╔╝██████╔╝█████╗  █████╗  ██║██╔██╗ ██║█████╗  
██║  ██║██╔══╝  ██╔══╝  ██╔═══╝ ██╔══██╗██╔══╝  ██╔══╝  ██║██║╚██╗██║██╔══╝  
██████╔╝███████╗███████╗██║     ██║  ██║███████╗██║     ██║██║ ╚████║███████╗
╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═══╝╚══════╝</pre>
</td>
</tr>
</table>

[![PyPi](https://img.shields.io/badge/PyPi-v0.1.8-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.8/)
[![Python](https://img.shields.io/badge/Python-3.10,3.11,3.12-blue.svg)](https://pypi.org/project/deeprefine-cli/0.1.8/)
[![Paper](https://img.shields.io/badge/Paper-DeepRefine-b31b1b.svg)](https://arxiv.org/pdf/2605.10488)
[![Project](https://img.shields.io/badge/Project-DeepRefine-green.svg)](https://github.com/HKUST-KnowComp/DeepRefine)

</div>

DeepRefine-Skill plugs into agent workflows and use a single command `/deeprefine` in your agent CLI to refine and evolve your LLM-Wiki (e.g., **[graphify](https://github.com/safishamsi/graphify)**) knowledge base.

```bash
/deeprefine
```

It refines your graphify knowledge graph for better future retrieval and Q&A quality.

Supported agent frameworks:

<p>
  <a href="https://cursor.com" title="Cursor"><img src="./assets/cursor_CUBE_25D.png" alt="Cursor" height="40"/></a>&nbsp;&nbsp;
  <a href="https://github.com/google-gemini/gemini-cli" title="Gemini CLI"><img src="./assets/gemini-cli-icon_full-color@4x.png" alt="Gemini CLI" height="40"/></a>
</p>

---

## News
- **[2026/6/18] unreleased** - Gemini CLI supported.
- **[2026/6/17] unreleased** - Added dry-run-first refinement, evidence-aware action review, ambiguous-node warnings, and LOW-confidence apply guard.
- **[2026/6/15] v0.1.8** - Aligned interaction memory with LLM-Wiki (graphify) and fixed the single query refinement issue.
- **[2026/6/2] v0.1.7** — Cursor skill + `deeprefine refine` with configurable API. And strict DeepRefine agent loop.

## Agent CLI (Recommended)

This is the default mode and the main workflow for this project.

### One-time setup

```bash
pip install deeprefine-cli graphifyy

cd /path/to/your-kb-project
graphify cursor install

# for Cursor
deeprefine cursor install
# for Gemini CLI
deeprefine gemini install # or deeprefine gemini link
```

After upgrading the package, run the command again to refresh local skill files.

### Typical session (Agent CLI)

```bash
/graphify .
/graphify ./ --wiki
/graphify query "your question 1"
/graphify query "your question 2"
# ..
/deeprefine
```

### What `/deeprefine` does now (default queue behavior)
<details>
<summary><strong>Procedures:</strong></summary>

When you run `/deeprefine`, it should follow this order:

1. `deeprefine history sync-memory`
   - import queries from `graphify-out/memory/query_*.md`
   - write to `graphify-out/.deeprefine/history.jsonl`
2. load pending queries from `history.jsonl` (`refined != true`)
3. refine pending queries sequentially
4. for refinement-path queries, generate `<refinement>` actions and run `deeprefine review`
5. stop in dry-run mode and show the review report; do **not** modify `graph.json` yet
6. only after user approval, run `deeprefine apply` and then `deeprefine loop finish`

</details>

### Agent artifacts

```text
graphify-out/
├── graph.json                              # graphify main graph; unchanged until apply approval
├── memory/
│   └── query_*.md                          # graphify query logs (sync source)
└── .deeprefine/
    ├── history.jsonl                       # DeepRefine-maintained history queue
    ├── graph.json.bak                      # backup before first apply in this run
    ├── loop_trace_<query_id>.json          # per-query loop audit trace
    ├── refinement_results_<YYYYMMDD>.jsonl # per-day run log
    ├── refinement_actions_*.txt            # optional; only when refinement path is taken
    ├── proposed_refinement_actions_*.txt    # CLI dry-run proposed actions
    ├── proposed_refinement_review_*.md      # evidence-aware review report
    └── proposed_refinement_review_*.json    # optional structured review report
```

### Agent-related commands

Run from your KB project root.

| Command | Description |
|---------|-------------|
| `deeprefine cursor install` | Install `/deeprefine` skill into current project |
| `deeprefine cursor install --user` | Install skill for all projects (`~/.cursor/skills/`) |
| `deeprefine gemini path` | Print the extension root used for Gemini CLI |
| `deeprefine gemini link` | Link the current source checkout with `gemini extensions link` |
| `deeprefine gemini install` | Install the bundled extension with `gemini extensions install` |
| `deeprefine gemini install --copy-only` | Manual fallback copy to `~/.gemini/extensions/deeprefine-skill` |
| `deeprefine gemini uninstall` | Remove the extension with Gemini CLI's manager |
| `deeprefine history sync-memory` | Import `graphify-out/memory/query_*.md` into DeepRefine history |
| `deeprefine history list --pending` | Show unrefined queue |
| `deeprefine loop init --query "..."` | Create `loop_trace_<id>.json` template |
| `deeprefine loop validate --trace-file T` | Validate trace against Reafiner control flow |
| `deeprefine review --trace-file T --refinement-file F` | Review proposed actions with HIGH/MEDIUM/LOW evidence labels; no graph write |
| `deeprefine apply --trace-file T --refinement-file F` | Apply `<refinement>` actions to `graph.json` after approval; refuses LOW by default |
| `deeprefine apply --allow-low-confidence --trace-file T --refinement-file F` | Override LOW-confidence guard explicitly |
| `deeprefine loop finish --trace-file T [--refinement-file F]` | Persist results and mark history refined |

### Evidence-aware review and safe apply

`/deeprefine` should default to dry-run-first behavior. Proposed actions are reviewed before they can modify `graphify-out/graph.json`. Each action is labeled:

| Label | Meaning |
|-------|---------|
| `HIGH` | Direct graph or code evidence exists. |
| `MEDIUM` | k-hop context supports the action, but direct code or exact-edge evidence is missing. |
| `LOW` | Node names are ambiguous, too broad, cross-community, or cannot be grounded in `graph.json`. |

Bare function names such as `main()`, `run()`, `train()`, `test()`, and `setup()` are treated as ambiguous. Prefer file-qualified names:

```text
BAD:  insert_edge("main()", "calls", "Trainer")
GOOD: insert_edge("pretraining/pretraining_CLIP_fine-grained.py::main()", "calls", "Trainer")
```

`deeprefine apply` refuses LOW-confidence actions by default. Use `--allow-low-confidence` only when the user explicitly accepts the risk.

---

## Gemini CLI Integration

<details>
<summary><strong>Setup, commands, and session usage</strong></summary>

DeepRefine can also be used as a Gemini CLI extension. This keeps the same safe,
dry-run-first DeepRefine workflow while making `/deeprefine` available inside
Gemini CLI.

### One-time setup for local development

```bash
cd /path/to/DeepRefine-Skill
pip install -e .
deeprefine gemini link
```

`deeprefine gemini link` calls Gemini CLI's official extension manager:

```bash
gemini extensions link /path/to/DeepRefine-Skill
```

Restart Gemini CLI after linking. Then check:

```text
/extensions list
/commands list
```

Expected commands:

```text
/deeprefine
/deeprefine:review
/deeprefine:apply
```

### Gemini CLI commands

| Command | Description |
|---------|-------------|
| `deeprefine gemini path` | Print the extension root used for Gemini CLI |
| `deeprefine gemini link` | Link the current source checkout with `gemini extensions link` |
| `deeprefine gemini install` | Install the bundled extension with `gemini extensions install` |
| `deeprefine gemini install --copy-only` | Manual fallback copy to `~/.gemini/extensions/deeprefine-skill` |
| `deeprefine gemini uninstall` | Remove the extension with Gemini CLI's manager |

For normal source development, prefer `deeprefine gemini link`. It makes the
extension visible to `/extensions list`, whereas copying files alone may not
register the extension in newer Gemini CLI versions.

### Gemini CLI session

```bash
gemini
```

Then run:

```text
/deeprefine
/deeprefine:review "Why is the graph missing the data loading path?"
/deeprefine:apply "Apply the approved refinement actions from the valid trace."
```

The extension files are located at the repository root and are also bundled under
`deeprefine_skill/gemini_extension/` for wheel installs. See
[`docs/gemini-cli.md`](docs/gemini-cli.md) for details.

</details>

---

## Terminal CLI (FAISS + API/vLLM)

<details>
<summary><strong>Requirements, environment, workflow, and commands</strong></summary>

Use this section when you want a pure terminal workflow without Cursor `/deeprefine`.

### Extra requirements

- DeepRefine repository installed in `atlastune`
- Inference backend configured (API or vLLM)

```bash
conda activate atlastune
cd /path/to/DeepRefine && pip install -e .
pip install deeprefine-cli

# Optional, if DeepRefine repo is elsewhere
export DEEPREFINE_REPO=/path/to/DeepRefine
```

### Inference environment (CLI mode)

| Variable | Default |
|----------|---------|
| `DEEPREFINE_LLM_URL` | *(empty; SDK default)* |
| `DEEPREFINE_EMBED_URL` | *(empty; SDK default)* |
| `DEEPREFINE_API_KEY` | fallback to `OPENAI_API_KEY` |
| `DEEPREFINE_LLM_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_EMBED_API_KEY` | fallback to `DEEPREFINE_API_KEY` |
| `DEEPREFINE_MODEL` | `gpt-4.1-mini` |
| `DEEPREFINE_EMBED_MODEL` | `text-embedding-3-small` |

### Terminal workflow

```bash
cd /path/to/your-kb-project

# Option A: import from graphify memory first (recommended)
deeprefine history sync-memory
deeprefine history list --pending
deeprefine refine          # dry-run: proposed actions + review, no graph write
deeprefine refine --apply  # optional: write accepted CLI refine changes

# Option B: add one explicit query
deeprefine history add --query "your question"
deeprefine refine          # dry-run by default
```

### Terminal commands

| Command | Description |
|---------|-------------|
| `deeprefine history add --query "..."` | Append one query to history |
| `deeprefine history list` | List all history rows |
| `deeprefine history sync-memory` | Import graphify memory queries into history |
| `deeprefine history list --pending` | List only unrefined queries |
| `deeprefine refine` | Generate proposed actions for all pending queries; dry-run by default |
| `deeprefine refine --query "..."` | Generate proposed actions for a single query; dry-run by default |
| `deeprefine refine --apply` | Persist accepted CLI refine changes to `graph.json` |
| `deeprefine refine --rebuild-index` | Rebuild FAISS before refine |
| `deeprefine index --rebuild` | Rebuild FAISS cache only |



## Installation

| Method | Command |
|--------|---------|
| **PyPI** | `pip install deeprefine-cli==0.1.8` |
| **Source** | `pip install -e /path/to/DeepRefine-Skill` |

```bash
deeprefine --help
# Expect: cursor, gemini, history, index, refine, review, apply, loop
```
</details>

---

## License

MIT — see [LICENSE](./LICENSE).
