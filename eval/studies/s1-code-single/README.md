# S1 — Single-Repository Code Recovery

## Question

Can DeepRefine recover deliberately hidden import edges in one code graph
without damaging the rest of the graph?

## Protocol

- Freeze source revision, baseline graph, AST gold, query set, model, and prompt configuration.
- Generate guided queries only from the baseline missing-edge set.
- Refine a copy of the baseline graph; never mutate the source artifact.
- Score module and symbol imports separately with strict target-module matching.

## Primary metric

Strict module-dependency recovery: recovered target edges / missing target edges.

## Required diagnostics

- strict symbol-import recovery;
- final precision/recall/F1;
- baseline nodes and link instances lost;
- new unverified import claims;
- calls, tokens, errors, and latency.

The current corrected rerun is a single guided run, not an autonomous discovery
benchmark or a statistical seed interval.

## Corrected seed-2026 result

- module dependencies: 5/5 recovered;
- symbol imports: 0/3 recovered;
- baseline node IDs and edge instances lost: 0;
- API errors: 0 across 103 detail calls.

The reviewed compact record is
`eval/reports/s1-code-single-s2026.json`; raw graphs and model logs remain
untracked.
