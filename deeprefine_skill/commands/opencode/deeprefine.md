---
description: Full DeepRefine workflow — process pending queries through judge→abduction→refinement→review→apply pipeline with 6 OpenCode-native optimizations
---

# /deeprefine

<command-instruction>
Use the `skill` tool to load the DeepRefine skill:

skill(name="deeprefine")

Then execute the full workflow described in the skill. Process all pending queries from `graphify-out/history.jsonl` through the complete judge→abduction→refinement→review→apply pipeline. Leverage all 6 OpenCode-native optimizations: parallel query processing, phase-specific model routing, structured progress tracking, 5-oracle parallel review, post-apply verification, and evidence ledger.

<user-request>$ARGUMENTS</user-request>
</command-instruction>
