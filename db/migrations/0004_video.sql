-- 0004_video.sql

-- asset: one raw video file you filmed (identified by its content fingerprint, sha256,
-- so the same file imported twice is recognized as the same asset).
CREATE TABLE asset (
    id          bigserial PRIMARY KEY,
    sha256      text NOT NULL UNIQUE,
    path        text NOT NULL,
    duration    real NOT NULL,
    width       int  NOT NULL,
    height      int  NOT NULL,
    has_audio   boolean NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- render: one finished video made from an asset with specific settings (the "spec").
-- render_key = fingerprint of (asset + settings), so the same render is never made twice.
CREATE TABLE render (
    id          bigserial PRIMARY KEY,
    asset_id    bigint NOT NULL REFERENCES asset(id),
    render_key  text NOT NULL UNIQUE,
    caption_id  bigint REFERENCES caption(id),
    spec        jsonb NOT NULL,
    output_path text,
    qc_passed   boolean,
    qc          jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE asset  ENABLE ROW LEVEL SECURITY;
ALTER TABLE render ENABLE ROW LEVEL SECURITY;
