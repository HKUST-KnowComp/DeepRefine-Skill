# S3 — Re-DocRED Relation Recovery

## Question

Can DeepRefine recover a withheld semantic relation between named entities?

## Primary metric

Strict `(head, relation, tail)` recovery over the frozen queried target set.

Endpoint-pair coverage ignores the relation label and is secondary diagnostic
evidence only. It must not be described as semantic edge recovery.

## Open-book issue ledger

The historical nominal-open runs did not deliver passage text to the action
prompt: entity labels were hashed through a different ID namespace than the
`node_id_to_file_id` mapping. Until that product-level mapping is fixed and a
prompt-level test proves the passage is present:

- do not compare nominal open vs closed runs;
- do not claim that source text is ineffective;
- preserve the old artifacts as an invalidated ablation;
- track the fix outside PR-1 if it changes shared DeepRefine behavior.

## Paired-run contract

Stage 3 does not wait for the passage fallback fix.  The tracked adapter in
`open_closed.py` follows the public contract used by the upstream DeepRefine
benchmarks:

- prepare one common entity/relation graph with passage nodes and incident
  links removed;
- deep-copy that same graph for both conditions and record its canonical
  SHA-256;
- pass the Re-DocRED document text explicitly as `original_chunk` for open
  book;
- pass `original_chunk=None` for closed book;
- hold the question and every other refinement setting fixed.

This prevents a future fallback fix from silently leaking passage text into
the closed-book condition.  `tests/test_s3_open_closed.py` verifies the graph
and call-argument contract without constructing a model client or making API
requests.  A separate prompt-level sentinel smoke remains required before a
real-model pilot.

## Context and metadata contract

- source: the UTF-8 corpus file selected by `suite.case.source_files[0]`;
- serialization: sentence tokens joined by one space and sentences joined by
  two newlines, as frozen by suite preparation;
- normalization: trim leading/trailing whitespace;
- budget: first 12,000 Unicode codepoints;
- provenance: record input/selected context hashes, lengths, truncation flag,
  common graph hash, context mode, and the DeepRefine/DeepRefine-Skill commit
  plus dirty state.

All current frozen 50-document corpus files are below this budget; the rule is
still explicit so future inputs cannot change prompt size silently.

## Prompt smoke and pilot gate

`prompt_smoke.py` invokes the real research engine action-prompt method with a
capturing fake generator.  It makes no network request and asserts that the
open prompt contains the sentinel, the closed prompt does not, and replacing
the sentinel leaves byte-identical prompt text.  Run it with:

```bash
python eval/studies/s3-redocred/prompt_smoke.py \
  --deeprefine-repo /path/to/DeepRefine \
  --output eval/studies/s3-redocred/prompt_smoke_result.json
```

The approved scope and request stop limits for the still-unstarted real-model
pilot are recorded in `PILOT_PLAN.md`.

`pilot.py` implements that bounded run.  It prepares one common graph, runs
the three frozen targets in open and closed mode, writes per-call usage and
metadata, stops before requests that exceed the caps, and reports strict
relation-label and newly-added endpoint-pair metrics separately.

Before Graphify serialization it also folds refinement-minted nodes onto a
baseline node only when the display label has one exact match.  Ambiguous and
new entities remain unchanged.  This prevents DeepRefine's hash-key namespace
from hiding an otherwise observable target pair during evaluation.
