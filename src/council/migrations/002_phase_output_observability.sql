-- Add per-output observability for retry and truncation diagnostics.
ALTER TABLE phase_outputs ADD COLUMN finish_reason TEXT;
ALTER TABLE phase_outputs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;
