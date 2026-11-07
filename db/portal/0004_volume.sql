-- Affiliate Portal, high volume (D-067).
-- The owner approves posts in bulk; the database hands the versions out to the team by itself
-- and keeps every affiliate's queue topped up:
--   * the person who filmed a clip always gets their own post (main version)
--   * the other versions go to whoever has the fewest posts waiting, never two people the same
--     version, and never more than their limit ("max_open", default 5) waiting at once
--   * when someone marks a post as posted, their queue is refilled from approved posts that
--     still have unused versions
-- The old one-post "Approve & send" (approve_pack) still works for hand-picking people.

ALTER TABLE {{schema}}.profiles ADD COLUMN max_open integer NOT NULL DEFAULT 5
    CHECK (max_open BETWEEN 0 AND 50);
CREATE INDEX ON {{schema}}.packs (status, reviewed_at);
CREATE INDEX ON {{schema}}.assignments (pack_id);

-- Internal: give the next unused version of a pack to one affiliate. Not callable from the site.
CREATE FUNCTION {{schema}}.give_version(p_pack bigint, p_affiliate uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE pk packs%ROWTYPE; pr profiles%ROWTYPE; v integer;
BEGIN
    SELECT * INTO pk FROM packs WHERE id = p_pack AND status = 'approved' FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO pr FROM profiles WHERE id = p_affiliate AND active AND role = 'affiliate';
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT count(*) INTO v FROM assignments WHERE pack_id = p_pack;
    IF v >= 1 + coalesce(array_length(pk.alt_video_keys, 1), 0) THEN RETURN false; END IF;
    INSERT INTO assignments (pack_id, affiliate_id, caption_final, video_key, hook_text)
    VALUES (p_pack, pr.id, affiliate_caption(pk.caption_base, pr.discount_code, pr.ref_link),
            CASE WHEN v = 0 THEN pk.video_key ELSE pk.alt_video_keys[v] END,
            CASE WHEN v = 0 THEN pk.hook_text ELSE coalesce(pk.alt_hooks[v], pk.hook_text) END)
    ON CONFLICT (pack_id, affiliate_id) DO NOTHING;
    RETURN FOUND;
END $$;

-- Internal: fill everyone's queue, fairest first. Bounded: at most 1000 handouts per call.
CREATE FUNCTION {{schema}}.fill_queues() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE given integer := 0; aff uuid; pk bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('{{schema}}.fill_queues'));
    FOR i IN 1..1000 LOOP
        aff := NULL; pk := NULL;
        SELECT w.id, q.id INTO aff, pk
          FROM (SELECT pr.id, pr.max_open,
                       (SELECT count(*) FROM assignments a WHERE a.affiliate_id = pr.id AND a.status = 'assigned') AS open,
                       (SELECT max(a.assigned_at) FROM assignments a WHERE a.affiliate_id = pr.id) AS last_at
                  FROM profiles pr WHERE pr.active AND pr.role = 'affiliate') w
          CROSS JOIN LATERAL (
                SELECT p.id FROM packs p
                 WHERE p.status = 'approved'
                   AND (SELECT count(*) FROM assignments a WHERE a.pack_id = p.id)
                       < 1 + coalesce(array_length(p.alt_video_keys, 1), 0)
                   AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.pack_id = p.id AND a.affiliate_id = w.id)
                 ORDER BY p.reviewed_at, p.id LIMIT 1) q
         WHERE w.open < w.max_open
         ORDER BY w.open, w.last_at NULLS FIRST, w.id
         LIMIT 1;
        EXIT WHEN aff IS NULL;
        EXIT WHEN NOT give_version(pk, aff);
        given := given + 1;
    END LOOP;
    RETURN given;
END $$;

-- Owner: approve many posts at once. Returns {"approved": n, "sent": m}.
CREATE FUNCTION {{schema}}.approve_packs(p_packs bigint[]) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE pk packs%ROWTYPE; approved integer := 0; sent integer := 0; uploader uuid;
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can approve'; END IF;
    IF coalesce(array_length(p_packs, 1), 0) > 200 THEN RAISE EXCEPTION 'approve at most 200 posts at once'; END IF;
    FOR pk IN SELECT * FROM packs WHERE id = ANY(p_packs) AND status = 'pending'
               ORDER BY created_at, id FOR UPDATE LOOP
        UPDATE packs SET status = 'approved', reviewed_at = now() WHERE id = pk.id;
        approved := approved + 1;
        SELECT s.affiliate_id INTO uploader FROM submissions s WHERE s.id = pk.submission_id;
        IF give_version(pk.id, uploader) THEN sent := sent + 1; END IF;   -- your own clip, always
    END LOOP;
    sent := sent + fill_queues();
    RETURN jsonb_build_object('approved', approved, 'sent', sent);
END $$;

-- Owner: reject many at once with one reason.
CREATE FUNCTION {{schema}}.reject_packs(p_packs bigint[], p_reason text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE n integer;
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can reject'; END IF;
    UPDATE packs SET status = 'rejected', reject_reason = left(p_reason, 300), reviewed_at = now()
     WHERE id = ANY(p_packs) AND status = 'pending';
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

-- Owner: how many posts one person may have waiting at once (0 = pause them).
CREATE FUNCTION {{schema}}.set_max_open(p_affiliate uuid, p_max integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can change limits'; END IF;
    UPDATE profiles SET max_open = greatest(0, least(50, p_max)) WHERE id = p_affiliate;
    RETURN fill_queues();
END $$;

-- Posting frees a slot, so the queue refills straight away.
CREATE OR REPLACE FUNCTION {{schema}}.mark_posted(p_assignment bigint, p_url text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
BEGIN
    UPDATE assignments SET status = 'posted', posted_at = now(), posted_url = nullif(p_url, '')
     WHERE id = p_assignment AND affiliate_id = auth.uid();
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM fill_queues();
    RETURN true;
END $$;

-- The engine (on the owner's PC) calls this after editing, in case approved posts are waiting.
REVOKE ALL ON FUNCTION {{schema}}.give_version(bigint, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION {{schema}}.fill_queues() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION {{schema}}.approve_packs(bigint[]) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION {{schema}}.reject_packs(bigint[], text) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION {{schema}}.set_max_open(uuid, integer) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION {{schema}}.approve_packs(bigint[]) TO authenticated;
GRANT EXECUTE ON FUNCTION {{schema}}.reject_packs(bigint[], text) TO authenticated;
GRANT EXECUTE ON FUNCTION {{schema}}.set_max_open(uuid, integer) TO authenticated;
