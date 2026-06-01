#!/bin/bash
# Generated from manual triage of self-review-2026-05-28 reports.
# P0 was empty (SQL params clean, CORS defaults safe, gitignore complete).

# P1 Correctness/Architecture Issues

gh issue create \
  --title "run_store.py: dual migration path (inline ALTER + orphaned migrations/)" \
  --body "run_store.py:169-187 contains 6 inline ALTER TABLE statements that duplicated the now-deleted migrations/001-003.sql files. The migrations/ dir had no runner — orphaned documentation. Deleted in cleanup. Inline _ensure_schema is now sole migration path. Consider adding a schema version table for future migrations." \
  --label "self-review,P1"

gh issue create \
  --title "static/index.html: 42 inline style= attributes bypass design tokens" \
  --body "static/index.html has 42 inline style= occurrences mixing layout (display:none, margin-top) and design values (font-size, color). These bypass CSS variables defined in :root. Extract to named CSS classes. Tracked separately from the larger index.html split task." \
  --label "self-review,P1"

gh issue create \
  --title "static/index.html: 1920 lines — split into html/css/js before further growth" \
  --body "static/index.html is 1920 lines with HTML, CSS, and JS co-located. CLAUDE.md already forbids growing it further before extracting config to presets.json. Next: split into static/app.css + static/app.js + slim index.html. Prerequisite for new UI features." \
  --label "self-review,P2"
