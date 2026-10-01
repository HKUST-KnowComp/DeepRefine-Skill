# Metric policy

Metrics are part of the experiment contract, not presentation knobs. A more
favorable number is acceptable only when it measures a pre-declared property
more faithfully; renaming or relaxing a matcher after seeing outputs is not an
optimization.

## Shared reporting contract

Every headline row records:

- target definition and denominator;
- exact matching rule;
- recovered and still-missing counts;
- regressions or new unverified claims;
- source/data revision and candidate code revision;
- model/configuration identity;
- calls, tokens, errors, and latency;
- whether the run is guided, open-book, and/or downstream.

## Four-stage primary metrics

| Study | Primary | Required counter-metric |
|---|---|---|
| S1 single-repository code | strict module-edge recovery | graph preservation + unverified import claims |
| S2 multi-repository code | pooled strict module-edge recovery | per-repository result + strict symbol recovery |
| S3 Re-DocRED | strict relation-triple recovery | relation-agnostic endpoint-pair coverage |
| S4 2Wiki | paired pre/post EM and token F1 | improved/regressed/unchanged counts |

## Legitimate optimization directions

- Improve target-module provenance for symbol nodes, then measure strict symbol recovery.
- Improve retrieval scope isolation without replacing the complete product graph.
- Repair passage provenance so S3 genuinely supplies open-book context.
- Add a true post-action reader pass for S4.
- Reduce false-positive actions and graph regressions, not merely increase inserts.
- Report efficiency or Pareto trade-offs such as strict recovery per 1K tokens.

## Disallowed ways to obtain a brighter number

- treating missing target fields as wildcards;
- counting endpoint pairs as correct semantic relations;
- comparing different retrieval depths as graph-state before/after;
- selecting only the best seed or run after observing results;
- omitting lost baseline facts or newly introduced unsupported edges.
