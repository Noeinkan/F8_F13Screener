# RTK — Token-Optimized CLI

**rtk** is a CLI proxy that filters and compresses command outputs, saving 60-90% tokens.

## Rule

Always prefix shell commands with `rtk`:

```bash
# Instead of:              Use:
git status                 rtk git status
git log -10                rtk git log -10
cargo test                 rtk cargo test
docker ps                  rtk docker ps
kubectl get pods           rtk kubectl pods
```

## Meta commands (use directly)

```bash
rtk gain              # Token savings dashboard
rtk gain --history    # Per-command savings history
rtk discover          # Find missed rtk opportunities
rtk proxy <cmd>       # Run raw (no filtering) but track usage
```

## Smart Execution Policy

Use a risk-based command strategy. Do not run broad or expensive commands by default.

### 1) Change Classification

- Low risk: docs, comments, copy, non-runtime config text changes.
- Medium risk: isolated function/module edits with clear local impact.
- High risk: shared core logic, data model changes, parser/storage behavior, or deployment/runtime scripts.

### 2) Validation Escalation Ladder

- Level 0 (no execution): Low-risk changes only.
- Level 1 (targeted checks): Run the smallest relevant check for changed files.
- Level 2 (related tests): Run tests related to touched modules when behavior may affect nearby areas.
- Level 3 (full suite / deploy checks): Run only for high-risk changes or explicit user request.

Never jump directly to Level 3 unless risk is high.

### 3) Python Test Best Practices (This Repo)

- Prefer targeted test file runs first:

```bash
rtk pytest tests/test_storage.py -q --maxfail=1
```

- Then add neighboring test files only if needed.
- Run full suite only when:
	- Shared core modules in `src/core/` changed significantly.
	- Cross-cutting behavior was modified.
	- User explicitly requests full verification.

### 4) Command Output Discipline

- Use concise flags first (`-q`, `--maxfail=1`) where available.
- Do not rerun the same broad command repeatedly without narrowing scope.
- After a failure, rerun only the failed/affected subset unless a full rerun is justified.

### 5) Deploy Script Discipline

- Do not run `deploy.sh` automatically after routine code edits.
- Run deploy checks only when deployment-related files changed or user explicitly requests.
- For deploy debugging, prefer one targeted attempt with focused follow-up checks over repeated full runs.

## Communication

- Use moderately concise communication.
- Routine progress updates: 1-2 sentences.
- Final answers for small changes: one short paragraph plus validation status (when relevant).
- Include: key decision, changed file(s), and result.
- Omit: broad background, repeated plans, and obvious explanations.
- Expand detail only for complex tradeoffs, failures, risks, or when explicitly requested.

## User Preferences

- Prefer rapid iteration for internal tools: use the cheapest useful validation unless risk is high or stronger verification is requested.
- After edits, verify at least one concrete changed marker with a direct read/search or a targeted test before summarizing.
- Keep instructions operational and specific; avoid vague style goals unless they define concrete behavior.
- When writing or updating instructions, include examples or thresholds that another agent can apply directly.

## Instruction Hygiene

- Keep this file repository-wide and durable: include workflow, validation, environment, and architecture rules only.
- Put area-specific rules in path-scoped files under `.github/instructions/*.instructions.md` (for example: frontend, backend, tests, or ML service code).
- Avoid conflicting rules across personal instructions, repository instructions, org-level instructions, `AGENTS.md`, `CLAUDE.md`, and path-specific instruction files.
- Document commands known to work, including prerequisites, expected order, and common timeout or platform caveats.
- Trust documented repo instructions first; search externally only when instructions are incomplete, stale, or contradicted by current code.
