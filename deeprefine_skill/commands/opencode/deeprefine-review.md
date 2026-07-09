---
description: Review existing DeepRefine refinement actions — evidence-aware scoring (HIGH/MEDIUM/LOW) of proposed knowledge graph changes with 5-oracle parallel audit
---

# /deeprefine-review

<command-instruction>
Use the `skill` tool to load the DeepRefine skill:

skill(name="deeprefine")

Execute the REVIEW phase only:
1. Read the latest refinement actions file from `graphify-out/.deeprefine/`
2. Launch 5 parallel oracle subagents reviewing from orthogonal angles (completeness, correctness, safety, graph consistency, edge-case coverage)
3. Score each action (HIGH/MEDIUM/LOW) using evidence-aware review
4. Present results with clear recommendations
5. Write evidence to the ledger

Do NOT apply any changes. Do NOT re-run the judge→abduction→refinement pipeline. This command only reviews existing actions.

<user-request>$ARGUMENTS</user-request>
</command-instruction>
