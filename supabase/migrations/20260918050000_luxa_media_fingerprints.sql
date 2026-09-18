-- ============================================================
-- 1) luxa_media_fingerprints
-- ============================================================
CREATE TABLE IF NOT EXISTS public.luxa_media_fingerprints (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id          uuid NOT NULL REFERENCES public.luxa_media(id) ON DELETE CASCADE,
  creator_id        uuid NOT NULL REFERENCES public.luxa_creators(id) ON DELETE CASCADE,
  algorithm         text NOT NULL
                      CHECK (algorithm IN ('exact', 'pdq', 'sscd', 'tmk_pdqf', 'audio')),
  version           text NOT NULL,
  exact_sha256      text,
  pdq_hash          bytea,
  pdq_quality       smallint,
  sscd_embedding    extensions.vector(512),
  tmk_fingerprint   bytea,
  tmk_frame_count   integer,
  audio_fingerprint bytea,
  audio_duration_ms integer,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT luxa_media_fingerprints_uniq
    UNIQUE (media_id, algorithm, version)
);

COMMENT ON TABLE public.luxa_media_fingerprints IS
  'Internal perceptual/crypto fingerprints for media deduplication. Service-role only.';

CREATE INDEX IF NOT EXISTS luxa_fp_media_idx
  ON public.luxa_media_fingerprints (media_id);

CREATE INDEX IF NOT EXISTS luxa_fp_creator_idx
  ON public.luxa_media_fingerprints (creator_id);

CREATE INDEX IF NOT EXISTS luxa_fp_algorithm_version_idx
  ON public.luxa_media_fingerprints (algorithm, version);

CREATE UNIQUE INDEX IF NOT EXISTS luxa_fp_exact_sha256_uidx
  ON public.luxa_media_fingerprints (exact_sha256)
  WHERE exact_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS luxa_fp_pdq_hash_idx
  ON public.luxa_media_fingerprints (pdq_hash)
  WHERE pdq_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS luxa_fp_sscd_hnsw_idx
  ON public.luxa_media_fingerprints
  USING hnsw (sscd_embedding extensions.vector_cosine_ops)
  WHERE sscd_embedding IS NOT NULL;

-- ============================================================
-- 2) luxa_duplicate_checks (audit of detection decisions)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.luxa_duplicate_checks (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id             uuid NOT NULL REFERENCES public.luxa_media(id) ON DELETE CASCADE,
  candidate_media_id   uuid REFERENCES public.luxa_media(id) ON DELETE SET NULL,
  pdq_score            real,
  sscd_score            real,
  tmk_score             real,
  audio_score           real,
  exact_match           boolean NOT NULL DEFAULT false,
  final_score           real,
  decision              text NOT NULL
                          CHECK (decision IN ('NEW', 'DUPLICATE', 'POSSIBLE_DUPLICATE', 'ERROR')),
  policy_version        text NOT NULL DEFAULT 'v1',
  detector_versions     jsonb NOT NULL DEFAULT '{}'::jsonb,
  details               jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.luxa_duplicate_checks IS
  'Audit log of duplicate detection decisions. Service-role only.';

CREATE INDEX IF NOT EXISTS luxa_dup_media_idx
  ON public.luxa_duplicate_checks (media_id);

CREATE INDEX IF NOT EXISTS luxa_dup_candidate_idx
  ON public.luxa_duplicate_checks (candidate_media_id)
  WHERE candidate_media_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS luxa_dup_decision_created_idx
  ON public.luxa_duplicate_checks (decision, created_at DESC);

-- ============================================================
-- 3) RLS — fingerprints & checks are internal only
-- ============================================================
ALTER TABLE public.luxa_media_fingerprints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.luxa_duplicate_checks ENABLE ROW LEVEL SECURITY;

-- Deny all for anon/authenticated. service_role bypasses RLS.
DROP POLICY IF EXISTS luxa_fp_deny_all ON public.luxa_media_fingerprints;
CREATE POLICY luxa_fp_deny_all ON public.luxa_media_fingerprints
  FOR ALL TO anon, authenticated
  USING (false)
  WITH CHECK (false);

DROP POLICY IF EXISTS luxa_dup_deny_all ON public.luxa_duplicate_checks;
CREATE POLICY luxa_dup_deny_all ON public.luxa_duplicate_checks
  FOR ALL TO anon, authenticated
  USING (false)
  WITH CHECK (false);

-- Optional: admins (luxa_profiles.role = 'admin') can read for support tooling
DROP POLICY IF EXISTS luxa_fp_admin_read ON public.luxa_media_fingerprints;
CREATE POLICY luxa_fp_admin_read ON public.luxa_media_fingerprints
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.luxa_profiles p
      WHERE p.id = auth.uid() AND p.role = 'admin'
    )
  );

DROP POLICY IF EXISTS luxa_dup_admin_read ON public.luxa_duplicate_checks;
CREATE POLICY luxa_dup_admin_read ON public.luxa_duplicate_checks
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.luxa_profiles p
      WHERE p.id = auth.uid() AND p.role = 'admin'
    )
  );

-- updated_at trigger helper
CREATE OR REPLACE FUNCTION public.luxa_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS luxa_media_fingerprints_updated_at ON public.luxa_media_fingerprints;
CREATE TRIGGER luxa_media_fingerprints_updated_at
  BEFORE UPDATE ON public.luxa_media_fingerprints
  FOR EACH ROW EXECUTE FUNCTION public.luxa_set_updated_at();
