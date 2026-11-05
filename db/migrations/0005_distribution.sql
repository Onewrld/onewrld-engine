-- 0005_distribution.sql

-- post: one finished video scheduled for one platform. It moves through:
--   planned   -> waiting for your approval
--   approved  -> ready; goes in that day's posting kit (or, later, to the posting service)
--   posted    -> live (external_url/external_id recorded)
--   rejected  -> you said no
--   skipped   -> its day passed without it being posted
-- idempotency_key = platform + render, so the same video can never be scheduled twice on
-- the same platform.
CREATE TABLE post (
    id               bigserial PRIMARY KEY,
    render_id        bigint NOT NULL REFERENCES render(id),
    asset_id         bigint NOT NULL REFERENCES asset(id),
    platform         text NOT NULL,
    caption_text     text NOT NULL,
    title            text,
    link_url         text,
    scheduled_at     timestamptz NOT NULL,
    status           text NOT NULL DEFAULT 'planned'
                     CHECK (status IN ('planned', 'approved', 'posted', 'rejected', 'skipped')),
    adapter          text NOT NULL DEFAULT 'manual',
    external_id      text,
    external_url     text,
    posted_at        timestamptz,
    idempotency_key  text NOT NULL UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX post_schedule_idx ON post (platform, scheduled_at);
CREATE INDEX post_asset_idx ON post (platform, asset_id, scheduled_at);

ALTER TABLE post ENABLE ROW LEVEL SECURITY;
