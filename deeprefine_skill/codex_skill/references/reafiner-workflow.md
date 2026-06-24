# DeepRefine Reafiner Workflow

Use this reference for the full `$deeprefine` / `/deeprefine` workflow.

## Safety Policy

A normal `$deeprefine` or `/deeprefine` invocation must stop after:

1. `deeprefine loop validate`
2. `deeprefine review`
3. showing the proposed actions and HIGH/MEDIUM/LOW review report

Then ask the user for explicit approval. Do not run `deeprefine apply` in the
same default refinement turn.

Approval must be in the user's current message and must explicitly say to
approve/apply/write the graph. A generated `<refinement>` block, a valid trace,
or a successful review is not approval.

## Forbidden

Do not:

1. Run `deeprefine refine` unless the user explicitly asks for CLI/FAISS mode.
2. Call `deeprefine apply` without a valid `loop_trace_<query_id>.json`.
3. Call `deeprefine apply` before `deeprefine review` and explicit approval.
4. Ignore LOW-confidence warnings unless the user explicitly accepts the risk.
5. Skip any hop's `<judge>Yes</judge>` / `<judge>No</judge>` judgement.
6. Skip error abduction when `len(interaction_history) > 1`.
7. Write `<refinement>` before abduction when refinement is required.
8. Hand-edit `graphify-out/graph.json` with Python or ad-hoc JSON patches.
9. Ignore pending history and refine only one latest query.
10. Invent a shorter pipeline such as "read file -> write refinement -> apply".

If validation fails, fix the trace or rerun the missing step. Do not bypass with
`--skip-trace-check` in agent mode.

## Constants

```text
MAX_HOPS = 4
INCREMENT_HOP = 1
BASE_TOP_K = 10
MAX_TRIPLE_NUM_BY_STEP = [5, 10, 15, 20]
HISTORY_HORIZON = 4
```

## Mandatory Artifact

For each query, maintain:

```text
graphify-out/.deeprefine/loop_trace_<query_id>.json
```

Create the template with:

```bash
deeprefine loop init --query "<exact question>"
```

Append each hop to `interaction_history` before starting the next hop. Run
`deeprefine loop validate --trace-file ...` after abduction and before review or
approved apply.

## Query Queue Selection

Default `$deeprefine` must process all unrefined history queries first, not only
the latest query.

1. Run `deeprefine history sync-memory`.
2. Read `graphify-out/.deeprefine/history.jsonl`.
3. Include rows where `refined != true`.
4. Dedupe by `id`, preserving first occurrence and file order.
5. If the pending queue is non-empty, use it as `target_queries`.
6. If the queue is empty, use the current session question.
7. Process target queries sequentially.

## Control Flow

Follow the same branch structure as `Reafiner.refine()`.

```text
target_queries = pending_history_queries()
run "deeprefine history sync-memory" before loading pending history
if target_queries is empty:
    target_queries = [current session question]

for question in target_queries:
    interaction_history = []
    for step in 1..MAX_HOPS:
        print "[Step: {step}]"

        if step == 1:
            run: graphify query "<question>"
            triples = parse NODE/EDGE rows into subject/relation/object triples
            cap = MAX_TRIPLE_NUM_BY_STEP[0]
            record retrieval.method = "graphify_query"
        else:
            entities = unique subjects/objects from previous triples
            expand 1-hop neighbors from graphify-out/graph.json
            cap = MAX_TRIPLE_NUM_BY_STEP[step - 1]
            record retrieval.method = "k_hop_expansion" or "graphify_query+k_hop_expansion"

        triples = dedupe; len(triples) <= cap
        answerable, judgement_raw = LLM_judge(question, triples)
        judgement_raw must be exactly <judge>Yes</judge> or <judge>No</judge>

        append interaction_history with:
          step, query, num_hops=(step - 1) * INCREMENT_HOP, base_top_k=10,
          retrieved_subgraph, answerable, judgement_raw,
          retrieval: {method, evidence: "<command output excerpt>"}

        if answerable:
            break

    if len(interaction_history) <= 1:
        set trace.early_exit = true
        deeprefine loop finish --trace-file ...
        continue

    error_abduction = LLM_abduction(interaction_history[-HISTORY_HORIZON:])
    error_abduction must be wrapped in <abduction>...</abduction>

    actions = LLM_kg_refinement(last_hop.retrieved_subgraph, error_abduction, question)
    actions must be wrapped in <refinement>...</refinement>

    save actions to graphify-out/.deeprefine/refinement_actions_<id>.txt
    deeprefine loop validate --trace-file ... --refinement-file ...
    deeprefine review --trace-file ... --refinement-file ...
    show review labels, evidence, warnings, and suggested replacements
    hard stop; do not modify graph.json in this turn
```

Critical rule: refinement runs when `len(interaction_history) > 1`, not only
when all judgements are `No`.

## Evidence-Aware Review

Before any graph write, run:

```bash
deeprefine review --trace-file graphify-out/.deeprefine/loop_trace_<id>.json --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
```

The review labels every action:

- `HIGH`: direct graph or code evidence exists.
- `MEDIUM`: k-hop context supports the action, but direct code or exact-edge
  evidence is missing.
- `LOW`: endpoint nodes are ambiguous, too broad, cross-community, or cannot be
  grounded in `graph.json`.

Bare names such as `main()`, `run()`, `train()`, `test()`, and `setup()` are
ambiguous even if they match only one node. Prefer file-qualified labels such
as `trainer_Brain_CLS.py::train_epoch()`.

`deeprefine apply` refuses LOW-confidence actions by default. Use
`--allow-low-confidence` only when the user explicitly approves the risk.
