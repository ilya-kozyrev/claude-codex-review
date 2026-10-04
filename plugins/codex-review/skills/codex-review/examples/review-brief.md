# Review: <one line on what the change does> (MR !<n>)

Read-only review: do not edit files and do not create temp files or directories (the sandbox forbids
it). Your final answer is the review. Answer in English.

## Context
<Two to five lines: what the change is for, the decision the author made that you want challenged,
which tests changed their expectations on purpose and why.>

Diff: `git diff <base-sha>..HEAD`.

## Author's test results (do not rerun them)
<The commands the author ran and their outcome: «pytest tests/api: 212 passed, exit 0», lint, type
check. The read-only sandbox cannot run a test suite that writes files.>

## What to check (only this)
1. Completeness: every path that <writes X / checks Y> now <does Z> — routers, services, background jobs.
2. Order of checks: <404 before 403, no write/audit/idempotency key spent before a refusal>.
3. No regression for <roles / callers / existing clients>.
4. Are the changed test expectations a deliberate, documented contract change, not a weakened assertion?

## Output
Findings only: severity, file:line, the concrete case (call sequence), the fix; «confirmed» vs «suspected»;
«no findings» per item with how you checked. Last line: verdict «merge» or «changes requested».
Max ~500 words.
