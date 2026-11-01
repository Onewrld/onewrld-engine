-- 0002_notification.sql
-- notification: a record of every email (later: SMS) the system sent you. It's used to
-- enforce sending caps, so a burst of errors can never flood your inbox.
CREATE TABLE notification (
    id         bigserial PRIMARY KEY,
    channel    text NOT NULL DEFAULT 'email' CHECK (channel IN ('email')),
    subject    text NOT NULL,
    alert_ids  bigint[] NOT NULL DEFAULT '{}',
    sent_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notification_sent_idx ON notification (sent_at);
ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
