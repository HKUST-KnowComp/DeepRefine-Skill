# DeepRefine Skill for Codex

DeepRefine-Skill can be installed as a Codex skill. This makes `$deeprefine`
available in Codex while preserving the dry-run-first DeepRefine workflow.

## Install

From the Graphify / LLM-Wiki knowledge-base project root:

```bash
pip install deeprefine-cli
deeprefine codex install --project
```

This installs:

```text
.agents/skills/deeprefine/
|-- SKILL.md
|-- references/
|   |-- reafiner-workflow.md
|   |-- llm-prompts.md
|   `-- trace-and-commands.md
`-- agents/
    `-- openai.yaml
```

For all projects:

```bash
deeprefine codex install --user
```

User-wide installation writes to:

```text
~/.codex/skills/deeprefine/
|-- SKILL.md
|-- references/
|   |-- reafiner-workflow.md
|   |-- llm-prompts.md
|   `-- trace-and-commands.md
`-- agents/
    `-- openai.yaml
```

After upgrading `deeprefine-cli`, rerun the install command to refresh the local
skill files.

## Use in Codex

Start Codex in the KB project root, then invoke:

```text
$deeprefine
```

or:

```text
/deeprefine
```

The Codex skill:

1. Runs `deeprefine history sync-memory`.
2. Processes pending query history from `graphify-out/.deeprefine/history.jsonl`.
3. Uses Graphify retrieval and the session model for the Reafiner loop.
4. Generates proposed `<refinement>` actions when refinement is needed.
5. Runs `deeprefine loop validate` and `deeprefine review`.
6. Stops before graph writes and asks for explicit approval.

## Review and Apply

Review-only mode:

```text
$deeprefine review the proposed actions
```

Apply mode must be explicit and should happen only after a review:

```text
Apply the approved DeepRefine actions from the valid trace.
```

The skill then runs:

```bash
deeprefine loop validate --trace-file <trace> --refinement-file <actions>
deeprefine apply --trace-file <trace> --refinement-file <actions>
deeprefine loop finish --trace-file <trace> --refinement-file <actions>
```

If the review contains LOW-confidence actions, Codex must not use
`--allow-low-confidence` unless the current user message explicitly accepts that
risk.

## Uninstall

Project scope:

```bash
deeprefine codex uninstall --project
```

User scope:

```bash
deeprefine codex uninstall --user
```

## Troubleshooting

- If `$deeprefine` is not available, restart or reload Codex after installation.
- If the skill cannot find `graphify-out/graph.json`, start Codex from the KB
  project root.
- If `deeprefine` is not found, reinstall with `pip install deeprefine-cli` or
  `pip install -e /path/to/DeepRefine-Skill`.
