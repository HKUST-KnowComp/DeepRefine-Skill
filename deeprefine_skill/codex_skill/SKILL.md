---
name: deeprefine
description: >-
  Codex adapter for the DeepRefine agent-native Reafiner loop. Use when the
  user invokes $deeprefine or /deeprefine, or asks to refine, diagnose, review,
  or apply changes to a Graphify / LLM-Wiki knowledge graph. Must follow the
  canonical DeepRefine skill rules and stop for review before graph writes.
---

# DeepRefine - Codex Adapter

This file is the Codex-specific entrypoint. It keeps the platform rules small
and loads longer DeepRefine procedure details only when needed:

- Full workflow, queue selection, Reafiner branch logic, and review rules:
  [references/reafiner-workflow.md](references/reafiner-workflow.md)
- Verbatim judgement, abduction, and refinement prompts:
  [references/llm-prompts.md](references/llm-prompts.md)
- Checklist, command sequence, trace schema, paths, and CLI mode:
  [references/trace-and-commands.md](references/trace-and-commands.md)

Do not reimplement or shorten the algorithm from memory. Load the relevant
reference file before executing that part of the workflow.

## Codex Invocation

Trigger this skill when the user:

- explicitly invokes `$deeprefine` or `/deeprefine`;
- asks to refine, improve, diagnose, repair, inspect, or review a Graphify
  knowledge graph;
- asks to apply a previously reviewed DeepRefine refinement.

Run from the knowledge-base project root, where `graphify-out/graph.json`
exists. If the user is planning or asking how DeepRefine works, explain the
workflow and do not mutate files.

If `deeprefine` is unavailable, tell the user to install it:

```bash
pip install deeprefine-cli
```

For source development:

```bash
pip install -e /path/to/DeepRefine-Skill
```

## Hard Safety Policy

A normal `$deeprefine` or `/deeprefine` invocation is dry-run only and **MUST
NEVER** call `deeprefine apply`.

The default workflow must stop after:

1. `deeprefine loop validate`
2. `deeprefine review`
3. showing the proposed actions and HIGH/MEDIUM/LOW review report to the user

Then ask for explicit approval.

Only if the user's next message explicitly says to approve/apply/write the graph
may you run:

```bash
deeprefine apply --trace-file ... --refinement-file ...
deeprefine loop finish --trace-file ... --refinement-file ...
```

Do not treat any of these as approval:

- generation of a `<refinement>` block;
- a valid `loop_trace_<query_id>.json`;
- a prior user message;
- a successful `deeprefine review`.

If the review contains LOW-confidence actions, use
`--allow-low-confidence` only when the user's current approval message
explicitly accepts that risk.

## Mode Selection

### Full workflow

Use for `$deeprefine`, `/deeprefine`, or requests to refine/improve/fix the
graph.

Follow the canonical reference in this order:

1. `references/reafiner-workflow.md`
2. `references/llm-prompts.md` when producing tagged LLM outputs
3. `references/trace-and-commands.md` when writing traces or running commands

Do not copy only the latest query if pending history exists. Process all
unrefined history queries first, preserving canonical dedupe/order rules.

### Review only

Use when the user asks to review, audit, inspect, dry-run, check evidence, or
show what would change.

Run validation and review only:

```bash
deeprefine loop validate --trace-file ... --refinement-file ...
deeprefine review --trace-file ... --refinement-file ...
```

Show the HIGH/MEDIUM/LOW evidence report. Do not modify `graph.json`.

### Apply only

Use only when the user's current message explicitly approves a previously
reviewed refinement.

Before applying, verify that the trace and refinement file match
`references/trace-and-commands.md` and the review rules in
`references/reafiner-workflow.md`. Then run:

```bash
deeprefine loop validate --trace-file ... --refinement-file ...
deeprefine apply --trace-file ... --refinement-file ...
deeprefine loop finish --trace-file ... --refinement-file ...
```

Use the LOW-confidence override only with explicit risk acknowledgement in the
same user message:

```bash
deeprefine apply --allow-low-confidence --trace-file ... --refinement-file ...
```

## Non-Negotiable Rules

These are restated here so Codex always sees the hard stops before loading any
reference.

Do not:

1. Run `deeprefine refine` unless the user explicitly asks for CLI/FAISS mode.
2. Call `deeprefine apply` without a valid `loop_trace_<query_id>.json`.
3. Call `deeprefine apply` before `deeprefine review` and explicit approval.
4. Ignore LOW-confidence review warnings without explicit risk acceptance.
5. Skip any hop's `<judge>Yes</judge>` / `<judge>No</judge>` judgement.
6. Skip error abduction when `len(interaction_history) > 1`.
7. Write `<refinement>` before abduction when refinement is required.
8. Hand-edit `graphify-out/graph.json` with Python or ad-hoc JSON patches.
9. Ignore pending history and refine only one latest query.
10. Invent a shorter pipeline such as "read file -> write refinement -> apply".

If validation fails, fix the trace or rerun the missing step. Do not bypass with
`--skip-trace-check` in agent mode.

## What to Load From References

Keep this adapter concise. Load the smallest reference needed:

- Full Reafiner pseudocode and safe review:
  `references/reafiner-workflow.md`
- Verbatim LLM prompts:
  `references/llm-prompts.md`
- Required JSON shape, exact command sequence, and CLI/FAISS exception path:
  `references/trace-and-commands.md`

Use the canonical commands and artifacts exactly as written there. This adapter
only maps those rules onto Codex's `$deeprefine` / `/deeprefine` invocation and
approval behavior.
