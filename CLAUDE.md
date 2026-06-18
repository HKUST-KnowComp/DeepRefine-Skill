# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Identity

DeepRefine-Skill is an agent skill that refines graphify knowledge graphs using the Reafiner algorithm (8-step state machine: INIT → RETRIEVE → JUDGE → RETRIEVE_KHOP → ABDUCE → REFINE → VALIDATE → APPLY → FINISH). It ships as `deeprefine-cli` on PyPI (v0.1.8) and supports Cursor, Copilot CLI, and Gemini CLI.

## Architecture

The codebase separates framework-agnostic Python logic from framework-specific instruction files.

### Framework-agnostic core (`deeprefine_skill/`)

All Python modules operate on local files (`graph.json`, `loop_trace_*.json`, `history.jsonl`) and are independent of any agent framework. The CLI (`cli.py`) exposes these as subcommands that any agent can invoke via Bash.

| Module | Role |
|--------|------|
| `agent_loop.py` | Trace validation against Reafiner control flow (`validate_trace()`). Defines regex patterns (`JUDGE_RE`, `ABDUCTION_RE`, `REFINEMENT_RE`) for structured output parsing. Contains `reafiner_early_exit()` and `reafiner_needs_refinement()` — the two branching rules from the paper. |
| `agent_graph.py` | Applies refinement actions to `graph.json`. Parses `<refinement>` blocks, executes `insert_edge`/`delete_edge`/`replace_node` via `apply_refinement_text()`. Handles node lookup by label/alias with Unicode normalization. Supports `source_file::label` qualified names. |
| `agent_prompts.py` | Verbatim prompt templates from the DeepRefine paper. Three LLM call types: judgement (`<judge>Yes/No</judge>`), error abduction (`<abduction>...</abduction>`), KG refinement (`<refinement>action|action</refinement>`). Also defines constants: `MAX_HOPS_DEFAULT=4`, `MAX_TRIPLE_NUM_BY_STEP=[5,10,15,20]`, `HISTORY_HORIZON_DEFAULT=4`. |
| `action_review.py` | Evidence-aware dry-run review engine. Parses `<refinement>` actions, audits each against `graph.json` nodes/edges, detects ambiguous bare names, greps source files for code evidence, assigns HIGH/MEDIUM/LOW confidence labels. `cmd_apply` enforces the review gate — refuses LOW-confidence actions without `--allow-low-confidence`. |
| `history.py` | JSONL-based query queue. `sync_history_from_memory()` imports from `graphify-out/memory/query_*.md` frontmatter. `pending_queries()` returns unrefined entries deduped by id. `mark_refined()` sets `refined=true`. Query IDs are SHA256 truncated to 16 hex chars. |
| `cli.py` | CLI entry point. Subcommands: `cursor/copilot/gemini install/uninstall`, `history (add|list|sync-memory)`, `index --rebuild`, `refine [--apply]`, `review`, `apply [--allow-low-confidence]`, `loop (init|validate|finish)`. `apply` requires `--trace-file` and runs both `validate_trace()` and `action_review` gate before touching `graph.json`. |
| `paths.py` | Path resolution. `find_project_root()` walks up for `graphify-out/graph.json`. `graphify_paths()` returns the canonical path dict. `find_deeprefine_repo()` locates the paper repo (needed only for Terminal CLI mode). |
| `installers.py` | Multi-platform skill installers. Supports Cursor (`.cursor/skills/deeprefine/`), Copilot CLI (`.github/skills/deeprefine/`), and Gemini CLI (`gemini extensions link/install` + manual copy fallback). |
| `refine_runner.py` | Terminal CLI mode using FAISS + API/vLLM. Dry-run by default; `--apply` to persist. Not used in agent mode. |
| `adapter_graphify.py` | Graphify data loading + FAISS index. Not used in agent mode. |

### Framework-specific instruction files

| File | Target | Description |
|------|--------|-------------|
| `SKILL.md` / `deeprefine_skill/SKILL.md` | Cursor | YAML frontmatter + Markdown describing the full Reafiner loop with dry-run safety policy. |
| `deeprefine_skill/SKILL_COPILOT.md` | Copilot CLI | Copilot-variant frontmatter (`allowed-tools: shell`, no `disable-model-invocation`), mode detection preamble, dry-run review workflow. Installed via `deeprefine copilot install`. |
| `deeprefine_skill/gemini_extension/` | Gemini CLI | Full extension directory: `gemini-extension.json`, `GEMINI.md`, `commands/*.toml`, `skills/deeprefine/SKILL.md`. Installed via `deeprefine gemini link/install`. |
| `GEMINI.md` | Gemini CLI | Context file loaded by Gemini runtime; describes extension behaviour at a high level. |
| `CLAUDE.md` | Claude Code | This file — project architecture and development guidance. |

### Control flow (agent mode)

```
User: /deeprefine
  → SKILL.md loaded as system instructions
  → Agent runs: deeprefine history sync-memory
  → Agent loads pending queries from history.jsonl
  → For each query:
      deeprefine loop init --query "..."
      Step 1: graphify query → judge → append to loop_trace
      Steps 2..MAX_HOPS: k-hop expand → judge → append
      If len(history)==1 && answerable: early exit → loop finish
      Else: abduction → refinement → loop validate → review → HARD STOP
      (user approval in follow-up message)
      → apply (with action_review evidence gate) → loop finish
```

The `deeprefine apply` command internally calls `validate_trace()` and the `action_review` evidence gate. It refuses LOW-confidence actions unless `--allow-low-confidence` is passed. The `--skip-trace-check` flag bypasses trace validation but not the review gate — SKILL.md explicitly forbids using it.

## Harness Architecture

The runtime harness enforces Reafiner protocol constraints at multiple levels.
Implemented components:

- **Trace validation** (`agent_loop.py`): `validate_trace()` checks that a
  completed `loop_trace_*.json` matches the Reafiner control flow — correct
  step ordering, required fields per step, valid retrieval methods.
- **Evidence audit** (`action_review.py`): Before `deeprefine apply` writes to
  `graph.json`, each proposed refinement action is audited against the live
  graph.  Node existence, edge duplication, ambiguous entity names, and source
  code evidence are checked.  LOW-confidence actions are rejected unless
  `--allow-low-confidence` is passed.

All harness components are framework-agnostic Python — reusable across
platforms without modification.

## Development Commands

```bash
# Install in dev mode
pip install -e .

# Run CLI
deeprefine --help
python scripts/deeprefine.py --help   # without pip install

# Lint (ruff not yet configured in CI)
pip install ruff
ruff check deeprefine_skill/
ruff format --check deeprefine_skill/

# Type check (mypy not yet configured)
pip install mypy
mypy deeprefine_skill/
```

A test suite and CI pipeline are not yet configured.

## Key Constraints

- The prompt templates in `agent_prompts.py` must stay verbatim from the DeepRefine paper. Changing wording changes LLM behaviour and breaks comparability.
- `validate_trace()` is the reference implementation of Reafiner control-flow rules. Any harness mechanism must be consistent with its checks.
- `graph.json` uses either `"links"` or `"edges"` as the key for relationships — `agent_graph.py` handles both.
- The project root is detected by the presence of `graphify-out/graph.json`, not by git or config files.
- Query IDs are `sha256(query.strip())[:16]` — used across `history.py`, `agent_loop.py`, and `cli.py` for dedup and file naming.

## Repository Notes

- `docs/PROJECT-PLAN.md` — technical plan and architecture
- `docs/gemini-cli.md` — Gemini CLI user guide
- `docs/copilot-cli.md` — Copilot CLI user guide
- `scripts/deeprefine.py` — lightweight CLI entry point; delegates to `deeprefine_skill.cli:main`
