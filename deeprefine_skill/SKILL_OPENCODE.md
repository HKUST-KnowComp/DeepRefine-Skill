---
name: deeprefine
description: "Agent-native DeepRefine Reafiner loop for Graphify knowledge graphs with 6 OpenCode-native optimizations — parallel query processing, phase-specific model routing, structured progress tracking, 5-oracle parallel review, post-apply verification, and evidence ledger."
---

# DeepRefine — Agent Reafiner loop (OpenCode optimized)

## Default safety policy: dry-run only

A normal `/deeprefine` invocation **MUST NEVER** call `deeprefine apply`.

The default `/deeprefine` workflow must stop after:

1. `deeprefine loop validate`
2. `deeprefine review` (including 5-oracle parallel audit)
3. showing the proposed actions and HIGH/MEDIUM/LOW review report to the user

Then ask the user for explicit approval.

Only if the user's **next message** explicitly says to approve/apply/write the graph may you run:

```bash
deeprefine apply --trace-file ... --refinement-file ...
deeprefine loop finish --trace-file ... --refinement-file ...
```

Do not treat generation of `<refinement>` actions as approval. Do not treat a valid trace as approval. Do not apply in the same `/deeprefine` turn.

---

## OpenCode-native optimizations (what's different from Cursor)

This harness leverages 6 OpenCode platform capabilities unavailable in Cursor or Cline:

| # | Optimization | OpenCode Capability | Impact |
|---|-------------|---------------------|--------|
| 1 | **Parallel query processing** | `task()` subagent fan-out | N queries complete in ~1 query's wall-clock time |
| 2 | **Phase-specific model routing** | env-var model selection | Cheap model for binary judgement; strong model for abduction/refinement |
| 3 | **Structured progress tracking** | `todowrite()` | Real-time progress; agent resumes from last completed phase |
| 4 | **5-Oracle parallel review** | `task(subagent_type="general")` × 5 | Orthogonal quality audit — all 5 must APPROVE before apply |
| 5 | **Post-apply auto-verification** | graphify re-query after apply | Confirms the graph mutation actually fixed the issue |
| 6 | **Evidence ledger** | JSONL append to disk | Full audit trail: every phase with timestamp, artifacts, QA results |

---

You **MUST** implement the **same control flow** as `Reafiner.refine()` in DeepRefine (`autorefiner/src/reafiner.py`).

| Component | Agent mode | CLI `deeprefine refine` |
|-----------|------------|-------------------------|
| Retrieval | `graphify query` + k-hop from `graph.json` | FAISS retriever |
| LLM | **OpenCode session model** (routed per phase) | External API / vLLM |
| Graph writes | Dry-run proposal + `deeprefine review` + 5-Oracle audit; `deeprefine apply` only after user approval | Dry-run by default; `--apply` persists |

---

## Model routing

OpenCode supports per-phase model selection via environment variables:

- **Judgement phase** (`<judge>Yes|No</judge>`): Set `$DEEPREFINE_JUDGE_MODEL` — preference for fast, cheap models (e.g., `gpt-4o-mini`, `claude-haiku`). Binary classification doesn't need frontier intelligence.
- **Abduction + Refinement phase**: Set `$DEEPREFINE_REFINE_MODEL` — preference for strong reasoning models (e.g., `claude-opus`, `gpt-4o`, `deepseek-v3`). Complex causal reasoning about graph structure errors.

If either env var is unset, the session default model is used.

When invoking LLM calls in the workflow, prefer the phase-appropriate model. The `/deeprefine-*` commands bind `${DEEPREFINE_REFINE_MODEL}` by default; override per-command with env vars.

---

## FORBIDDEN (hard stop)

Do **NOT**:

1. Run `deeprefine refine` (unless the user explicitly asks for CLI/FAISS mode).
2. Call `deeprefine apply` without a valid `loop_trace_<query_id>.json` (CLI will reject).
3. Call `deeprefine apply` before running `deeprefine review` + 5-Oracle audit and receiving explicit user approval.
4. Call `deeprefine apply` before all 5 Oracle subagents return APPROVE (or user explicitly overrides).
5. Ignore LOW-confidence review warnings unless the user explicitly requests `--allow-low-confidence`.
6. Skip any hop's `<judge>Yes</judge>` / `<judge>No</judge>` judgement.
7. Skip error abduction when `len(interaction_history) > 1`.
8. Write `<refinement>` before abduction when refinement is required.
9. Hand-edit `graph.json` with Python or ad-hoc JSON patches.
10. Ignore pending history and refine only one latest query when unrefined queries already exist.
11. Invent a shorter pipeline ("read file → write refinement → apply").
12. Apply actions without first writing evidence to the ledger.
13. Skip post-apply verification after apply.

If validation fails, **fix the trace and re-run the missing step** — do not bypass with `--skip-trace-check`.

---

## Constants (match `refine_runner.py` / Reafiner)

```text
MAX_HOPS = 4
INCREMENT_HOP = 1
BASE_TOP_K = 10
MAX_TRIPLE_NUM_BY_STEP = [5, 10, 15, 20]   # cap triples per step
HISTORY_HORIZON = 4                        # abduction uses last N steps
```

---

## Mandatory artifacts

For each query, maintain:

`graphify-out/.deeprefine/loop_trace_<query_id>.json`

Create template:

```bash
deeprefine loop init --query "<exact question>"
```

Append each hop to `interaction_history` **before** starting the next hop.
Run `deeprefine loop validate --trace-file ...` after abduction and before `review` / approved `apply`.

### Evidence ledger

**Every phase boundary** must append to the evidence ledger:

```
graphify-out/.deeprefine/ledger.jsonl
```

Format per entry:

```json
{"ts":"<ISO8601>","query_id":"<id>","phase":"<name>","artifacts":["<path>"],"status":"started|completed|failed","qa":"<self-check result>","model":"<model used>"}
```

Write at these phase boundaries:
- After `loop init`
- After each hop judgement (step N judge)
- After abduction
- After refinement actions generated
- After `loop validate`
- After review (including 5-oracle results)
- After user approval received
- After `apply` + post-apply verification
- After `loop finish`

---

## Query queue selection (default behavior of `/deeprefine`)

`/deeprefine` must process **all unrefined history queries** first, not just the latest one.

1. Sync graphify query memory into DeepRefine history:
   - run: `deeprefine history sync-memory`
   - source dir: `graphify-out/memory/query_*.md`
   - target file: `graphify-out/.deeprefine/history.jsonl`
2. Read pending queue from `graphify-out/.deeprefine/history.jsonl`:
   - include rows where `refined != true`
   - dedupe by `id` (first occurrence)
   - preserve file order
3. If pending queue is non-empty: set `target_queries = pending_queue`.
4. If pending queue is empty: set `target_queries = [current session question]`.

**CRITICAL — OpenCode optimization #1: Parallel query processing (two-stage)**

Instead of processing queries sequentially, use a TWO-STAGE architecture to avoid background task notification loss:

**Stage 1 — Parallel processing (sub-agents do query → refine → save ONLY):** Launch each query in a parallel subagent. Sub-agents NEVER call `task()` internally.

```
Run: deeprefine history sync-memory
target_queries = pending_history_queries() or [current session question]

For EACH question in target_queries, launch a parallel subagent:
  task(description="Process query: {question}",
       prompt="Process this query: judge→abduction→refinement→save to file.
               Query: '{question}'. Write todowrite. Write ledger.
               Save refinement to graphify-out/.deeprefine/refinement_actions_<id>.txt
               Do NOT launch any subagents. Do NOT review. Just save and return.")
```

Each subagent independently runs the core Reafiner loop (query → judge → k-hop → abduction → refinement → save file). For early-exit queries, finish immediately. For refinement-path queries, save the actions file and return.

**Stage 2 — Centralized Oracle review (main agent collects files, launches reviews):** After ALL Stage 1 subagents complete, the main agent collects all generated refinement_actions_*.txt files. For EACH file, launch 5 oracle reviews (see "5-Oracle parallel review" section). Oracles read the file and return APPROVE/REJECT.

**Stage 3 — Auto-approve gate (main agent decides):** Main agent checks all oracle verdicts + review labels. Actions that are ALL HIGH confidence + 5/5 APPROVE → auto-apply. Others → flag for human review.

Do NOT make sub-agents call task() — always launch oracles from the main agent.

---

## Control flow (must match `Reafiner.refine()`)

Pseudocode — follow **exactly**:

```text
target_queries = pending_history_queries()  # refined != true, dedupe by id, keep order
run "deeprefine history sync-memory" before loading pending history
if target_queries is empty:
    target_queries = [current session question]

# OpenCode optimization #1: Parallel fan-out (Stage 1)
for question in target_queries:
    launch parallel subagent via task() to process this question independently
# Sub-agents NEVER call task() internally — they only save files

Within each subagent, for its assigned question (Stage 1 ONLY — query → refine → save):
    interaction_history = []
    for step in 1..MAX_HOPS:
        todowrite status="in_progress" for phase "Query {id} / Step {step}"

        if step == 1:
            # Vector-retrieval equivalent: graphify query on full question
            RUN: graphify query "<question>"
            triples = parse NODE/EDGE → [{subject, relation, object}, ...]
            cap = MAX_TRIPLE_NUM_BY_STEP[0]  # 5
            record retrieval.method = "graphify_query"
        else:
            # k-hop expansion from entities in previous hop (NOT a new random search)
            entities = unique subjects/objects from previous triples
            expand 1-hop neighbors from graphify-out/graph.json (or graphify query on entities)
            cap = MAX_TRIPLE_NUM_BY_STEP[step-1]
            record retrieval.method = "k_hop_expansion" or "graphify_query+k_hop_expansion"

        triples = dedupe; len(triples) <= cap

        # Answerable judgement — prefer DEEPREFINE_JUDGE_MODEL if set (cheap, fast)
        answerable, judgement_raw = LLM_judge(question, triples)
        MUST output ONLY: <judge>Yes</judge> or <judge>No</judge>

        append interaction_history with:
          step, query, num_hops=(step-1)*INCREMENT_HOP, base_top_k=10,
          retrieved_subgraph, answerable, judgement_raw,
          retrieval: {method, evidence: "<command output excerpt>"}

        # Write ledger entry for this hop
        append to graphify-out/.deeprefine/ledger.jsonl:
          {"ts":"<now>","query_id":"<id>","phase":"step_{step}_judge","artifacts":["loop_trace_<id>.json"],"status":"completed","qa":"<judge result>","model":"<model used>"}

        if answerable:
            BREAK   # stop hop loop

    # --- same branch as Reafiner.refine() line 314+ ---
    if len(interaction_history) <= 1:
        # Early exit: first hop was answerable — NO graph refinement
        set trace.early_exit = true
        deeprefine loop finish --trace-file ...   # no --refinement-file
        todowrite status="completed" for query
        write ledger: phase "early_exit" status "completed"
        CONTINUE  # move to next pending query (or subagent returns)
    else:
        # len > 1 → ALWAYS error abduction + actions (even if last hop was Yes)
        # OpenCode optimization #2: Use DEEPREFINE_REFINE_MODEL for abduction/refinement
        error_abduction = LLM_abduction(interaction_history[-HISTORY_HORIZON:])
        MUST output: <abduction>...</abduction>

        actions = LLM_kg_refinement(
            last_hop.retrieved_subgraph,
            error_abduction,
            question,
            source file hints from triples,
        )
        MUST output: <refinement>insert_edge(...)|...</refinement>

        save refinement to graphify-out/.deeprefine/refinement_actions_<id>.txt
        deeprefine loop validate --trace-file ... --refinement-file ...
        write ledger: phase "abduction_refinement" status "completed"

        todowrite status="completed" label="Refinement saved for query {id}"
        # Sub-agent returns here. Do NOT launch oracles. Do NOT review.

# --- Stage 2: Main agent collects all refinement files and reviews ---
Run: deeprefine review --trace-file ... --refinement-file ...
SHOW review labels: HIGH / MEDIUM / LOW for ALL refinement_actions_*.txt files

# For EACH refinement file, launch 5 Oracle reviews IN PARALLEL from MAIN agent:
# See "5-Oracle parallel review" section for exact oracle prompts.
# ALL must return APPROVE before proceeding.

SHOW: combined 5-oracle review with per-oracle verdicts for each query
SHOW: 5-oracle verdict summaries

# --- Stage 3: Auto-approve gate (main agent decides) ---
for each refinement file:
    if ALL 5 oracles APPROVE AND ALL actions labeled HIGH:
        → AUTO-APPLY: deeprefine apply --trace-file ... --refinement-file ...
        → Post-apply verify: graphify query "<original question>"
        → write ledger: phase "post_apply_verify" status "completed|needs_attention"
    else:
        → FLAG for human review
        todowrite status="in_progress" label="Awaiting user approval for query {id}"
        write ledger: phase "review" status "awaiting_approval"

# --- Human approval for flagged items ---
HARD STOP: do not modify graph.json in this /deeprefine turn for FLAGGED items
Report the proposed actions, review labels, and oracle verdicts to the user
Ask for explicit approval; approval must arrive in the user's next message

# Follow-up turn only, after the user's next message explicitly approves/apply/write:
if user explicitly approves and no LOW-confidence action remains AND all 5 oracles APPROVE:
    deeprefine apply --trace-file ... --refinement-file ...
    deeprefine loop finish --trace-file ... --refinement-file ...
    # OpenCode optimization #5: Post-apply verification
    RUN: graphify query "<original question>"
    Verify: did the answer status change? If still not answerable, report to user.
    write ledger: phase "post_apply_verify" status "completed|needs_attention"
if user explicitly accepts LOW-confidence risk in that approval message:
    deeprefine apply --allow-low-confidence --trace-file ... --refinement-file ...
    deeprefine loop finish --trace-file ... --refinement-file ...
    # Same post-apply verification as above
if any oracle returned REJECT and user has not explicitly overridden:
    Report which oracle(s) rejected and why
    Ask user to either: (a) override and apply anyway, or (b) fix and re-run refinement
    Do NOT apply until user decision
```

**Critical Reafiner rule:** refinement runs when `len(interaction_history) > 1`, not only when all judgements are `No`.

**Safe-review rule:** a refinement path is dry-run by default. Generating `<refinement>` actions is not approval to write `graph.json`, and a normal `/deeprefine` turn must end after `deeprefine review`.

---

## 5-Oracle parallel review (OpenCode optimization #4 — Stage 2: Main Agent runs this)

**This review runs AFTER all Stage 1 sub-agents have completed and saved their refinement files. The main agent collects ALL refinement_actions_*.txt files and launches this review. Sub-agents NEVER run oracle reviews.**

For EACH refinement file, the main agent launches 5 reviews in parallel:

```
# 1. Collect all pending refinement files
refinement_files = glob("graphify-out/.deeprefine/refinement_actions_*.txt")

# 2. For each file, launch 5 oracle reviews in parallel from the MAIN agent (NOT from sub-agents)
for each file in refinement_files:
    task(subagent_type="general", description="Oracle 1: Completeness audit",
         prompt="Review the refinement actions at {file}. Are they COMPLETE —
         do they fully address every category (incompleteness, incorrectness, redundancy)
         identified in the abduction? Return APPROVE or REJECT with specific reasoning.")

    task(subagent_type="general", description="Oracle 2: Correctness audit",
         prompt="Review the refinement actions at {file}. Are the edges/nodes
         factually CORRECT based on source code? Flag any wrong facts.
         Return APPROVE or REJECT with specific reasoning.")

    task(subagent_type="general", description="Oracle 3: Safety audit",
         prompt="Review the refinement actions at {file}. Will these changes
         BREAK the existing graph structure? Check: orphaned nodes, broken chains,
         conflicting relations, duplicate edges. Return APPROVE or REJECT.")

    task(subagent_type="general", description="Oracle 4: Consistency audit",
         prompt="Review the refinement actions at {file}. Do new edges create
         CYCLES, ambiguity, or self-contradiction? Check: circular relations,
         node label collisions. Return APPROVE or REJECT.")

    task(subagent_type="general", description="Oracle 5: Edge-case audit",
         prompt="Review the refinement actions at {file} and the original question.
         Does the fix handle EDGE CASES, not just the happy path?
         Consider: ambiguous entity names, multi-hop paths, partial matches.
         Return APPROVE or REJECT.")
```

**Gate rule:** ALL 5 oracles must return APPROVE before apply proceeds. If any oracle returns REJECT, the main agent must:
1. Report which oracle(s) rejected and their specific reasoning
2. Ask the user: "Override and apply anyway, or abort and re-run refinement?"
3. Do NOT apply until the user explicitly responds

**Auto-approve rule (Stage 3):** Actions that are ALL HIGH confidence (from deeprefine review) AND 5/5 APPROVE → auto-apply immediately. All others → flag for human review.

---

## Evidence-aware review rules

Before any graph write, run:

```bash
deeprefine review --trace-file graphify-out/.deeprefine/loop_trace_<id>.json --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
```

The review must label every action:

- `HIGH`: direct graph or code evidence exists.
- `MEDIUM`: k-hop context supports the action, but direct code or exact-edge evidence is missing.
- `LOW`: endpoint nodes are ambiguous, too broad, cross-community, or cannot be grounded in `graph.json`.

Bare names such as `main()`, `run()`, `train()`, `test()`, and `setup()` are ambiguous even if they match only one node. Prefer file-qualified labels such as `trainer_Brain_CLS.py::train_epoch()`.

`deeprefine apply` refuses LOW-confidence actions by default. Use `--allow-low-confidence` only when the user explicitly approves the risk.

---

## LLM prompts (verbatim — do not paraphrase)

### Judgement (`_answerable_judgement`)

**System:**

```text
As an advanced judgement assistant, your task is to judge whether the given question is answerable based on the provided KG context.

Evaluate whether the given question is answerable based on the provided KG context. Output your judgment in the following format:
<judge>Yes</judge> or <judge>No</judge>

**Important:** You must think carefully about the question and the KG context before making your judgment. And output your judgment result directly in the specified format.
```

**User:**

```text
Question: {question}
Knowledge Graph (KG) context: {triples_string}
```

`{triples_string}` = one triple per line: `subject | relation | object`

### Error abduction (`_error_abduction`) — only if `len(interaction_history) > 1`

**System:**

```text
As an advanced error abduction assistant, your task is to analyze the error reasons based on the given interaction history.

Analyze the reasons of the unanswerable questions based on the given interaction history from the incompleteness, incorrectness, and redundancy perspectives. Output your analysis in the following format:
<abduction>...</abduction>

**Important:** You must think carefully about the interaction history before making your analysis. And output your analysis result directly in the specified format.
```

**User:**

```text
Interaction history: {interaction_history}
```

`{interaction_history}` format (same as Reafiner):

```text
Step1:
['Query': ..., 'Subgraph_hop': ..., 'Subgraph_content': ..., 'Answerable': ...]

Step2:
...
```

### KG refinement actions (`_kg_refinement_action`) — only if `len(interaction_history) > 1`

**System:**

```text
As an advanced knowledge graph refinement assistant, your task is to generate a series of actions (**within 10 actions**) to refine the given KG to make it more suitable for answering the given question.

Based on the given KG and the analysed error reasons, refine the given KG to make it more easily for retrieval and answering the given question. You have the following three types of actions to conduct:

- insert_edge(subject, relation, object): Insert a new edge into the KG to complete the missing information.
- delete_edge(subject, relation, object): Delete an edge from the KG to remove the redundant information or conflicting information.
- replace_node(old_entity, new_entity): Replace an entity in the KG to correct the errors or deal with disambiguation.

Output a series of actions (**within 10 actions**) in the following format:
<refinement>insert_edge("...", "...", "...")|delete_edge("...", "...", "...")|replace_node("...", "...")|...</refinement>

**Important:** You must think carefully about the given KG and the analysed error reasons before making your refinement. DO NOT DELETE ANY IRRELEVANT TRIPLES FROM THE ORIGINAL KG. TRY TO KEEP THE ORIGINAL KG AS MUCH AS POSSIBLE. DO NOT GENERATE TOO MANY ACTIONS. And output your refinement result directly in the specified format.
```

**User:**

```text
Original Text: {original_text}
KG: {triples_string}
Question: {question}
Error reasons: {error_reasons}
```

Use **last hop's** `retrieved_subgraph` as `{triples_string}` (JSON list is OK in trace; string form for the prompt).

### KG Refinement — OpenCode schema constraints

To prevent invalid refinement actions, the Agent MUST enforce these constraints before generating `<refinement>` output.

<existing_edge_types>
Valid relation types in this graph (from graph.json). Use ONLY these types:
- calls, contains, imports_from, references, defined_in, has_method, rationale_for
- part_of, defines, imports, returns, instantiates, validates_field, exports

Do NOT invent new relation types (e.g. assign_confidence, references_constant, has_parameter).
If the concept cannot be expressed with an existing edge type, do NOT generate the action.
</existing_edge_types>

<format_constraint>
Every insert_edge(subject, relation, object) must use node labels from graph.json
as subject and object. Node labels look like:
  - File paths:  "agent_loop.py", "action_review.py"
  - Functions:   "validate_trace()", "review_action()"
  - Concepts:    "DeepRefine Agent Loop Workflow"

Do NOT use natural language sentences as node labels.
Do NOT use 4-argument insert_edge (only 3 arguments: subject, relation, object).

WRONG: insert_edge("review_action()", "assigns_confidence", "LOW", "when warnings...")
RIGHT: insert_edge("review_action()", "calls", "_matching_nodes()")
</format_constraint>

<operation_constraint>
Only these 3 operations are supported by the apply engine (agent_graph.py):
  - insert_edge(subject, relation, object)
  - delete_edge(subject, relation, object)
  - replace_node(old_entity, new_entity)

Do NOT use insert_node, update_node, merge_node, or any other operation type.
The apply engine will REJECT any unrecognized operation.
</operation_constraint>

---

## Per-query checklist (use todowrite — OpenCode optimization #3)

Do NOT use a text checklist. Instead, use `todowrite()` at each phase boundary:

```
todowrite(todos=[
  {"content": "Phase: sync-memory — sync graphify query memory to history.jsonl", "status": "completed", "priority": "high"},
  {"content": "Phase: init — create loop_trace_<id>.json for query {id}", "status": "completed", "priority": "high"},
  {"content": "Phase: step_1 — graphify query + judge hop 0 for query {id}", "status": "in_progress", "priority": "high"},
  {"content": "Phase: step_{N} — k-hop expansion + judge hop {N-1} for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: abduction — analyze error reasons for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: refinement — generate actions for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: validate — CLI loop validate for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: review — evidence review + 5-oracle audit for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: await_approval — HARD STOP, waiting for user approval for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: apply — apply approved actions + post-apply verify for query {id}", "status": "pending", "priority": "high"},
  {"content": "Phase: finish — loop finish + ledger write for query {id}", "status": "pending", "priority": "high"},
])
```

This replaces the Cursor text checklist. OpenCode agents can see real-time progress and resume from the last completed phase.

---

## Mode selection

Three slash commands for different workflow entry points:

| Command | Scope | When to use |
|---------|-------|-------------|
| `/deeprefine` | Full pipeline: sync → judge → abduction → refinement → review → (await approval) → apply → verify | Normal usage: process all pending queries |
| `/deeprefine-review` | Review only: read actions file → 5-oracle audit → evidence review → present results | Actions already generated, need quality audit |
| `/deeprefine-apply` | Apply only: read actions → confirm → apply → post-apply verify → finish | Review complete, user approved in previous turn |

**Auto-detection logic in `/deeprefine`:**
- If `refinement_actions_<id>.txt` exists and `loop_trace_<id>.json` shows validation passed but review not done → offer to run `/deeprefine-review`
- If review report exists and all actions reviewed → offer to run `/deeprefine-apply`
- If neither exists → start full pipeline

---

## Commands (in order)

```bash
# 0. KB project root; graphify-out/graph.json exists
mkdir -p graphify-out/.deeprefine
cp graphify-out/graph.json graphify-out/.deeprefine/graph.json.bak

# 1. Sync graphify query memory to deeprefine history first.
deeprefine history sync-memory

# 2. Build target query list:
#    - preferred: all pending from history.jsonl (refined != true)
#    - fallback: current session question (single query)
deeprefine history list --pending

# 3. OpenCode optimization: Launch parallel subagents for EACH query
#    Each subagent runs the full pipeline independently.

# 4–7. Per subagent: graphify/graph read → judge → append to loop_trace_*.json
#    Use todowrite for progress, write ledger after each phase.

# 8a. Early exit (len(history)==1 and answerable)
deeprefine loop validate --trace-file graphify-out/.deeprefine/loop_trace_<id>.json
deeprefine loop finish --trace-file graphify-out/.deeprefine/loop_trace_<id>.json

# 8b. Refinement path (len(history)>1): validate → 5-oracle review → deeprefine review
deeprefine loop validate --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
# Launch 5 oracle subagents in parallel (see "5-Oracle parallel review" section)
deeprefine review --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# HARD STOP.
# A normal /deeprefine run must end here.
# Report the review, oracle verdicts, and ledger to the user.
# Ask for explicit approval.
# Do NOT run deeprefine apply in the same /deeprefine turn.

# Approval-only follow-up commands, only after the user explicitly says approve/apply:
deeprefine apply --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
# Optional explicit risk override:
# deeprefine apply --allow-low-confidence --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
deeprefine loop finish --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# Post-apply verification (OpenCode optimization #5):
graphify query "<original question>"
# Verify answerability changed. If still not answerable, report to user with full ledger context.
```

---

## `loop_trace_*.json` schema

```json
{
  "schema_version": 1,
  "mode": "agent-loop",
  "query": "what is dulce?",
  "query_id": "5cdc0798eb59b486",
  "constants": { "max_hops": 4, "increment_hop": 1, "base_top_k": 10,
    "max_triple_num_by_step": [5, 10, 15, 20], "history_horizon_size": 4 },
  "interaction_history": [
    {
      "step": 1,
      "num_hops": 0,
      "base_top_k": 10,
      "query": "what is dulce?",
      "retrieval": {
        "method": "graphify_query",
        "evidence": "graphify query \"what is dulce?\" → …"
      },
      "retrieved_subgraph": [
        {"subject": "A", "relation": "r", "object": "B"}
      ],
      "answerable": false,
      "judgement_raw": "<judge>No</judge>"
    }
  ],
  "error_abduction_reason": "…",
  "error_abduction_raw": "<abduction>…</abduction>",
  "refinement_action_file": "graphify-out/.deeprefine/refinement_actions_<id>.txt",
  "early_exit": false,
  "oracle_review": {
    "completeness": "APPROVE",
    "correctness": "APPROVE",
    "safety": "APPROVE",
    "consistency": "APPROVE",
    "edge_cases": "APPROVE"
  },
  "ledger_ref": "graphify-out/.deeprefine/ledger.jsonl"
}
```

Note: `oracle_review` and `ledger_ref` are OpenCode-specific trace extensions.

---

## Evidence ledger schema

```
graphify-out/.deeprefine/ledger.jsonl
```

One JSON object per line, appended at every phase boundary:

```json
{"ts":"2026-07-02T20:40:00Z","query_id":"5cdc0798eb59b486","phase":"step_1_judge","artifacts":["loop_trace_5cdc0798eb59b486.json"],"status":"completed","qa":"judge returned No","model":"gpt-4o-mini"}
{"ts":"2026-07-02T20:40:15Z","query_id":"5cdc0798eb59b486","phase":"step_2_judge","artifacts":["loop_trace_5cdc0798eb59b486.json"],"status":"completed","qa":"judge returned No","model":"gpt-4o-mini"}
{"ts":"2026-07-02T20:41:00Z","query_id":"5cdc0798eb59b486","phase":"abduction_refinement","artifacts":["loop_trace_5cdc0798eb59b486.json","refinement_actions_5cdc0798eb59b486.txt"],"status":"completed","qa":"generated 3 actions","model":"claude-sonnet-4-20250514"}
{"ts":"2026-07-02T20:42:00Z","query_id":"5cdc0798eb59b486","phase":"review","artifacts":["loop_trace_5cdc0798eb59b486.json","refinement_actions_5cdc0798eb59b486.txt"],"status":"awaiting_approval","qa":"5/5 oracles APPROVE, review: 2 HIGH, 1 MEDIUM, 0 LOW","model":"claude-sonnet-4-20250514"}
```

---

## Optional: CLI mode (FAISS + API)

Only when the user **explicitly** requests `deeprefine refine` / full runtime:

```bash
conda activate atlastune
export DEEPREFINE_EMBED_URL=... DEEPREFINE_LLM_URL=...
deeprefine refine --query "..."       # dry-run proposal only
# deeprefine refine --query "..." --apply   # only when the user explicitly wants CLI mode to write graph.json
```

---

## Paths

- `graphify-out/graph.json`
- `graphify-out/.deeprefine/loop_trace_*.json` (**required**)
- `graphify-out/.deeprefine/refinement_actions_*.txt`
- `graphify-out/.deeprefine/refinement_results_*.jsonl`
- `graphify-out/.deeprefine/proposed_refinement_review_*.md`
- `graphify-out/.deeprefine/proposed_refinement_review_*.json`
- `graphify-out/.deeprefine/graph.json.bak`
- `graphify-out/.deeprefine/ledger.jsonl` (**new — OpenCode evidence ledger**)
