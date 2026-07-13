---
name: deeprefine
description: >-
  Agent-native DeepRefine Reafiner loop — same control flow as Reafiner.refine(),
  graphify search instead of FAISS, session LLM, dry-run review before approved graph writes.
disable-model-invocation: false
---

# DeepRefine — Agent Reafiner loop (strict)

## Default safety policy: dry-run only

A normal `/deeprefine` invocation **MUST NEVER** call `deeprefine apply`.

The default `/deeprefine` workflow must stop after:

1. `deeprefine loop validate`
2. `deeprefine review`
3. showing the proposed actions and HIGH/MEDIUM/LOW review report to the user

Then ask the user for explicit approval.

Only if the user's **next message** explicitly says to approve/apply/write the graph may you run:

```bash
deeprefine apply --refresh-wiki --trace-file ... --refinement-file ...
deeprefine loop finish --trace-file ... --refinement-file ...
```

Do not treat generation of `<refinement>` actions as approval. Do not treat a valid trace as approval. Do not apply in the same `/deeprefine` turn.

---

You **MUST** implement the **same control flow** as `Reafiner.refine()` in DeepRefine (`autorefiner/src/reafiner.py`).

| Component | Agent mode | CLI `deeprefine refine` |
|-----------|------------|-------------------------|
| Retrieval | `graphify query` + k-hop from `graph.json` | FAISS retriever |
| LLM | **Your session model** | External API / vLLM |
| Graph writes | Dry-run proposal + `deeprefine review`; `deeprefine apply` only after user approval | Dry-run by default; `--apply` persists |

---

## FORBIDDEN (hard stop)

Do **NOT**:

1. Run `deeprefine refine` (unless the user explicitly asks for CLI/FAISS mode).
2. Call `deeprefine apply` without a valid `loop_trace_<query_id>.json` (CLI will reject).
3. Call `deeprefine apply` before running `deeprefine review` and receiving explicit user approval.
4. Ignore LOW-confidence review warnings unless the user explicitly requests `--allow-low-confidence`.
5. Skip any hop’s `<judge>Yes</judge>` / `<judge>No</judge>` judgement.
6. Skip error abduction when `len(interaction_history) > 1`.
7. Write `<refinement>` before abduction when refinement is required.
8. Hand-edit `graph.json` with Python or ad-hoc JSON patches.
9. Ignore pending history and refine only one latest query when unrefined queries already exist.
10. Invent a shorter pipeline (“read file → write refinement → apply”).

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

## Mandatory artifact

For each query, maintain:

`graphify-out/.deeprefine/loop_trace_<query_id>.json`

Create template:

```bash
deeprefine loop init --query "<exact question>"
```

Append each hop to `interaction_history` **before** starting the next hop.  
Run `deeprefine loop validate --trace-file ...` after abduction and before `review` / approved `apply`.

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
5. Run the full Reafiner loop for **each** query in `target_queries`, one by one.
6. For early-exit queries, finish immediately. For refinement-path queries, generate review output and wait for user approval before `apply` + `loop finish`.

---

## Control flow (must match `Reafiner.refine()`)

Pseudocode — follow **exactly**:

```text
target_queries = pending_history_queries()  # refined != true, dedupe by id, keep order
run "deeprefine history sync-memory" before loading pending history
if target_queries is empty:
    target_queries = [current session question]

for question in target_queries:
    interaction_history = []
    for step in 1..MAX_HOPS:
        print "[Step: {step}]"   # show in chat

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

        # Answerable judgement — session LLM, prompts below
        answerable, judgement_raw = LLM_judge(question, triples)
        MUST output ONLY: <judge>Yes</judge> or <judge>No</judge>

        append interaction_history with:
          step, query, num_hops=(step-1)*INCREMENT_HOP, base_top_k=10,
          retrieved_subgraph, answerable, judgement_raw,
          retrieval: {method, evidence: "<command output excerpt>"}

        if answerable:
            BREAK   # stop hop loop

    # --- same branch as Reafiner.refine() line 314+ ---
    if len(interaction_history) <= 1:
        # Early exit: first hop was answerable — NO graph refinement
        set trace.early_exit = true
        deeprefine loop finish --trace-file ...   # no --refinement-file
        CONTINUE  # move to next pending query
    else:
        # len > 1 → ALWAYS error abduction + actions (even if last hop was Yes)
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
        deeprefine review --trace-file ... --refinement-file ...
        SHOW review labels: HIGH / MEDIUM / LOW, evidence, warnings, suggested replacements
        HARD STOP: do not modify graph.json in this /deeprefine turn
        Report the proposed actions and HIGH/MEDIUM/LOW review to the user
        Ask for explicit approval; approval must arrive in the user's next message

        # Follow-up turn only, after the user's next message explicitly approves/apply/write:
        if user explicitly approves and no LOW-confidence action remains:
            deeprefine apply --refresh-wiki --trace-file ... --refinement-file ...
            deeprefine loop finish --trace-file ... --refinement-file ...
        if user explicitly accepts LOW-confidence risk in that approval message:
            deeprefine apply --refresh-wiki --allow-low-confidence --trace-file ... --refinement-file ...
            deeprefine loop finish --trace-file ... --refinement-file ...
```

**Critical Reafiner rule:** refinement runs when `len(interaction_history) > 1`, not only when all judgements are `No`.

**Safe-review rule:** a refinement path is dry-run by default. Generating `<refinement>` actions is not approval to write `graph.json`, and a normal `/deeprefine` turn must end after `deeprefine review`.

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

Use **last hop’s** `retrieved_subgraph` as `{triples_string}` (JSON list is OK in trace; string form for the prompt).

---

## Per-query checklist (report in chat)

Copy and tick each item in your final message:

```text
[ ] Backup: graphify-out/.deeprefine/graph.json.bak
[ ] loop_trace_<id>.json created
[ ] Step 1: graphify query executed (evidence in trace)
[ ] Each step: <judge>Yes|No</judge> shown in chat
[ ] Hops stopped on Yes OR reached MAX_HOPS
[ ] early_exit OR (abduction + refinement) per Reafiner branch
[ ] deeprefine loop validate passed
[ ] deeprefine review generated with HIGH/MEDIUM/LOW labels
[ ] graph.json intentionally left unchanged pending next-message approval OR user approved in a follow-up message
[ ] deeprefine apply skipped in normal /deeprefine turn; only run after next-message approval
[ ] deeprefine loop finish
```

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

# 3. For EACH query in target list:
deeprefine loop init --query "<question>"

# 4–7. For each hop: graphify/graph read → judge → append to loop_trace_*.json

# 8a. Early exit (len(history)==1 and answerable)
deeprefine loop validate --trace-file graphify-out/.deeprefine/loop_trace_<id>.json
deeprefine loop finish --trace-file graphify-out/.deeprefine/loop_trace_<id>.json

# 8b. Refinement path (len(history)>1): dry-run review first
deeprefine loop validate --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
deeprefine review --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# HARD STOP.
# A normal /deeprefine run must end here.
# Report the review to the user and ask for explicit approval.
# Do NOT run deeprefine apply in the same /deeprefine turn.

# Approval-only follow-up commands, only after the user explicitly says approve/apply:
deeprefine apply --refresh-wiki --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
# Optional explicit risk override:
# deeprefine apply --refresh-wiki --allow-low-confidence --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
deeprefine loop finish --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# 9. Repeat step 3..8 until all pending queries are reviewed/finished.
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
  "early_exit": false
}
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
