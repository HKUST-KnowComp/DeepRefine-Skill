# Reproducibility matrix

This table records what is known from run artifacts and distinguishes it from
metadata recovered later from surviving local checkouts. Large datasets, raw
model output, indexes, and credentials are intentionally not committed.

| Stage | Input and sample | Code provenance | Model / seed | Primary metric | Result / status |
|---|---|---|---|---|---|
| S1 | DeepRefine-Skill v0.2.0; 5 module + 3 symbol gaps | source/gold `ff4a094`; runtime Skill `9261ec4`; engine `b783b11`, all recorded | Qwen3-32B + Qwen3-Embedding-8B; seed 2026 | strict module recovery | `s1-code-single-s2026.json`; complete |
| S2 | urllib3, requests, python-dateutil, click; 35 dependency + 142 symbol targets | repository SHAs recovered from surviving checkouts; historical results did not embed runtime revisions | historical generation metadata incomplete; executions 2026–2029 | pooled strict module recovery | `s2-code-multirepo.json`; offline strict rescore complete |
| S3 | Re-DocRED dev SHA-256 `051ee1d...016f`; 50 documents × 3 targets × open/closed | Skill `89116ff`; engine `b783b11`, clean and recorded for all 100 conditions | Qwen3-32B + Qwen3-Embedding-8B; seed 2026 | strict relation-label recovery | `s3-redocred-s2026.json`; complete |
| S4 | 2Wiki dev SHA-256 `48b9bdc...11a6`; 64 questions, 16/type | engine `b783b11` observed at acceptance; evaluated Stage 4 worktree captured by `7212246`, but per-case files did not embed Git SHAs | Qwen3-32B + Qwen3-Embedding-8B; seed 2026 | paired pre/post EM and token F1 | `s4-2wiki-s2026.json`; complete |

## Interpretation boundaries

- S1 is guided completion and a single execution, not autonomous discovery or
  a statistical interval.
- S2 reuses historical candidate graphs and applies the corrected strict
  matcher offline. Missing historical revision fields are marked missing rather
  than reconstructed as if they had been recorded at run time.
- S3 endpoint-pair coverage is diagnostic only. Free-form relation labels do
  not count as strict Re-DocRED semantic recovery.
- S4 uses the corrected baseline-reader → action apply → rebuilt-index
  post-reader pipeline. The historical first-hop/expanded-hop comparison
  remains invalidated. Git revisions were not embedded per case, so the
  acceptance-time engine checkout and post-run commit that captured the
  evaluated worktree are labelled as such rather than claimed as runtime pins.

The JSON companion, `reproducibility-matrix.json`, is the machine-readable
source for automated completeness checks.
