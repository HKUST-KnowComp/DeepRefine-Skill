# Stage 3 Re-DocRED open/closed pilot — 2026-10-02

## Scope and validity

- case: `redocred-0358d1357783` (Abbas Kiarostami);
- three deterministically selected missing relations;
- six refinement runs: three open and three closed;
- seed: 2026;
- common graph: 51 nodes, 47 links, zero passage nodes;
- common graph SHA-256:
  `9958e13afb48981976495c79d9a75798794e281ed45a75a2e3513a26f46ca375`;
- open/closed graph files were byte-identical before refinement;
- open passed 1,988 characters through `original_chunk`; closed passed `None`;
- prompt sentinel smoke passed before the pilot.

This pilot validates the pipeline and accounting.  Three targets are not
enough for a quality or causal conclusion.

## Results

| Condition | Strict relation label | Newly added endpoint pair | API requests | LLM requests | Errors |
|---|---:|---:|---:|---:|---:|
| open | 0/3 | 1/3 | 20 | 8 | 0 |
| closed | 0/3 | 1/3 | 20 | 8 | 0 |

Both conditions acted only on the `The Wind Will Carry Us` → `1999` target.
The gold relation was `publication date`; open proposed `release_year` and
closed proposed `released_in`.  Consequently the endpoint pair was recovered
under the diagnostic lens, but neither action recovered the strict gold label.

The other two targets stopped after a first-hop `Yes` judgement and did not
reach action generation in either condition.  This is shared behavior, but it
limits how much this three-target pilot can reveal about source-text effects.

## Usage

| Condition | Prompt tokens | Completion tokens | Total tokens | Accumulated API time |
|---|---:|---:|---:|---:|
| open | 5,463 | 170 | 5,633 | 40.886 s |
| closed | 5,072 | 239 | 5,311 | 41.752 s |

The open condition used 391 additional prompt tokens across the eight LLM
calls.  Total usage was 40 requests and 0 errors, below the 120-request and
40-LLM-request hard limits.

## Write-back correction discovered by the pilot

The first offline evaluation reported endpoint-pair `0/3` despite both action
logs naming the target entities.  Inspection showed that DeepRefine attached
the new edge to a hash-key duplicate of `The Wind Will Carry Us`, while the
evaluator aligned the gold entity to the original baseline node.

The Stage 3 runner now folds a minted node only when its display label has one
exact baseline match.  It does not guess ambiguous matches or rewrite relation
labels.  Reprocessing the existing actions folded one movie node and remapped
one edge per condition.  No additional API calls were made.  The unfolded
candidate graphs remain in the ignored local artifact directory for audit.

## Revisions and artifacts

- DeepRefine engine used for API calls:
  `b783b114bb5508c8f223ea1262fc3464fc981f32` (clean);
- DeepRefine-Skill API-run revision:
  `77ab522c5ddea6260f3d850484c2f322b2b035cd` (clean);
- entity-fold postprocessing revision:
  `7b3ca93f0cd3af45d637e613a2b5c5714c0c2700` (clean);
- local raw artifact directory:
  `eval/results/s3-redocred-pilot-s2026-20261002/` (ignored).

The local artifact directory contains the common inputs, per-condition
metadata, per-call usage JSONL, refinement logs, unfolded and folded candidate
graphs, evaluator outputs, and `summary.json`.
