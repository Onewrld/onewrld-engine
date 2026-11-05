-- 0006_hooks_formats.sql
-- Hooks (the opening line of a video) live in the caption table with kind='hook', so they
-- share scoring, approval and feedback. hook_type: statement, detail, icarus, ...
ALTER TABLE caption ADD COLUMN kind text NOT NULL DEFAULT 'caption'
    CHECK (kind IN ('caption', 'hook'));
ALTER TABLE caption ADD COLUMN hook_type text;

-- Which format a clip was filmed as (from the shot list code in its file name, e.g. F06_...)
ALTER TABLE asset ADD COLUMN format_id text;

-- Which hook and format each finished video used: what the learning loop compares later.
ALTER TABLE render ADD COLUMN hook_id bigint REFERENCES caption(id);
ALTER TABLE render ADD COLUMN format_id text;
