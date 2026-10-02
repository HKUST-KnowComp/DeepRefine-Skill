# Evaluation

This directory contains reproducible evaluation tooling, small tracked
fixtures, and the existing wiki proof-of-concept checks. It is development
infrastructure, not part of the installed `deeprefine_skill` runtime package.

## Layout

- `benchmarking/`: deterministic evaluators and the standalone evaluation CLI.
- `suites/`: small versioned fixtures and suite manifests.
- `studies/`: stable protocols and offline aggregation for individual studies.
- `reports/`: concise, reviewed result summaries.
- `benchmarks/`: wiki proof-of-concept structure and refinement-recall checks.
- `smoke-tests/`: instructions for manual checks in supported agents.
- `data/`: instructions and manifests for external or generated inputs.
- `results/`: schema and storage policy for generated outputs.

Run the lightweight checks from the repository root:

```bash
python -m eval.benchmarking.cli --help
pytest tests/test_benchmark.py
```

The wiki proof-of-concept scripts can also be run directly, for example:

```bash
python eval/benchmarks/kg_structure.py --help
python eval/benchmarks/refinement_recall.py --help
```

The structure metric is local and deterministic. The refinement-recall check
runs the model-backed refinement loop and therefore requires configured model
credentials. See the script help and `smoke-tests/README.md` before use.

Large datasets, cloned repositories, model outputs, and credentials must not
be committed. A result reported in `reports/` must identify its input data,
code revision, protocol, random seed, and metric definition.

Changes to production behavior belong under `deeprefine_skill/`; this directory
should contain only evaluation protocols, fixtures, runners, and reports.
