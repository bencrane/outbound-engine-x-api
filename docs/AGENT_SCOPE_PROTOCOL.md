# Agent Scope Protocol (Default Wrapper)

Use this protocol at the top of every stage prompt sent to implementation agents.

## Scope Lock (Non-Negotiable)

- Execute only the requested stage.
- Touch only files explicitly listed in `ALLOWED_FILES`.
- Do not modify any file outside `ALLOWED_FILES` without explicit approval.
- If a required change appears to need an additional file, stop and report it as `scope_change_required` with rationale.

## Allowed Files Contract

Prompt must include:

```text
ALLOWED_FILES:
- <absolute-or-repo-relative-file-1>
- <absolute-or-repo-relative-file-2>
...
```

Rules:

- `ALLOWED_FILES` is the full write allowlist.
- New files are allowed only if their exact paths are pre-listed in `ALLOWED_FILES`.
- No opportunistic refactors.
- No unrelated formatting changes.

## Stage Boundaries

- Do not execute future stages early.
- Do not expand feature scope beyond explicit stage goals.
- Defer ambiguous or contract-missing items as `blocked_contract_missing`.

## Commit/Push Policy

- Never commit or push unless explicitly instructed in the stage prompt.
- When instructed to commit, include only stage-relevant files.
- Exclude unrelated working-tree changes.

## Required Output Format (Every Stage)

1. Files changed (must be a subset of `ALLOWED_FILES`)
2. Endpoints/methods added or adjusted
3. Tests run + exact commands + totals
4. Blockers/contract gaps
5. Readiness verdict for this stage only

## Violation Handling

If scope is violated:

- Immediately report:
  - violating file paths
  - why they were touched
  - corrective plan
- Do not proceed to next stage until scope is re-approved.

## Default Prompt Prefix (Template)

```text
Apply docs/AGENT_SCOPE_PROTOCOL.md strictly.

ALLOWED_FILES:
- <file1>
- <file2>
- <file3>

Any change outside ALLOWED_FILES is prohibited unless you stop and request approval with `scope_change_required`.
```

