# Benchmark suites and third-party data

The package ships only the self-authored `synthetic-smoke-v1` fixture. It is
licensed under the same MIT license as DeepRefine-Skill and exists to test the
evaluator; its scores are not a model-quality claim.

Real mini suites are prepared locally from an upstream file supplied by the
user. DeepRefine-Skill records the source SHA-256 and selected sample IDs, but
does not redistribute the original text.

## Re-DocRED

- Paper: https://arxiv.org/abs/2205.12696
- Repository: https://github.com/tonytan48/Re-DocRED
- Expected input: the official revised dev JSON (`dev_revised.json`), with
  `rel_info.json` in the same directory when human-readable relation names are
  available.

Review and comply with the dataset repository's current terms and the terms of
its underlying Wikipedia/Wikidata content before use.

## 2WikiMultiHopQA

- Paper: https://arxiv.org/abs/2011.01060
- Repository: https://github.com/Alab-NII/2wikimultihop
- Expected input: an official JSON split, or the compatible
  `DeepRefine/benchmark/2wikimultihopqa.json` file.

The evaluator treats `evidences` as query-relevant reasoning paths only. They
are not an exhaustive gold graph, so the 2Wiki suite never reports full-graph
edge precision.

Generated prepared-suite directories retain source paths, hashes, provenance,
and paper links in `suite.json` and `suite.lock.json`. Those generated
directories should not be redistributed without checking the upstream terms.
