---
name: ponytail
description: Token- and complexity-conscious engineering workflow that prefers existing platform capabilities, project code, and the smallest safe implementation before adding dependencies or abstractions.
---
# PONYTAIL INTEGRATION
Before adding a package, framework, abstraction, helper, or service:
1. Search the project for an existing capability.
2. Check the platform/runtime standard library and native APIs.
3. Check whether the current dependency set already solves it.
4. Compare maintenance, bundle size, runtime, security, and token/context cost.
5. Choose the smallest solution that remains production-safe.

Do not remove useful abstractions merely to make code shorter. Correctness, security, maintainability, and testability outrank token minimization.

Boundary: Ponytail optimizes implementation complexity; it does not replace testing, security, or release gates.
