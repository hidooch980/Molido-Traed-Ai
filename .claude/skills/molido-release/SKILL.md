---
name: molido-release
description: Production release gate combining build, static checks, tests, security, application E2E, regression, runtime and deployment verification.
---
# MOLIDO RELEASE
Run applicable gates: build, typecheck, lint, unit, integration, API, database, security, application E2E, human E2E, permissions, persistence, responsive/accessibility, performance, runtime errors, regression, final review. Any required FAIL means PRODUCTION = BLOCKED. Record commit/version, commands, evidence, failures, known issues, and final decision.
