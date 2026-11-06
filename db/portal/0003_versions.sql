-- Affiliate Portal: several versions per post, so affiliates never post identical videos.
-- The engine renders a main version plus alternates (different hook, look, crop). When the
-- owner sends one post to several people, approve_pack hands out the versions in rotation:
-- person 1 gets the main, person 2 the first alternate, and so on. Identical uploads across
-- accounts can be flagged as unoriginal by TikTok/Instagram (D-065).

ALTER TABLE {{schema}}.packs ADD COLUMN alt_video_keys text[] NOT NULL DEFAULT '{}';
ALTER TABLE {{schema}}.packs ADD COLUMN alt_hooks text[] NOT NULL DEFAULT '{}';
ALTER TABLE {{schema}}.packs ADD CONSTRAINT packs_one_per_submission UNIQUE (submission_id);

-- When the engine started editing an upload (to spot runs that crashed mid-edit).
ALTER TABLE {{schema}}.submissions ADD COLUMN claimed_at timestamptz;

ALTER TABLE {{schema}}.assignments ADD COLUMN video_key text;
ALTER TABLE {{schema}}.assignments ADD COLUMN hook_text text;

CREATE OR REPLACE FUNCTION {{schema}}.approve_pack(p_pack bigint, p_affiliates uuid[]) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = {{schema}} AS $$
DECLARE pk packs%ROWTYPE; n integer; already integer; versions integer;
BEGIN
    IF NOT is_owner() THEN RAISE EXCEPTION 'only the owner can approve'; END IF;
    SELECT * INTO pk FROM packs WHERE id = p_pack FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'pack % not found', p_pack; END IF;
    IF pk.status = 'rejected' THEN RAISE EXCEPTION 'pack % was rejected', p_pack; END IF;
    UPDATE packs SET status = 'approved', reviewed_at = now() WHERE id = p_pack;
    SELECT count(*) INTO already FROM assignments WHERE pack_id = p_pack;
    versions := 1 + coalesce(array_length(pk.alt_video_keys, 1), 0);
    INSERT INTO assignments (pack_id, affiliate_id, caption_final, video_key, hook_text)
    SELECT p_pack, x.id, affiliate_caption(pk.caption_base, x.discount_code, x.ref_link),
           CASE WHEN x.v = 0 THEN pk.video_key ELSE pk.alt_video_keys[x.v] END,
           CASE WHEN x.v = 0 THEN pk.hook_text ELSE coalesce(pk.alt_hooks[x.v], pk.hook_text) END
      FROM (SELECT pr.*, ((row_number() OVER (ORDER BY pr.display_name, pr.id) - 1 + already) % versions)::int AS v
              FROM profiles pr
             WHERE pr.id = ANY(p_affiliates) AND pr.active
               AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.pack_id = p_pack AND a.affiliate_id = pr.id)) x
    ON CONFLICT (pack_id, affiliate_id) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

-- Affiliates may open exactly the version assigned to them.
DROP POLICY "read assigned packs {{schema}}" ON storage.objects;
CREATE POLICY "read assigned packs {{schema}}" ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'packs' AND ({{schema}}.is_owner() OR EXISTS (
        SELECT 1 FROM {{schema}}.assignments a
        WHERE a.affiliate_id = auth.uid() AND a.video_key = storage.objects.name)));
