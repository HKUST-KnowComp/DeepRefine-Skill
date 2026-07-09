---
description: Apply approved DeepRefine refinement actions to the knowledge graph with explicit user confirmation and post-apply auto-verification
---

# /deeprefine-apply

<command-instruction>
Use the `skill` tool to load the DeepRefine skill:

skill(name="deeprefine")

Execute the APPLY phase only:
1. Read the latest refinement actions file from `graphify-out/.deeprefine/`
2. Read the review report to confirm all actions have been reviewed
3. Show exactly what will be applied to `graph.json`
4. **Ask for explicit user confirmation** — do NOT apply without approval
5. Apply approved actions: `deeprefine apply --trace-file ... --refinement-file ...`
6. Run `deeprefine loop finish --trace-file ... --refinement-file ...`
7. **Post-apply verification**: re-query graphify for the original question to confirm the graph mutation was effective
8. Write evidence to the ledger

Do NOT run the judge→abduction→refinement pipeline. Do NOT review — use `/deeprefine-review` for that. This command only applies already-reviewed and explicitly-approved actions.

<user-request>$ARGUMENTS</user-request>
</command-instruction>
