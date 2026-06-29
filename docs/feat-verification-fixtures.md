# feat/verification-fixtures — Submission Notes

## What This Branch Does

Adds a **verification harness** for the DeepRefine-Skill project: test fixtures,
a schema validator, and end-to-end verification data.  These let anyone quickly
check that the Python CLI (`deeprefine review`, `deeprefine apply`, etc.) and
agent-mode Reafiner loop behave correctly — on both synthetic and real graphify
knowledge graphs.

## Why

Before this branch, the only way to test the harness was to install graphify on
a real codebase, generate a full KG, and run the CLI blind.  There were no
fixtures, no schema checks, and no documented verification procedure.
Collaborators adding a new platform adapter (Codex, Copilot, Gemini) had no
quick way to confirm their changes didn't break the core Python enforcement
layer.

## What's Included

### 1. Synthetic Knowledge Graph (`fixtures/synth-minimal.json`)

A 10-node, 11-edge hand-crafted KG in graphify's schema.  It models the
DeepRefine-Skill codebase with enough structure to exercise both Reafiner
paths:

| Path | Condition | Behaviour |
|------|-----------|-----------|
| Early exit | Query answerable from existing edges | 1 step → JUDGE Yes → FINISH |
| Refinement | Query requires a deliberately missing edge | ≥2 steps → JUDGE No → ABDUCE → REFINE → HARD STOP |

### 2. Trace Fixtures

| File | Purpose |
|------|---------|
| `trace-valid.json` | 2-step refinement path — exercises full ABDUCE → REFINE flow |
| `trace-valid-early-exit.json` | 1-step early exit — `early_exit: true` |
| `trace-invalid-order.json` | Malformed trace — used to test `loop validate` rejection |

### 3. Refinement Action Fixtures

| File | Purpose |
|------|---------|
| `refinement-good.txt` | Valid `insert_edge()` action; both nodes exist in `synth-minimal.json` |
| `refinement-ambiguous.txt` | Action with bare/unresolvable node names — triggers LOW confidence |
| `refinement-invalid.txt` | No `<refinement>` block — tests parse error handling |

### 4. Schema Validator (`scripts/validate_graph_schema.py`)

Standalone script that checks a `graph.json` against graphify's expected
schema.  Validates:

- Top-level keys (`nodes`, `hyperedges`, `edges`/`links`)
- Node required fields (`id`, `label`, `source_file`)
- Edge required fields (`source`, `target`, `relation`, `confidence`, `confidence_score`, `source_file`)
- Confidence values (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`)
- Edge source/target referential integrity

Usage:
```bash
python scripts/validate_graph_schema.py path/to/graph.json
# Exit 0 = valid, exit 1 = errors
```

### 5. Documentation

| File | Audience |
|------|----------|
| `docs/verification-data.md` | Detailed design of the synthetic KG, query scenarios, quick-start commands |
| `docs/phase-b-report.md` | Real graphify KG verification results, schema differences found and fixed |
| `docs/feat-verification-fixtures.md` | This file — submission notes for reviewers |

### 6. `.gitignore` Updates

Added entries for local dev artifacts that should never be committed:
```
.venv/
graphify-out/
.github/skills/
```

## Quick Start

No external dependencies beyond the `deeprefine` CLI (already installed if you
`pip install -e .`).

```bash
cd /path/to/DeepRefine-Skill

# 1. Validate the synthetic KG schema
python scripts/validate_graph_schema.py fixtures/synth-minimal.json
# → OK: fixtures/synth-minimal.json — 10 nodes, 11 edges

# 2. Test trace validation (positive cases)
python -m deeprefine_skill.cli loop validate \
  --trace-file fixtures/trace-valid-early-exit.json
# → OK

python -m deeprefine_skill.cli loop validate \
  --trace-file fixtures/trace-valid.json \
  --refinement-file fixtures/refinement-good.txt
# → OK

# 3. Test trace validation (negative case — should fail)
python -m deeprefine_skill.cli loop validate \
  --trace-file fixtures/trace-invalid-order.json
# → INVALID + error messages + exit 1

# 4. Test the review gate (dry-run, no graph writes)
mkdir -p /tmp/test_kb/graphify-out
cp fixtures/synth-minimal.json /tmp/test_kb/graphify-out/graph.json

python -m deeprefine_skill.cli review \
  --refinement-file fixtures/refinement-good.txt \
  --trace-file fixtures/trace-valid.json \
  --project-root /tmp/test_kb
# → [MEDIUM] confidence report

# 5. Test the apply gate
python -m deeprefine_skill.cli apply \
  --refinement-file fixtures/refinement-good.txt \
  --trace-file fixtures/trace-valid.json \
  --project-root /tmp/test_kb
# → Applied 1 action(s)

# 6. Test LOW-confidence rejection
python -m deeprefine_skill.cli apply \
  --refinement-file fixtures/refinement-ambiguous.txt \
  --trace-file fixtures/trace-valid.json \
  --project-root /tmp/test_kb
# → Refusing... LOW-confidence + exit 1

# 7. Cleanup
rm -rf /tmp/test_kb
```

## Verification Results

### Phase A — Synthetic Data

All CLI commands (`review`, `apply`, `loop validate`, `loop init`, `loop finish`)
verified against the synthetic 10-node KG.  Harness correctly:

- Validates Reafiner control flow in trace files
- Assigns HIGH/MEDIUM/LOW confidence labels to refinement actions
- Rejects LOW-confidence actions by default
- Allows `--allow-low-confidence` override

### Phase B — Real Graphify KG

Installed graphifyy 0.8.42, ran `graphify update .` on the DeepRefine-Skill
codebase (361 nodes, 646 edges, AST-only).  Found and fixed 3 schema
differences between our expectations and real graphify output:

1. Real graphify uses `"links"` (not `"edges"`) as the edge container key
2. `input_tokens` / `output_tokens` are absent in AST-only mode
3. Real KG includes extra fields: `_origin`, `norm_label`, `directed`, `built_at_commit`

The schema validator was updated to accept both `links` and `edges`, and to
treat `input_tokens`/`output_tokens` as optional.  All CLI commands verified
on the real KG.

### Phase C — Copilot CLI End-to-End

Ran `/deeprefine` in Copilot CLI (DeepSeek v4-flash via BYOK) against the real
361-node KG.  Four paths verified:

| Path | Result |
|------|--------|
| **Refinement** (query not answerable in hop 1) | ✅ Full 8-step loop: JUDGE No → k-hop → JUDGE Yes → ABDUCE → REFINE → VALIDATE → REVIEW → HARD STOP.  `graph.json` unchanged. |
| **Early exit** (query answerable in hop 1) | ✅ JUDGE Yes → FINISH.  No refinement files generated.  `early_exit: true`. |
| **Apply** (user approves refinement) | ✅ `deeprefine apply` writes INFERRED edges to `graph.json`.  `loop finish` marks query refined. |
| **LOW-confidence gate** | ✅ LOW actions rejected (exit 1).  `--allow-low-confidence` overrides (exit 0). |

Key finding: Copilot CLI's LLM agent correctly followed the Reafiner protocol
defined in `SKILL_COPILOT.md` — including the `len(interaction_history) > 1`
branch rule and the HARD STOP safety policy.

## For Collaborators

### Adding a New Platform Adapter

If you're adding a skill for a new platform (Cursor, Codex, etc.), run the
quick-start commands above to confirm your changes don't break the core Python
harness.  The fixtures are framework-agnostic — they test `deeprefine` CLI
commands, not any specific agent framework.

### Validating Your Own KG

```bash
# Against synth-minimal (always works)
python scripts/validate_graph_schema.py fixtures/synth-minimal.json

# Against a real graphify KG
python scripts/validate_graph_schema.py path/to/your/graphify-out/graph.json
```

### Adding New Test Queries

1. Create a new trace fixture following the schema in `trace-valid.json`
2. Add corresponding refinement text if testing the refinement path
3. Run `deeprefine loop validate` to confirm control flow correctness

### Schema Differences to Watch For

When graphify introduces new fields or changes existing ones, the validator
may need updates.  The known differences (Phase B) are already handled.  If
you encounter new ones, update `TOP_LEVEL_REQUIRED`, `TOP_LEVEL_OPTIONAL`, or
`TOP_LEVEL_EDGE_KEYS` in `scripts/validate_graph_schema.py`.

## Files Changed

```
 .gitignore                           |   6 +
 docs/phase-b-report.md               | 121 ++++++++++++++++
 docs/verification-data.md            | 157 ++++++++++++++++++++
 docs/feat-verification-fixtures.md   |  this file
 fixtures/refinement-ambiguous.txt    |   1 +
 fixtures/refinement-good.txt         |   1 +
 fixtures/refinement-invalid.txt      |   3 +
 fixtures/synth-minimal.json          | 193 +++++++++++++++++++++++
 fixtures/trace-invalid-order.json    |  57 +++++++
 fixtures/trace-valid-early-exit.json |  43 ++++++
 fixtures/trace-valid.json            |  87 +++++++++++
 scripts/validate_graph_schema.py     | 141 ++++++++++++++++
 12 files changed, 810 insertions(+)
```
