-- 0003_brand_brain.sql

-- caption: one piece of written copy (a caption) and its brand score. Who wrote it is
-- in `source`: session (written in a build session), owner, owner_edit, or api.
-- text_hash makes importing the same caption twice a no-op (idempotent).
CREATE TABLE caption (
    id             bigserial PRIMARY KEY,
    text           text NOT NULL,
    text_hash      text NOT NULL UNIQUE,
    pillar         text,
    product        text,
    source         text NOT NULL DEFAULT 'session'
                   CHECK (source IN ('session', 'owner', 'owner_edit', 'api')),
    fact_check     boolean NOT NULL DEFAULT false,
    score          int NOT NULL,
    blocked        boolean NOT NULL,
    score_reasons  jsonb NOT NULL DEFAULT '[]'::jsonb,
    parent_id      bigint REFERENCES caption(id),  -- set when this is your edit of another
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- quiz_answer: your pick on one voice-quiz pair. Answering again replaces the old pick.
CREATE TABLE quiz_answer (
    pair_id     text PRIMARY KEY,
    dimension   text NOT NULL,
    choice      text NOT NULL CHECK (choice IN ('a', 'b', 'both', 'neither')),
    value       text,            -- the style value you picked, e.g. 'story' or 'short'
    answered_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE caption     ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_answer ENABLE ROW LEVEL SECURITY;
