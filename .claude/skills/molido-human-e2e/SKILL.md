---
name: molido-human-e2e
description: Human-like end-to-end application testing and production quality gate. Use for real user journeys, UI interaction, authentication, forms, persistence, permissions, network failures, lifecycle, responsive behavior, accessibility, runtime errors, performance, regression, and release readiness.
---
# MOLIDO HUMAN E2E v2 PRO

Test software as a real human user, not only through unit/API tests.

## Rules
- Never claim PASS unless actually executed.
- Never invent evidence or hide failures.
- Never disable failing tests or weaken assertions to obtain PASS.
- Never deploy known blocking defects.
- Build success is not application success.

## Workflow
OPEN → OBSERVE → INTERACT → INPUT → SUBMIT → WAIT → VERIFY → NAVIGATE → COMPLETE

## Coverage
Test applicable: launch, authentication, logout, session refresh/restart, navigation/deep links, forms, primary business workflow, success/failure paths, network loss/timeout/recovery, persistence, permissions, responsive layouts, accessibility, runtime errors, performance, and regression.

## Persistence
Create → Save → Leave → Restart → Return → Verify.

## Failure protocol
FAIL → STOP → CAPTURE EVIDENCE → REPRODUCE → ROOT CAUSE → FIX → RETEST → DEPENDENT TESTS → REGRESSION.

## Release gate
If an applicable critical gate fails, PRODUCTION = BLOCKED. N/A requires a written reason.

## Evidence
Use real screenshots, traces, console/network logs, reports, and executed test output. No fabricated evidence.

## Final report
Application / Version / Commit / Platform / Environment / each applicable gate PASS|FAIL|N/A / Blocking Issues / Non-Blocking Issues / Evidence / FINAL STATUS / PRODUCTION READY|BLOCKED.
