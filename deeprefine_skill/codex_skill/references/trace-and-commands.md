# DeepRefine Trace And Commands

Use this reference when writing or validating loop traces and when executing the
CLI command sequence.

## Per-Query Checklist

Report these items in chat for each query:

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

## Commands In Order

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

# 3. For each query in target list:
deeprefine loop init --query "<question>"

# 4-7. For each hop: graphify/graph read -> judge -> append to loop_trace_*.json

# 8a. Early exit (len(history)==1 and answerable)
deeprefine loop validate --trace-file graphify-out/.deeprefine/loop_trace_<id>.json
deeprefine loop finish --trace-file graphify-out/.deeprefine/loop_trace_<id>.json

# 8b. Refinement path (len(history)>1): dry-run review first
deeprefine loop validate --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
deeprefine review --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# Hard stop.
# A normal /deeprefine run must end here.
# Report the review to the user and ask for explicit approval.
# Do not run deeprefine apply in the same /deeprefine turn.

# Approval-only follow-up commands, only after explicit approve/apply:
deeprefine apply --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
# Optional explicit risk override:
# deeprefine apply --allow-low-confidence --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt
deeprefine loop finish --trace-file ... --refinement-file graphify-out/.deeprefine/refinement_actions_<id>.txt

# 9. Repeat until all pending queries are reviewed/finished.
```

## `loop_trace_*.json` Schema

```json
{
  "schema_version": 1,
  "mode": "agent-loop",
  "query": "what is dulce?",
  "query_id": "5cdc0798eb59b486",
  "constants": {
    "max_hops": 4,
    "increment_hop": 1,
    "base_top_k": 10,
    "max_triple_num_by_step": [5, 10, 15, 20],
    "history_horizon_size": 4
  },
  "interaction_history": [
    {
      "step": 1,
      "num_hops": 0,
      "base_top_k": 10,
      "query": "what is dulce?",
      "retrieval": {
        "method": "graphify_query",
        "evidence": "graphify query \"what is dulce?\" -> ..."
      },
      "retrieved_subgraph": [
        {"subject": "A", "relation": "r", "object": "B"}
      ],
      "answerable": false,
      "judgement_raw": "<judge>No</judge>"
    }
  ],
  "error_abduction_reason": "...",
  "error_abduction_raw": "<abduction>...</abduction>",
  "refinement_action_file": "graphify-out/.deeprefine/refinement_actions_<id>.txt",
  "early_exit": false
}
```

## Optional CLI Mode

Only use this when the user explicitly requests `deeprefine refine` / full
runtime mode.

```bash
conda activate atlastune
export DEEPREFINE_EMBED_URL=... DEEPREFINE_LLM_URL=...
deeprefine refine --query "..."       # dry-run proposal only
# deeprefine refine --query "..." --apply   # only when explicitly requested
```

## Paths

- `graphify-out/graph.json`
- `graphify-out/.deeprefine/loop_trace_*.json`
- `graphify-out/.deeprefine/refinement_actions_*.txt`
- `graphify-out/.deeprefine/refinement_results_*.jsonl`
- `graphify-out/.deeprefine/proposed_refinement_review_*.md`
- `graphify-out/.deeprefine/proposed_refinement_review_*.json`
- `graphify-out/.deeprefine/graph.json.bak`
