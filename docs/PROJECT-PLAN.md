# DeepRefine-Skill: Cross-Platform Agent Skill Project Plan

---

## 1. Project Scope

| Dimension | Description |
|-----------|-------------|
| **Primary Objective** | Port DeepRefine skill from Cursor to GitHub Copilot CLI; harden the agent harness with progressive engineering |
| **Secondary Objective** | Port to Claude Code as a cross-platform comparison target (after Copilot delivery) |
| **Core Deliverable** | A cross-platform agent skill system with unified YAML spec, template-based multi-target emission, and a progressively hardened runtime harness |
| **Original Repository** | [DeepRefine-Skill](https://github.com/HKUST-KnowComp/DeepRefine) |
| **Reference Paper** | [DeepRefine (arXiv:2605.10488)](https://arxiv.org/pdf/2605.10488) |

### Priority & Dependency

| Priority | Track | Description | Depends On |
|----------|-------|-------------|------------|
| **P0** | Copilot CLI Adaptation | Primary deliverable: make `/deeprefine` work on Copilot CLI | Phase 1–2 |
| **P0** | Harness Engineering | Progressive hardening from post-hoc validation to inline enforcement | Phase 1 audit |
| **P1** | Claude Code Adaptation | Learning track + cross-platform comparison data source | Phase 3 Copilot done; may reference classmate's implementation |

> **Decision rationale**: Copilot CLI is the assigned task. Claude Code adaptation is deferred until after Copilot delivery — by that point, classmates' Claude Code work may be available for reference, and the harness will already be mature enough to reuse.

---

## 2. Technical Architecture

### 2.1 Core Insight: Skill and Harness Are Parallel Artefacts

The current SKILL.md describes the Reafiner protocol in natural language for the LLM to follow. The harness enforces the same protocol in code at runtime. They are **not** in a transformation relationship — they are two projections of the same specification, targeting two different executors:

```
                    ┌──────────────────────────┐
                    │   Reafiner Specification   │
                    │   (single source of truth) │
                    │                            │
                    │  • State machine (8 steps) │
                    │  • Prompt templates        │
                    │  • Validation rules        │
                    │  • Tool contracts          │
                    └──────────┬─────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌──────────────────┐              ┌──────────────────┐
   │  Skill Artefact   │              │  Harness Artefact │
   │  (for the LLM)    │              │  (for the runtime)│
   │                   │              │                   │
   │  • Natural lang   │              │  • State machine   │
   │    instructions    │              │    enforcement     │
   │  • Prompt templates│              │  • Output valid.   │
   │  • Step-by-step    │              │  • k-hop expansion │
   │    guidance        │              │  • Action whitelist│
   └────────┬───────────┘              └────────┬──────────┘
            │                                   │
            ▼                                   ▼
   ┌──────────────────┐              ┌──────────────────┐
   │  Agent Framework  │              │  Python Runtime   │
   │  (Copilot / Claude)│◄────────────│  (framework-      │
   │                   │  enforces   │   agnostic)       │
   │  Executes steps   │              │  Validates each   │
   │  Calls tools      │              │  step inline      │
   └──────────────────┘              └──────────────────┘
```

### 2.2 Template-Based Emitter Architecture

Only 2 target platforms (Copilot CLI, Claude Code), both emitting Markdown instruction files. A full compiler with IR layer is over-engineering for N=2. Instead, a YAML spec drives Jinja2 templates directly — Spec → Template → Target.

```
┌─────────────────────────────────────────────────────────────┐
│                Reafiner Skill Specification (YAML)            │
│  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌─────────┐  │
│  │ State    │ │ Prompt       │ │ Validation │ │ Tool    │  │
│  │ Machine  │ │ Templates    │ │ Rules      │ │Contracts│  │
│  │ (8 steps)│ │ (judgement,  │ │ (structural│ │(exec,   │  │
│  │          │ │  abduction,  │ │ + semantic)│ │ read,   │  │
│  │          │ │  refinement) │ │            │ │ write,  │  │
│  │          │ │              │ │            │ │ llm)    │  │
│  └──────────┘ └──────────────┘ └────────────┘ └─────────┘  │
└──────────────┬──────────────────────────┬────────────────────┘
               │                          │
               ▼                          ▼
     ┌─────────────────┐       ┌─────────────────────────┐
     │  Jinja2 Template │       │  Harness Config         │
     │  copilot-        │       │  (FSM guards, output    │
     │  instructions    │       │   gates, k-hop params)  │
     │  .md.j2          │       │   → deeprefine_skill/   │
     └────────┬────────┘       └─────────────────────────┘
              │
              ▼
     ┌─────────────────┐
     │ .github/copilot- │
     │ instructions.md  │
     │ (P0 — primary)   │
     └─────────────────┘

     ┌─────────────────┐
     │  Jinja2 Template │
     │  claude-skill    │
     │  .md.j2          │
     └────────┬────────┘
              ▼
     ┌─────────────────┐
     │ .claude/skills/  │
     │ deeprefine/      │
     │ SKILL.md         │
     │ (P1 — secondary) │
     └─────────────────┘

The same YAML spec also initializes harness configuration — FSM transition tables,
output gate regexes, and k-hop parameters — ensuring the runtime enforcement layer
stays consistent with the instruction files.
```

**Why not a full compiler (Spec → IR → Target)?** With only 2 targets that are both
Markdown, an IR adds abstraction overhead without payoff. A Jinja2 template is ~80
lines of Markdown with `{{ spec.state_machine }}`-style placeholders. Adding a new
platform means writing one template file, not a new IR→Target emitter. The spec
remains the single source of truth — change a rule in one place, regenerate all
targets.

---

## 3. Phased Implementation Plan

### Phase 1: Audit & Baseline (Week 1–3, ~25h)

**Objective**: Understand every line of the current codebase; quantify gaps relative to the DeepRefine paper; identify harness insertion points.

#### 1.1 Environment Setup (4h)
- [ ] Clone the DeepRefine paper repository; understand core logic in `autorefiner/src/reafiner.py`
- [ ] Read the DeepRefine paper (at minimum the Reafiner algorithm section)
- [ ] Run the full graphify → DeepRefine-Skill pipeline locally
- [ ] Understand project data flow: `graph.json` structure, `loop_trace_*.json` schema, `history.jsonl` format

#### 1.2 Code Audit (8h)
- [ ] Produce a module dependency graph
- [ ] Assess test coverage per module (current: ~0%)
- [ ] Identify all bare `print()` → candidate for structured logging
- [ ] Identify all bare `except` → candidate for specific exception handling
- [ ] Document hardcoded paths and assumptions (e.g., `graphify-out/`, `../DeepRefine`)
- [ ] Review prompt consistency between SKILL.md and `agent_prompts.py`
- [ ] **Harness-specific**: map every check in `validate_trace()` to its corresponding insertion point in the 8-step control flow; classify each as "can be inline" vs "must be post-hoc"

#### 1.3 Baseline Measurement (13h)
- [ ] Prepare 20 test queries covering three scenarios: single-hop answerable, multi-hop answerable, unanswerable
- [ ] Execute `/deeprefine` in Cursor for each query; capture full traces
- [ ] Compare traces step-by-step against the paper's Reafiner reference
- [ ] Produce baseline report: per-step compliance rate, common drift types
- [ ] **Harness-specific**: for each drift instance, record whether a harness mechanism (A/B/C) could have prevented it

**Deliverables**:
- `docs/phase1-audit.md` — code audit report, including harness insertion point map
- `docs/phase1-baseline.csv` — 20 queries × per-step compliance data + harness preventability annotation
- `tests/fixtures/` — test graph.json and query set

---

### Phase 2: Harness Engineering & Core Hardening (Week 4–7, ~51h)

**Objective**: Progressively harden the agent loop from post-hoc validation to inline enforcement. This is the core technical contribution.

#### 2.1 Harness Level 0: Post-hoc Validation (baseline — already exists) (2h)

The starting point. `validate_trace()` in `agent_loop.py` already does this. Document it as Level 0.

- [ ] Formalize the current `validate_trace()` as `HarnessLevel0`
- [ ] Write unit tests for all validation rules (~20 cases from 1.3 baseline)
- [ ] Measure: false-positive rate, false-negative rate on baseline traces

**What it does**: Runs after the full loop. Catches errors but cannot prevent them.
**Limitation**: A failed trace means re-running the entire loop — wasted LLM calls.

#### 2.2 Harness Level 1: Structured Output Enforcement (12h)

Move from post-hoc regex matching to real-time output gate.

- [ ] Implement `OutputGate` class:
  ```python
  class OutputGate:
      def check_judge(self, raw: str) -> tuple[bool, str | None]:
          """Returns (passed, error_message). Retry on failure."""
      def check_abduction(self, raw: str) -> tuple[bool, str | None]: ...
      def check_refinement(self, raw: str) -> tuple[bool, str | None]: ...
  ```
- [ ] Integrate into agent loop: after each LLM call, gate checks output before proceeding
  - `<judge>` must match `JUDGE_RE` → if not, retry with same prompt + format reminder
  - `<abduction>` must contain all three perspectives (incompleteness, incorrectness, redundancy)
  - `<refinement>` must pass action whitelist (`insert_edge` / `delete_edge` / `replace_node` only)
- [ ] Implement retry policy: max 3 retries per step, exponential backoff on format errors
- [ ] Unit tests: each gate with valid + invalid inputs (~15 cases)
- [ ] Compare against Level 0 baseline: retry success rate, tokens saved vs full re-run

**Key design decision**: Level 1 only checks *format*, not *semantic correctness*. Semantic validation comes at Level 1.5.

#### 2.2.5 Harness Level 1.5: Semantic Evidence Audit (exists — `action_review.py`) (0h new implementation; document + integrate)

The gap between format correctness (Level 1) and state-machine enforcement (Level 3) is *semantic auditing*: after the LLM generates syntactically-valid `<refinement>` actions, are those actions *grounded in evidence*?

`action_review.py` (356 lines, contributed by ziymeng in PR #1) fills this gap.  It is an evidence-aware refinement action auditor that operates between the REFINE and VALIDATE states.

**Architecture**:

```
<refinement> text
    │
    ▼
parse_refinement_block()          ← split into individual action strings
    │
    ▼
review_action() × N               ← audit each action independently
    │
    ├── 1. Parse action → (fn, args) via _parse_action_string()
    ├── 2. Node lookup: _matching_nodes() resolves entity names against
    │      graph.json's "nodes" list; supports file::qualified_name syntax
    ├── 3. Ambiguity detection: bare names like main(), run(), train()
    │      are flagged as AMBIGUOUS_LABELS → LOW confidence
    ├── 4. Edge existence: _edge_exists() checks if an insert_edge target
    │      already exists in graph.json (duplicate prevention)
    ├── 5. Code evidence grep: _has_code_evidence() opens source files
    │      and regex-verifies claimed relations:
    │      - method/defines:    class Subject ... def Object
    │      - calls/uses:        def Subject ... Object()
    │      - imports/from:      import Object
    └── 6. Confidence assignment (L286-299):
           warnings → LOW
           code evidence | exact edge exists | replacement source → HIGH
           other evidence, no direct proof → MEDIUM
           nothing → LOW + "No direct evidence"
    │
    ▼
ActionReview(action, confidence, evidence, warnings, suggested_replacement)
```

**Two integration points** (in `cli.py`):
- **Explicit**: `deeprefine review` — audits without touching graph.json
- **Implicit gate**: `deeprefine apply` — runs review internally; refuses when LOW-confidence actions detected (hard gate; `--allow-low-confidence` to override)

**What it prevents**: Blind application of hallucinated or ungrounded refinement actions.  An LLM might generate `insert_edge("main()", "calls", "init()")` — syntactically valid, but `main()` matches dozens of nodes across files.  The auditor flags this as LOW confidence and blocks the write.

**Key design insight**: This is an instance of the **"policy sinking" pattern** — moving a constraint from natural-language instruction (SKILL.md FORBIDDEN #4: "Ignore LOW-confidence review warnings") into hard Python enforcement.  The LLM can no longer skip the review step; the harness refuses to proceed without it.

**Relationship to other levels**:
- Level 1 ensures `<refinement>insert_edge(...)|...</refinement>` is syntactically valid
- Level 1.5 ensures the **content** inside that valid syntax is evidence-backed
- Level 3 ensures the state machine transitions are legal (REFINE → VALIDATE → APPLY)

**Abbreviated analysis in Section 4 summary table**.

#### 2.3 Harness Level 2: Deterministic k-hop Expansion (8h)

Remove LLM discretion from entity expansion. k-hop should be a deterministic graph operation.

- [ ] Implement `KHopExpander` in `agent_loop.py`:
  ```python
  class KHopExpander:
      def __init__(self, graph: dict):
          self.adj = self._build_adjacency(graph)
      
      def expand(self, entities: list[str], hop: int = 1) -> list[dict]:
          """BFS from entities, return triples within `hop` distance."""
  ```
- [ ] For step ≥ 2: extract entities from previous step's triples → `expander.expand(entities)` → return triples
- [ ] No longer prompt the LLM to "decide which entities to expand from"
- [ ] Unit tests: known graph → verify expansion output (~10 cases)
- [ ] Integration test: run 10 queries, verify every step ≥ 2 uses k-hop (trace `retrieval.method`)

**Key design decision**: The LLM still does judgement on the expanded triples. We're only removing its discretion over *which entities to retrieve*.

#### 2.4 Harness Level 3: State Machine Enforcement (15h)

The highest level: hard-code the Reafiner state machine with inline validation gates at every transition.

- [ ] Define the formal state machine (JSON Schema):
  ```
  states: [INIT, RETRIEVE, JUDGE, RETRIEVE_KHOP, ABDUCE, REFINE, VALIDATE, APPLY, FINISH]
  transitions:
    INIT → RETRIEVE:          always
    RETRIEVE → JUDGE:         always
    JUDGE → RETRIEVE_KHOP:    guard: answerable == False AND step < MAX_HOPS
    JUDGE → FINISH:           guard: answerable == True
    RETRIEVE_KHOP → JUDGE:    always
    JUDGE → ABDUCE:           guard: len(history) > 1 (after loop exit)
    ABDUCE → REFINE:          always
    REFINE → VALIDATE:        always
    VALIDATE → APPLY:         guard: validation passed
    APPLY → FINISH:           always
  ```
- [ ] Implement `StateMachine` class that:
  - Defines allowed transitions
  - Before each transition, runs guard condition
  - On guard failure → returns **actionable error message** (not just "invalid transition"):
    - Names the current state and expected next state
    - Suggests the exact CLI command to proceed
    - Example: `FSM guard: expected state JUDGE, got ABDUCE. Next valid action: run judgement and record <judge> tag. Query current state: deeprefine loop state --trace-file loop_trace_xxx.json`
  - After each transition, runs post-condition check
- [ ] Implement `deeprefine loop state --trace-file ...` — queries FSM for current state + valid next actions
- [ ] Implement `deeprefine loop next --trace-file ...` — returns the exact next step the LLM should execute (reduces decision burden on the LLM)
- [ ] Three-layer defense for FSM compliance in CLI agents:
  1. **Instruction layer**: mirror all FSM rules in the platform instruction file (`.github/copilot-instructions.md`) so the LLM knows constraints before acting
  2. **Assist layer**: `loop next` command tells the LLM what to do — it doesn't need to track state
  3. **Enforce layer**: Python FSM guards as final backstop; reject illegal transitions with actionable errors
- [ ] Copilot CLI error-recovery test: deliberately violate FSM, verify Copilot can read error message and correct course
- [ ] Integrate Level 1 gates as pre-transition checks
- [ ] Integrate Level 2 k-hop as the RETRIEVE_KHOP implementation
- [ ] Unit tests: all valid paths + invalid transition attempts (~25 cases)
- [ ] Functional tests: run 20 queries through the state machine, verify zero protocol violations

#### 2.5 Unified Specification & Template-Based Emitter (6h)

With the harness mature, design the single-source-of-truth YAML spec and Jinja2 templates for target platform emission. No IR layer — with only 2 Markdown targets, templates are simpler and sufficient.

- [ ] Define Specification Schema (YAML):
  ```yaml
  spec_version: 1
  state_machine: { ... }      # from Level 3
  prompts:
    judgement: { system: ..., user_template: ... }
    abduction: { system: ..., user_template: ... }
    refinement: { system: ..., user_template: ... }
  validation_rules:           # from Level 0-3
    output_gates: [ ... ]
    state_guards: [ ... ]
    post_conditions: [ ... ]
  tool_contract:
    commands: [graphify, deeprefine, ...]
    file_reads: [graph.json, loop_trace_*.json, ...]
    file_writes: [loop_trace_*.json, refinement_actions_*.txt]
  forbidden:
    - "Never use --skip-trace-check"
    - ...
  ```
- [ ] Implement `SpecLoader`: YAML file → Python dict (lightweight, ~50 lines)
- [ ] Write Jinja2 template: `templates/copilot-instructions.md.j2` (~80 lines)
  - Renders state machine rules, prompt templates, forbidden rules, step-by-step protocol
  - Uses `{{ spec.state_machine }}`-style placeholders — no intermediate IR
- [ ] Write Jinja2 template: `templates/claude-skill.md.j2` (~80 lines)
  - Same spec, different Markdown layout for Claude Code conventions
- [ ] Implement `deeprefine compile --target copilot|claude` CLI subcommand
  - Loads YAML spec → renders template → writes target file
- [ ] The same YAML spec initializes harness config: FSM transition table, output gate regexes, k-hop parameters
- [ ] Unit tests: spec loads without schema errors; template renders valid Markdown; regenerated output matches snapshot
- [ ] **Design constraint**: adding a new framework target = writing one ~80-line Jinja2 template. No Python code changes needed.

#### 2.6 Test Suite Construction (8h)

- [ ] Unit tests: `test_agent_loop.py` (trace validation + state machine, ~25 cases)
- [ ] Unit tests: `test_output_gates.py` (format enforcement, ~15 cases)
- [ ] Unit tests: `test_khop.py` (expansion correctness, ~10 cases)
- [ ] Unit tests: `test_history.py` (CRUD + mark_refined, ~10 cases)
- [ ] Integration tests: `test_tool_contract.py`
- [ ] Functional tests: `test_e2e_harness.py` (harness catches known drift patterns from baseline)
- [ ] Target coverage: core modules ≥80%, overall ≥60%

**Deliverables**:
- `deeprefine_skill/harness/` — Levels 0–3 implementation
- `deeprefine_skill/spec/` — unified YAML specification
- `templates/` — Jinja2 templates (Copilot + Claude emitters)
- `tests/` — complete test suite
- `.github/workflows/ci.yml` — CI skeleton

---

### Phase 3: Multi-Platform Deployment (Week 8–10, ~41h)

**Objective**: Deliver working `/deeprefine` on Copilot CLI (P0), then Claude Code (P1).

#### 3.1 Copilot CLI Adapter — P0 (25h)

- [ ] Research Copilot CLI instruction format, capability boundaries, and tool-use model
  - Document: what tools are available? how are instructions injected? any hook system?
  - Produce a capability matrix: Copilot CLI vs Cursor vs Claude Code
- [ ] Run `deeprefine compile --target copilot` to emit initial `.github/copilot-instructions.md`
- [ ] Hand-polish the emitted instructions for Copilot CLI-specific constraints
- [ ] End-to-end test suite:
  - [ ] Normal flow: hop1 No → hop2 Yes → abduction → refinement → apply
  - [ ] Early-exit flow: hop1 Yes → early exit
  - [ ] Multi-hop all-No: hop1–4 all No → abduction → refinement
  - [ ] Edge cases: missing graph.json, malformed refinement output, empty query, non-English query
  - [ ] Queue behaviour: multiple pending queries processed sequentially
- [ ] For each test case, capture full trace + compare against baseline
- [ ] If Copilot CLI lacks specific capabilities (hooks, fine-grained tool control), document as framework capability gaps
- [ ] Write Copilot CLI user guide (`docs/copilot-cli-guide.md`)

#### 3.2 Claude Code Adapter — P1 (12h)

> **Prerequisite**: Copilot CLI adapter delivered. Classmates' Claude Code implementation may be available for reference.

- [ ] Study Claude Code skill system: SKILL.md format, settings.json hooks, allowed-tools declaration
- [ ] Run `deeprefine compile --target claude` to emit initial `.claude/skills/deeprefine/SKILL.md` + `.claude/settings.json`
- [ ] Configure hooks:
  - `PreToolUse` → enforce backup before `deeprefine apply`
  - `PostToolUse` → auto-write audit log after `deeprefine apply`
- [ ] End-to-end test: same test cases as Copilot CLI
- [ ] Step-by-step trace comparison with Copilot CLI; annotate divergence sources

#### 3.3 Cross-Platform Observational Comparison (4h)

> **Scope note**: This is a best-effort observational comparison, not a rigorous root-cause analysis. Both Copilot CLI and Claude Code are black-box systems (prompt injection, model behaviour, tool-use handling are not fully visible). Attributing divergence to specific causes requires controlled experiments beyond the project budget. The goal is to document what differs, not to definitively explain why.

- [ ] Run the same 20-query suite on both Copilot CLI and Claude Code
- [ ] Capture full traces for each query on each platform
- [ ] Produce quantitative divergence summary:
  - Per-step answerable agreement rate (do both platforms agree Yes/No on each hop?)
  - Refinement action count comparison (does one platform produce more/fewer actions?)
  - Number of queries where final outcome differs (early-exit vs refinement vs failure)
- [ ] High-level annotation of observed differences (e.g., "Copilot tended to answer No more often on hop 1", "Claude Code produced longer abduction text")
- [ ] Where a divergence clearly maps to a known framework limitation (e.g., tool unavailable), note it. Otherwise, mark as "unattributed — likely model or prompt-injection difference"
- [ ] Produce a concise divergence report (`docs/cross-platform-divergence.md`)

**Deliverables**:
- `.github/copilot-instructions.md` (P0 — primary)
- `.claude/skills/deeprefine/SKILL.md` + `.claude/settings.json` (P1)
- `docs/copilot-cli-guide.md`
- `docs/cross-platform-divergence.md`

---

### Phase 4: CI/CD, Documentation & Release (Week 11–13, ~25h)

**Objective**: Make the project understandable, usable, extensible, and CI-verified.

#### 4.1 CI/CD Pipeline (8h)
- [ ] `.github/workflows/ci.yml`:
  ```yaml
  on: [push, pull_request]
  jobs:
    lint:        ruff check + ruff format --check
    type:        mypy deeprefine_skill/
    unit:        pytest tests/unit/ -v --cov
    integration: pytest tests/integration/ -v
    functional:  pytest tests/functional/ -v  # requires graphify environment
  ```
- [ ] `.github/workflows/publish.yml`: tag push → build → PyPI publish
- [ ] pre-commit hooks: ruff + mypy

#### 4.2 Documentation (9h)
- [ ] Rewrite `README.md`:
  - Quick start (Copilot CLI users) — primary
  - Quick start (Claude Code users) — secondary
  - Harness architecture overview
  - Guide for adding new framework targets
- [ ] `CONTRIBUTING.md`: dev environment setup, running tests, PR process
- [ ] API docs: public interfaces of `deeprefine-core` (docstrings + mkdocs or sphinx)

#### 4.3 Packaging & Release (3h)
- [ ] `pyproject.toml` extras:
  ```toml
  [project.optional-dependencies]
  copilot = []
  claude = []
  dev = ["pytest", "pytest-cov", "ruff", "mypy", "pre-commit"]
  ```
- [ ] Publish release v0.2.0 to PyPI
- [ ] Add PyPI badge + CI badge to README

#### 4.4 Thesis (5h)
- [ ] Structure:
  1. Introduction — agent skills as a new software artefact; the gap between natural-language protocols and reliable execution
  2. Background — Reafiner algorithm, graphify, current SKILL.md limitations
  3. Approach — progressive harness engineering (Levels 0–3), unified spec, template-based emission
  4. Implementation — Copilot CLI adapter (primary), Claude Code adapter (secondary)
  5. Evaluation — harness level ablation study, cross-platform divergence analysis
  6. Discussion — how much control to take from the LLM; framework capability gaps; lessons for agent-skill engineering

**Deliverables**:
- CI/CD pipeline (green check)
- Full documentation
- PyPI release v0.2.0
- Final thesis

---

## 4. Harness Engineering Summary

This is the core technical narrative of the project:

| Level | Name | What It Does | Prevents | Status |
|-------|------|-------------|----------|--------|
| **0** | Post-hoc Validation | `validate_trace()` after full loop | Silent acceptance of bad traces | Exists in `agent_loop.py` |
| **1** | Structured Output Enforcement | Real-time regex gate on each LLM output; retry on mismatch | Format errors in `<judge>`, `<abduction>`, `<refinement>` | Phase 2.2 |
| **1.5** | Semantic Evidence Audit | Per-action evidence check: node existence, ambiguity detection, code grep, duplicate prevention; hard gate in `apply` | Hallucinated entities, ambiguous bare names, duplicate edges, ungrounded relations | Exists in `action_review.py` (PR #1) |
| **2** | Deterministic k-hop Expansion | BFS from Python, not LLM discretion | Entity selection errors, missed neighbours | Phase 2.3 |
| **3** | State Machine Enforcement | Hard transitions with guard conditions; inline checkpoints | Step skipping, order violation, early-exit logic errors | Phase 2.4 |

Each level builds on the previous and incrementally reduces the LLM's degrees of freedom.  Levels 0, 1.5 are already implemented; Levels 1, 2, 3 remain to be built.  All levels can be toggled for ablation studies (thesis Chapter 5).

---

## 5. Platform Adaptation Methodology

This section documents an observed methodological difference between two
adaptation approaches, discovered during Phase 1 code audit of upstream
contributions.

### 5.1 Two Adaptation Strategies

The DeepRefine skill has been adapted to two platforms through two distinct
engineering strategies:

| Dimension | Copilot CLI (our work) | Gemini CLI (ziymeng, PR #2) |
|-----------|----------------------|---------------------------|
| **Strategy** | Content adapter | Platform-native extension |
| **Deliverable** | 1 Markdown file (`SKILL_COPILOT.md`) | Extension directory tree (manifest + context file + command TOMLs + skill SKILL.md) |
| **Command registration** | Implicit (description-based auto-match) | Explicit (`commands/*.toml` with prompt templates) |
| **Pre-execution hooks** | None (LLM reads SKILL.md and runs commands sequentially) | `!{...}` shell injection in TOML prompt — runs `history sync-memory`, `find` before LLM sees context |
| **Install methods** | 1: copy file | 3: `link` (symlink via Gemini manager), `install` (copy via Gemini manager), `copy-only` (manual fallback) |
| **Multi-command support** | Simulated via natural-language mode detection preamble in SKILL.md | Native via 3 TOML-defined slash commands (`/deeprefine`, `/deeprefine:review`, `/deeprefine:apply`) |

### 5.2 Key Insight: Pre-Execution Context Injection

The Gemini CLI TOML `prompt` field supports `!{shell command}` blocks that
execute **before** the LLM receives the conversation context.  This means
discovery commands (`deeprefine history sync-memory`, `find graphify-out`,
`deeprefine history list --pending`) are pre-run and their output injected into
the initial context — the LLM never has to remember to run them.

For platforms without native pre-execution hooks (Copilot CLI), we simulate
this with a **mode detection preamble** in `SKILL_COPILOT.md` that instructs
the LLM to run discovery commands first and switch behaviour based on user
intent keywords.

### 5.3 "Policy Sinking" as a General Principle

Both the dry-run review system (PR #1) and our harness roadmap (Phase 2)
exemplify the same design pattern: **moving constraints from natural-language
instructions into hard Python enforcement**.

```
Natural-language rule          →    Python enforcement
──────────────────────────────────────────────────────────
"Do NOT call apply before        →   cmd_apply runs review
 review" (SKILL.md FORBIDDEN #3)     internally; refuses LOW
                                     confidence

"Ignore LOW-confidence review    →   --allow-low-confidence
 warnings" (FORBIDDEN #4)             flag required to bypass

"Run deeprefine loop validate    →   validate_trace() called
 before apply" (FORBIDDEN #2)         inside cmd_apply before
                                      touching graph.json
```

The pattern: every NL rule in the FORBIDDEN list should have a corresponding
Python gate.  The NL rule is the *specification*; the Python gate is the
*enforcement*.  This is the through-line connecting Phase 2.2–2.4.

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Copilot CLI skill system too immature for full adapter | Medium | Medium | Document as capability gap (valid finding); focus harness contribution as primary deliverable |
| Copilot CLI lacks hook/fine-grained-tool-control support | Medium | Medium | Harness runs as Python layer independent of framework; still validates post-hoc even if inline hooks are unavailable |
| State machine is too rigid — legitimate LLM variations get blocked | Medium | Medium | Tune guard strictness with a "strict/lenient" mode; log all rejections for analysis |
| Claude Code skill/hook behaviour diverges from documentation | Low | Medium | Smoke-test at start of Phase 3.2 before deep investment |
| 20-query baseline data insufficiently significant | Medium | Low | Expand to 30 queries + 3 KG domains |
| DeepRefine repository dependencies too heavy (conda/vLLM/FAISS) | High | Low | Baseline uses SKILL.md agent mode (zero extra deps); CLI mode not required |

---

## 7. Milestone Timeline

```
Week 1  ██ Environment setup + paper deep-read
Week 2  ██ Code audit complete (incl. harness insertion point map)
Week 3  ██ Baseline data collection + harness preventability analysis → D1
────────── Phase 1 complete ──────────

Week 4  ██ Harness Level 1 (output gates) + Level 2 (k-hop)
Week 5  ██ Harness Level 3 (state machine) implementation
Week 6  ██ Unified spec design + template-based emitter implementation
Week 7  ██ Test suite completion + CI skeleton → D2
────────── Phase 2 complete ──────────

Week 8  ██ Copilot CLI research + adapter scaffolding
Week 9  ██ Copilot CLI end-to-end passing
Week 10 ██ Claude Code adapter + cross-platform verification → D3+D4
────────── Phase 3 complete ──────────

Week 11 ██ CI/CD + documentation
Week 12 ██ Thesis + packaging
Week 13 ██ Final revisions + release v0.2.0 → D5+D6
────────── Phase 4 complete ──────────
```
