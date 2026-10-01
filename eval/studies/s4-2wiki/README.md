# S4 — 2WikiMultihopQA Downstream Evaluation

## Question

Does applying graph refinement improve downstream answers for the same
question under a fixed reader protocol?

## Corrected protocol

1. Run the fixed reader on the frozen baseline graph.
2. Apply refinement actions.
3. Run the same reader again on the refined graph with the same retrieval and
   answer settings.
4. Score paired before/after predictions.

The historical first-hop vs last-expanded-hop comparison is not a pre/post
refinement experiment and is excluded from headline results.

## Primary metrics

- Exact Match and token F1 before/after;
- paired improved / regressed / unchanged question counts.

Evidence recall is optional and requires a validated entity/relation alignment.
