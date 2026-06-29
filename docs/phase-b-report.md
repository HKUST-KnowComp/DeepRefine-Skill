# Phase B Report: Real Graphify KG Verification

Date: 2026-06-19

## Summary

Phase B verified that our synthetic fixtures (`fixtures/synth-minimal.json`) are schema-compatible with real graphify output. We installed graphifyy 0.8.42, ran `graphify update .` on the DeepRefine-Skill codebase to generate a 361-node, 646-edge AST-only knowledge graph, compared it against our synthetic data, found and fixed 3 validator issues, and confirmed the CLI harness works correctly on real data.

## Environment

| Item | Value |
|------|-------|
| graphifyy version | 0.8.42 |
| Python | 3.14 (venv) |
| Command used | `graphify update .` |
| Mode | AST-only (tree-sitter, no LLM) |
| Output | `graphify-out/graph.json` |

## Key Findings

### 1. graphify CLI command structure

The CLI does NOT use `graphify .` directly. Two separate commands:
- `graphify extract <path>` — full extraction (AST + semantic LLM), needs API key
- `graphify update <path>` — AST-only re-extraction, no LLM, no API key

`update` is the correct choice for CI/smoke tests and deterministic verification.

### 2. Schema differences found and fixed

Our `scripts/validate_graph_schema.py` had 3 issues against real graphify output:

| Issue | Our expectation | Real behavior | Fix |
|-------|----------------|---------------|-----|
| Edge key name | `edges` only | `links` (graphify uses `links`) | Accept either `edges` or `links` |
| `input_tokens` | Required | Absent in AST-only mode | Made optional |
| `output_tokens` | Required | Absent in AST-only mode | Made optional |

After fixes, both synthetic and real graphs pass validation.

### 3. Structural comparison

| Dimension | synth-minimal.json | real (graphify update) |
|-----------|-------------------|----------------------|
| Nodes | 10 | 361 |
| Edges | 11 | 646 |
| EXTRACTED | 8 (73%) | 646 (100%) |
| INFERRED | 3 (27%) | 0 (0%) |
| Node types | code, document | code, document, **rationale** |
| Node extra fields | — | `_origin`, `norm_label` |
| Edge fields | identical | identical |
| Top-level keys | edges, nodes, hyperedges, input/output_tokens | links, nodes, hyperedges, directed, multigraph, graph, built_at_commit |

**Key insight**: `graphify update` is pure AST extraction — all edges are EXTRACTED with confidence 1.0. No INFERRED edges without `graphify extract` + LLM backend. Our synthetic data includes both types, which is correct for testing harness logic that handles mixed confidence.

**New node type**: `rationale` — graphify extracts rationale nodes from comments and docstrings. Our synthetic data didn't include this type. This is fine — the harness doesn't depend on node type.

### 4. CLI verification on real KG

All CLI commands work correctly on the real knowledge graph:

| Command | Result | Notes |
|---------|--------|-------|
| `validate_graph_schema.py` | ✅ Pass | After fixes |
| `review` | ✅ [MEDIUM] | Both nodes existed in real KG |
| `apply` | ✅ Applied | Edge written with INFERRED confidence (0.9) |

The review gate correctly assessed MEDIUM confidence (nodes exist but no literal source evidence for the relation) and `apply` successfully wrote the new edge with `confidence: INFERRED`.

## Changes Made

| File | Change | Reason |
|------|--------|--------|
| `.gitignore` | Added `.venv/` and `graphify-out/` | Local dev artifacts |
| `scripts/validate_graph_schema.py` | Accept `links` as edge key; make `input_tokens`/`output_tokens` optional | Match real graphify output |

## Coverage Gap: EXTRACTED-only vs INFERRED edges

### graphify's two extraction modes

| Command | AST | LLM | API Key | Edge types | Confidence |
|---------|-----|-----|---------|------------|------------|
| `graphify update .` | ✅ tree-sitter | ❌ | Not needed | EXTRACTED only | All 1.0 |
| `graphify extract .` | ✅ tree-sitter | ✅ Claude/Gemini/OpenAI | Required | EXTRACTED + INFERRED | 0.4–1.0 |

`graphify extract` sends code chunks to an LLM which infers semantic relationships — e.g., "this function probably depends on that module" or "this class implements that design pattern". These INFERRED edges have sub-1.0 confidence and are the **primary target of DeepRefine's Reafiner refinement loop**.

### What we verified vs what we didn't

| Aspect | Status | Notes |
|--------|--------|-------|
| Schema structure (field names, types) | ✅ Verified | Both modes use identical schema |
| Harness logic (validate, review, apply) | ✅ Verified | Harness is schema-agnostic |
| EXTRACTED-only KG handling | ✅ Verified | `graphify update` output |
| INFERRED edge refinement on real KG | ❌ Not tested | Requires `graphify extract` + API key |

The synthetic fixtures (`synth-minimal.json`) include 3 hand-crafted INFERRED edges, so the harness logic for mixed-confidence graphs IS tested — just not against a real graphify LLM-extracted KG.

### How to close this gap

A contributor with an Anthropic, Gemini, or OpenAI API key can run:
```bash
graphify extract . --backend claude   # or gemini, openai, deepseek
```
This will produce a `graph.json` with both EXTRACTED and INFERRED edges. Then re-run the Phase B CLI verification steps to confirm harness behavior on a full-extraction KG.

For CI/automated testing without API keys, `graphify update .` + our synthetic fixtures together provide adequate coverage.

## Implications for Phase C (Copilot CLI)

1. **Schema alignment confirmed** — our synthetic data and real graphify data share the same structural contract. Fixtures are valid test data.
2. **INFERRED edges gap** — if Phase C needs INFERRED edges for realistic retrieval testing, we need `graphify extract` with an API key (Anthropic or Gemini).
3. **Node naming** — real graphify node IDs use `deeprefine_skill_<module>_<function>` pattern with normalization. Trace files need node names that actually exist in the KG.
4. **Rationale nodes** — real KG has rationale nodes from comments. These are an important part of the retrieval surface that our synthetic data doesn't model. Consider adding rationale nodes to `synth-minimal.json` for Phase C.

## Files Produced

- `graphify-out/graph.json` — 361-node, 646-edge real KG (local only, gitignored)
- `graphify-out/GRAPH_REPORT.md` — graphify's own report
- `graphify-out/graph.html` — visualization
- `graphify-out/cache/` — graphify cache directory
