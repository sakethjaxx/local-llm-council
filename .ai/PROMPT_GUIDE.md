# Prompt Guide for AI Agents

## Good implementation request

State the goal, affected user flow, constraints, and validation target.

```text
Add <outcome> to <user flow>. Keep local-first defaults unchanged, preserve
<security/compatibility constraint>, add a regression test in <test file>, and
run the full suite. Do not refactor unrelated modules.
```

## Security-focused request

```text
Audit <route/input/rendering path> for data egress, secret persistence, path
escape, and HTML injection. Implement only the smallest safe fix, prove the
negative invariant with a test, and report commands/output.
```

## Refactoring request

```text
Simplify <specific module/function> without changing public behavior. First
list the invariants and callers. Keep the patch scoped; do not split frontend
files or orchestrator flow unless explicitly asked. Run focused and full tests.
```

## Avoid

- “Improve the architecture” without naming a measurable problem.
- Requests that silently enable remote fetch, web search, cloud models, or Python execution.
- Broad cleanup mixed with a behavior or security fix.

## Council quality requests

For stronger local outcomes, choose the Quality run control: it combines a
RAM-fitted mixed roster, the quality token budget, and Deep Debate. Confirm the
displayed concurrent-RAM estimate when selecting models manually; the chairman
runs in a later phase, so it is checked independently from the analyst trio.
