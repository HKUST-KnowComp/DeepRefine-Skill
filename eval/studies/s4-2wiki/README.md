# S4 — 2WikiMultihopQA Engineering Evaluation

## Purpose

This is a product regression evaluation for the installable DeepRefine
engineering stack (PyPI/pip and agent skills), not a research-paper benchmark.
It asks whether applying graph refinement changes downstream answer quality
without breaking graph integrity, reproducibility, or unattended execution.

The suite is intentionally small and fixed.  It is designed to catch product
regressions and produce inspectable artifacts; it does not claim statistical
significance, confidence intervals, or general benchmark superiority.

## Corrected protocol

1. Run the fixed reader on the frozen baseline graph.
2. Apply refinement actions.
3. Run the same reader again on the refined graph with the same retrieval and
   answer settings.
4. Score paired before/after predictions.

The historical first-hop vs last-expanded-hop comparison is not a pre/post
refinement experiment and is excluded from headline results.

The concrete timeline is enforced by `protocol.py`:

1. copy the frozen graph into an isolated `baseline-reader` sandbox;
2. copy the same frozen graph into an isolated `refinement` sandbox;
3. run the baseline reader read-only with an explicit index rebuild;
4. apply refinement only in the refinement sandbox and snapshot its graph;
5. copy that snapshot into a fresh `post-reader` sandbox;
6. run the same reader configuration in a new process with another explicit
   index rebuild.

Reader results carry `source=reader`; a refinement run's `final_answer` or
`interaction_history` is rejected as a pre/post prediction.  Graph hashes are
checked before and after every reader run, so a reader write is a hard failure.

## Why the historical result is invalid

`DeepRefine.refine()` performs retrieval and answer generation inside its hop
loop.  Error abduction, action generation, and action application happen only
after that loop.  The old evaluator compared the first hop's answer with the
last hop's answer from this one call.  Both answers therefore predate action
application; the observed change measures expanded retrieval, not the effect
of the candidate graph.

This is repairable without changing or duplicating the answer prompt.  The
same engine reader is invoked in two independent runs, once against the frozen
baseline and once against the persisted candidate.  Only the graph path may
differ between their reader configurations.

## Primary metrics

- Exact Match and token F1 before/after;
- paired improved / regressed / unchanged question counts.

Evidence recall is optional and requires a validated entity/relation alignment.

## Tracked code and local artifacts

Tracked protocol code lives only in this directory:

- `protocol.py`: phase ordering and validity gates;
- `worker.py`: one three-process case and its isolated phase subprocesses;
- `batch.py`: resume-safe unattended pilot/full runner;
- `aggregate.py`: offline EM/F1 and detail-row-only usage aggregation;

`batch.py` performs the reusable input preflight itself: suite balance,
suite/source/type metadata, graph presence, and per-case graph hashes.  This
keeps one-shot migration/audit scripts out of the permanent product eval.

Large inputs remain under ignored `eval/data/`.  Corrected run artifacts use
the single ignored root `eval/results/stage4-corrected-20261002/`, split into
`preflight/`, `smoke/`, `pilot/`, and `full/`.  Each batch stores `cases/`, a
resume manifest, per-case logs, raw answers, graph snapshots, reader retrieval
contexts, graph hashes, phase records, and API usage detail rows.

`batch.py` is deliberately non-interactive.  It verifies already completed
cases on restart, refuses to overwrite incomplete case directories, retries a
newly failed case up to three times, and enforces per-case plus global request caps.
An explicit `--retry-incomplete` archives a failed partial case under
`failed-attempts/` before retrying; failed evidence is never silently deleted.

Reader answers use a per-case deterministic response cache keyed by question,
canonical retrieved-context hash, and the complete reader configuration.  It
removes provider wording drift for identical reader inputs while preserving
the first raw response verbatim.  A changed retrieved context always gets a
different key and a fresh model call; cache-hit provenance is stored in each
phase result.

For a zero-action case whose candidate graph is byte-identical to its frozen
baseline, the post reader still starts independently, rebuilds the candidate
index, and records the context returned by that index.  Its scored reader
input is then fixed to the baseline context.  This paired-control rule prevents
remote embedding jitter at the Top-K boundary from being misreported as a
graph-refinement effect; both the raw rebuilt-index context and the effective
paired context remain in `reader-retrieval.json` for audit.
