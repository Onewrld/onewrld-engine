-- Affiliate Portal: video storage (Supabase Storage) and who can touch which file.
-- Two private folders ("buckets"):
--   uploads  raw clips. Each affiliate uploads only into their own sub-folder (<their id>/...)
--            and can only see their own. The owner sees all.
--   packs    finished posts made by the engine. An affiliate can only open a pack file
--            that was assigned to them. The owner sees all.
-- Nobody but the engine (which uses the service key) can change or delete files.
-- Per-file size limit: on the free plan Supabase caps uploads at 50 MB whatever is set
-- here. After upgrading to Pro, raise MAX_UPLOAD_MB in portal/config.js (D-062).

INSERT INTO storage.buckets (id, name, public)
VALUES ('uploads', 'uploads', false), ('packs', 'packs', false)
ON CONFLICT (id) DO NOTHING;

CREATE POLICY "upload into own folder {{schema}}" ON storage.objects FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'uploads'
                AND (storage.foldername(name))[1] = auth.uid()::text
                AND {{schema}}.is_member());

CREATE POLICY "read own uploads {{schema}}" ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'uploads'
           AND ((storage.foldername(name))[1] = auth.uid()::text OR {{schema}}.is_owner()));

CREATE POLICY "read assigned packs {{schema}}" ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'packs' AND ({{schema}}.is_owner() OR EXISTS (
        SELECT 1 FROM {{schema}}.packs p JOIN {{schema}}.assignments a ON a.pack_id = p.id
        WHERE a.affiliate_id = auth.uid() AND (p.video_key = storage.objects.name
                                               OR p.thumb_key = storage.objects.name))));
