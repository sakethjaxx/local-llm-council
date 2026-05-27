-- Add durable quality dashboard metrics.
ALTER TABLE runs ADD COLUMN parse_tier TEXT;
ALTER TABLE runs ADD COLUMN phase1_divergence REAL;
ALTER TABLE runs ADD COLUMN specificity_score REAL;
