-- 004_confidence_metrics
-- Adds trust-signal columns to runs: chairman grounding ratio, aggregate
-- council confidence (0-100), and the per-member stance summary JSON.
ALTER TABLE runs ADD COLUMN grounding_ratio REAL;
ALTER TABLE runs ADD COLUMN council_confidence INTEGER;
ALTER TABLE runs ADD COLUMN stance_summary TEXT;
