# Documentation

## Product and architecture

- [Architecture](ARCHITECTURE.md) — runtime boundaries, ownership, and data flow.
- [Specification](SPEC.md) — product requirements and implementation history.
- [Codex fix plan](CODEX_FIX_PLAN.md) — completed and follow-up hardening work.

## Guides

- [Demo run guide](guides/demo_run_guide.md)
- [Demo runner](guides/demo_runner.md)
- [Demo scorecard template](guides/demo_scorecard_template.md)
- [Self-improvement guide](guides/self_improvement_guide.md)

## Plans

- [Improvement plan](plans/IMPROVEMENT_PLAN.md)

## Developer tools

- `tools/ponytail_audit.py` — heuristic complexity and bloat audit. Run it with:

  ```bash
  ./venv/bin/python3 tools/ponytail_audit.py
  ```

- `tools/install_hook.sh` — optional local Git-hook installer.
