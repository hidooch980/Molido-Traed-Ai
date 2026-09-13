# MOLIDO Engineering Rules

## Flow
INSPECT → PLAN → IMPLEMENT → TEST → VERIFY → REVIEW → LOCK

## Non-Negotiable
- Never claim success without evidence.
- Never hide failures or weaken tests.
- Never deploy known blocking defects.
- Inspect before modifying; prefer the smallest safe change.
- Do not add dependencies when existing capabilities are sufficient.
- Never expose secrets.
- Run all applicable release gates before production.

## Skill Loading
Skills live in `.claude/skills/`. Load only the skill relevant to the current task:
- Code changes: `molido-quality`; tests: `molido-testing`; failures: `molido-debug`.
- Schema, migrations, journal or production data: `molido-database`.
- Auth, secrets, API exposure: `molido-security`; speed, CPU, memory: `molido-performance`.
- UI work: `molido-design` and `impeccable`. Code minimization: `ponytail`.
- Application verification: `molido-human-e2e`. Before production: `molido-release`.

## Failure
FAIL → CAPTURE EVIDENCE → ROOT CAUSE → FIX → RETEST → REGRESSION → RELEASE CHECK

## Phase Lock
Record changes, tests, evidence, known issues, and commit when appropriate.
