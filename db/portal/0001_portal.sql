-- Affiliate Portal: tables, security rules and actions.
-- {{schema}} is replaced when applied: "public" on Supabase (the website reads it through
-- Supabase's API), a throwaway test schema in tests. Applied with: python -m onewrld portal setup
--
-- Security model (Row Level Security = the database checks every request against these rules):
--   * Nobody can sign up on their own. You invite an email; only invited people get a profile.
--   * An affiliate sees only their own uploads and the posts assigned to them.
--   * Only the owner can approve, reject and assign. Those happen through the functions at
--     the bottom, which check who is calling before they change anything.

-- invite: an email you have invited, with that affiliate's code and link.
CREATE TABLE {{schema}}.invites (
    email          text PRIMARY KEY CHECK (email = lower(email)),
    display_name   text NOT NULL,
    discount_code  text,
    ref_link       text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- profile: a person who can log in (owner or affiliate). id = their Supabase login id.
CREATE TABLE {{schema}}.profiles (
    id             uuid PRIMARY KEY,
    email          text NOT NULL UNIQUE,
    role           text NOT NULL DEFAULT 'affiliate' CHECK (role IN ('owner', 'affiliate')),
    display_name   text NOT NULL,
    discount_code  text,
    ref_link       text,
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- submission: one raw clip an affiliate uploaded. consent_at proves they gave ONEWRLD the
-- right to edit and repost it (required to upload at all).
CREATE TABLE {{schema}}.submissions (
    id             bigserial PRIMARY KEY,
    affiliate_id   uuid NOT NULL REFERENCES {{schema}}.profiles(id),
    storage_key    text NOT NULL UNIQUE,
    original_name  text,
    size_bytes     bigint,
    product_handle text,
    note           text,
    consent_at     timestamptz NOT NULL,
    status         text NOT NULL DEFAULT 'uploaded'
                   CHECK (status IN ('uploaded', 'processing', 'ready', 'failed', 'rejected')),
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- pack: one finished post the system made from a submission (edited video + text),
-- waiting for your decision.
CREATE TABLE {{schema}}.packs (
    id             bigserial PRIMARY KEY,
    submission_id  bigint NOT NULL REFERENCES {{schema}}.submissions(id),
    video_key      text NOT NULL,
    thumb_key      text,
    hook_text      text,
    caption_base   text NOT NULL,
    status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'approved', 'rejected')),
    reject_reason  text,
    reviewed_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- assignment: an approved pack handed to one affiliate, with THEIR caption (their code,
-- their link, the required #ad disclosure). One per pack per affiliate.
CREATE TABLE {{schema}}.assignments (
    id             bigserial PRIMARY KEY,
    pack_id        bigint NOT NULL REFERENCES {{schema}}.packs(id),
    affiliate_id   uuid NOT NULL REFERENCES {{schema}}.profiles(id),
    caption_final  text NOT NULL,
    status         text NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned', 'posted')),
    posted_url     text,
    assigned_at    timestamptz NOT NULL DEFAULT now(),
    posted_at      timestamptz,
    UNIQUE (pack_id, affiliate_id)
);
CREATE INDEX ON {{schema}}.submissions (affiliate_id, created_at);
CREATE INDEX ON {{schema}}.assignments (affiliate_id, status);

-- --- who is asking? -------------------------------------------------------------------------
-- auth.uid() is Supabase's "id of the logged-in person making this request".
CREATE FUNCTION {{schema}}.is_owner() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = {{schema}} AS $$
    SELECT EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'owner' AND active)
$$;

CREATE FUNCTION {{schema}}.is_member() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = {{schema}} AS $$
    SELECT EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND active)
$$;

-- --- invite-only: a new login gets a profile only if its email was invited -----------------
CREATE FUNCTION {{schema}}.handle_new_user() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE inv invites%ROWTYPE;
BEGIN
    SELECT * INTO inv FROM invites WHERE email = lower(NEW.email);
    IF FOUND THEN
        INSERT INTO profiles (id, email, display_name, discount_code, ref_link)
        VALUES (NEW.id, lower(NEW.email), inv.display_name, inv.discount_code, inv.ref_link)
        ON CONFLICT (id) DO NOTHING;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER on_auth_user_created_{{schema}}
    AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION {{schema}}.handle_new_user();

-- --- security rules -----------------------------------------------------------------------
ALTER TABLE {{schema}}.invites     ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{schema}}.profiles    ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{schema}}.submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{schema}}.packs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE {{schema}}.assignments ENABLE ROW LEVEL SECURITY;

CREATE POLICY owner_all ON {{schema}}.invites FOR ALL TO authenticated
    USING ({{schema}}.is_owner()) WITH CHECK ({{schema}}.is_owner());

CREATE POLICY read_self_or_owner ON {{schema}}.profiles FOR SELECT TO authenticated
    USING (id = auth.uid() OR {{schema}}.is_owner());
CREATE POLICY owner_manage ON {{schema}}.profiles FOR UPDATE TO authenticated
    USING ({{schema}}.is_owner()) WITH CHECK ({{schema}}.is_owner());

CREATE POLICY upload_own ON {{schema}}.submissions FOR INSERT TO authenticated
    WITH CHECK (affiliate_id = auth.uid() AND {{schema}}.is_member()
                AND consent_at IS NOT NULL AND status = 'uploaded');
CREATE POLICY read_own_or_owner ON {{schema}}.submissions FOR SELECT TO authenticated
    USING (affiliate_id = auth.uid() OR {{schema}}.is_owner());
CREATE POLICY owner_update ON {{schema}}.submissions FOR UPDATE TO authenticated
    USING ({{schema}}.is_owner()) WITH CHECK ({{schema}}.is_owner());

CREATE POLICY read_assigned_or_owner ON {{schema}}.packs FOR SELECT TO authenticated
    USING ({{schema}}.is_owner() OR EXISTS (
        SELECT 1 FROM {{schema}}.assignments a WHERE a.pack_id = packs.id AND a.affiliate_id = auth.uid()));

CREATE POLICY read_own_or_owner ON {{schema}}.assignments FOR SELECT TO authenticated
    USING (affiliate_id = auth.uid() OR {{schema}}.is_owner());

-- Logged-out visitors get nothing. Logged-in users get only what the rules above allow.
GRANT USAGE ON SCHEMA {{schema}} TO authenticated;
-- Supabase grants every new table to anon and authenticated by default; take that back first,
-- then grant only what the website needs (the security rules above still apply on top).
REVOKE ALL ON ALL TABLES IN SCHEMA {{schema}} FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA {{schema}} FROM anon;
GRANT SELECT ON {{schema}}.profiles, {{schema}}.packs, {{schema}}.assignments TO authenticated;
GRANT SELECT, INSERT ON {{schema}}.submissions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON {{schema}}.invites TO authenticated;
GRANT UPDATE ON {{schema}}.profiles, {{schema}}.submissions TO authenticated;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA {{schema}} TO authenticated;

-- --- actions (the buttons) ------------------------------------------------------------------
-- The caption an affiliate posts: the approved text, then their link/code, then the
-- disclosure the FTC requires for paid affiliates.
CREATE FUNCTION {{schema}}.affiliate_caption(base text, code text, link text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT base
        || CASE WHEN coalesce(link, '') <> '' THEN E'\n\n' || link ELSE '' END
        || CASE WHEN coalesce(code, '') <> '' THEN E'\n' || 'Code ' || code || ' at checkout.' ELSE '' END
        || E'\n\n#ad I earn a commission on sales from my link.'
$$;

-- [Approve] + the people you ticked. Safe to press twice: nobody gets a pack twice.
CREATE FUNCTION {{schema}}.approve_pack(p_pack bigint, p_affiliates uuid[]) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE pk packs%ROWTYPE; n integer;
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can approve'; END IF;
    SELECT * INTO pk FROM packs WHERE id = p_pack FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'pack % not found', p_pack; END IF;
    IF pk.status = 'rejected' THEN RAISE EXCEPTION 'pack % was rejected', p_pack; END IF;
    UPDATE packs SET status = 'approved', reviewed_at = now() WHERE id = p_pack;
    INSERT INTO assignments (pack_id, affiliate_id, caption_final)
    SELECT p_pack, pr.id, affiliate_caption(pk.caption_base, pr.discount_code, pr.ref_link)
      FROM profiles pr WHERE pr.id = ANY(p_affiliates) AND pr.active
    ON CONFLICT (pack_id, affiliate_id) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

-- [Reject] with a reason (feeds the Brand Brain later).
CREATE FUNCTION {{schema}}.reject_pack(p_pack bigint, p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can reject'; END IF;
    UPDATE packs SET status = 'rejected', reject_reason = p_reason, reviewed_at = now()
     WHERE id = p_pack AND status = 'pending';
END $$;

-- Affiliate's [Mark posted] (+ optional link to their post). Only on their own assignment.
CREATE FUNCTION {{schema}}.mark_posted(p_assignment bigint, p_url text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
BEGIN
    UPDATE assignments SET status = 'posted', posted_at = now(), posted_url = nullif(p_url, '')
     WHERE id = p_assignment AND affiliate_id = auth.uid();
    RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION {{schema}}.approve_pack(bigint, uuid[]) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION {{schema}}.reject_pack(bigint, text) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION {{schema}}.mark_posted(bigint, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION {{schema}}.approve_pack(bigint, uuid[]) TO authenticated;
GRANT EXECUTE ON FUNCTION {{schema}}.reject_pack(bigint, text) TO authenticated;
GRANT EXECUTE ON FUNCTION {{schema}}.mark_posted(bigint, text) TO authenticated;
