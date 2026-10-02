# Benchmark data attribution and licensing

DeepRefine-Skill's benchmark commands support small, reproducible subsets of
third-party datasets. The project does not relicense those datasets. Keep the
original notices when downloading, preparing, sharing, or publishing results.

The package itself includes only `synthetic-smoke-v1`, a generated fixture used
to test the evaluator and report pipeline. It is covered by this repository's
MIT license and is not evidence of real-world graph quality.

## Recommended suites

### Re-DocRED

- Purpose in DeepRefine-Skill: intrinsic entity and relation quality.
- Source: [tonytan48/Re-DocRED](https://github.com/tonytan48/Re-DocRED)
- Paper: [Revisiting DocRED – Addressing the False Negative Problem in
  Relation Extraction](https://arxiv.org/abs/2205.12696)
- Upstream repository license: MIT.
- Provenance: the corpus derives from DocRED, Wikipedia, and Wikidata. Cite the
  upstream paper and preserve any source attribution that accompanies the
  downloaded data.

### 2WikiMultiHopQA

- Purpose in DeepRefine-Skill: downstream multi-hop evidence retrieval,
  reasoning-path coverage, and answer quality.
- Source:
  [Alab-NII/2wikimultihop](https://github.com/Alab-NII/2wikimultihop)
- Paper: [Constructing A Multi-hop QA Dataset for Comprehensive Evaluation of
  Reasoning Steps](https://arxiv.org/abs/2011.01060)
- Upstream repository license: Apache-2.0. The paper is published under
  CC BY 4.0.
- Provenance: passages and evidence also derive from Wikipedia and Wikidata.
  Preserve their attribution when redistributing prepared data.

### MultiHop-RAG

- Purpose in DeepRefine-Skill: optional, slower cross-document RAG evaluation.
- Source: [yixuantt/MultiHop-RAG](https://github.com/yixuantt/MultiHop-RAG)
- Paper: [MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for
  Multi-Hop Queries](https://arxiv.org/abs/2401.15391)
- Upstream dataset license: ODC-BY.
- Provenance: its knowledge base contains news articles from third-party
  publishers. Review the original URLs and applicable content rights before
  redistributing article text.

## Safe distribution pattern

Prefer committing a preparation manifest containing upstream IDs, suite
version, profile, selection rules, and checksums. Download the source data from
its official location at preparation time. Do not copy a third-party subset
into a wheel or source distribution unless its license and required notices
have been reviewed.
