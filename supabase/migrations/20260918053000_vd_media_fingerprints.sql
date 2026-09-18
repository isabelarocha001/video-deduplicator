-- ============================================================
-- video-deduplicator schema (independent from luxa_*)
-- Prefix: vd_
-- ============================================================

CREATE TABLE IF NOT EXISTS public.vd_media (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  storage_path  text,
  original_name text,
  media_type    text NOT NULL CHECK (media_type IN ('image', 'video', 'audio', 'unknown')),
  mime_type     text,
  size_bytes    bigint,
  duration_ms   integer,
  width         integer,
  height        integer,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  status        text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'ready', 'duplicate', 'error')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.vd_media IS
  'Media registry for video-deduplicator project (not Luxa).';

CREATE INDEX IF NOT EXISTS vd_media_status_idx ON public.vd_media (status);
CREATE INDEX IF NOT EXISTS vd_media_created_idx ON public.vd_media (created_at DESC);

-- Fingerprints: one row per (media_id, algorithm, version)
CREATE TABLE IF NOT EXISTS public.vd_media_fingerprints (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id          uuid NOT NULL REFERENCES public.vd_media(id) ON DELETE CASCADE,
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
  CONSTRAINT vd_media_fingerprints_uniq UNIQUE (media_id, algorithm, version)
);

COMMENT ON TABLE public.vd_media_fingerprints IS
  'Fingerprints for video-deduplicator. Service-role only.';

CREATE INDEX IF NOT EXISTS vd_fp_media_idx ON public.vd_media_fingerprints (media_id);
CREATE INDEX IF NOT EXISTS vd_fp_algorithm_version_idx ON public.vd_media_fingerprints (algorithm, version);

CREATE UNIQUE INDEX IF NOT EXISTS vd_fp_exact_sha256_uidx
  ON public.vd_media_fingerprints (exact_sha256)
  WHERE exact_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS vd_fp_pdq_hash_idx
  ON public.vd_media_fingerprints (pdq_hash)
  WHERE pdq_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS vd_fp_sscd_hnsw_idx
  ON public.vd_media_fingerprints
  USING hnsw (sscd_embedding extensions.vector_cosine_ops)
  WHERE sscd_embedding IS NOT NULL;

-- Audit of detection decisions
CREATE TABLE IF NOT EXISTS public.vd_duplicate_checks (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id             uuid NOT NULL REFERENCES public.vd_media(id) ON DELETE CASCADE,
  candidate_media_id   uuid REFERENCES public.vd_media(id) ON DELETE SET NULL,
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

COMMENT ON TABLE public.vd_duplicate_checks IS
  'Duplicate detection audit for video-deduplicator. Service-role only.';

CREATE INDEX IF NOT EXISTS vd_dup_media_idx ON public.vd_duplicate_checks (media_id);
CREATE INDEX IF NOT EXISTS vd_dup_candidate_idx
  ON public.vd_duplicate_checks (candidate_media_id) WHERE candidate_media_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS vd_dup_decision_created_idx
  ON public.vd_duplicate_checks (decision, created_at DESC);

-- RLS: internal only
ALTER TABLE public.vd_media ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vd_media_fingerprints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vd_duplicate_checks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vd_media_deny_all ON public.vd_media;
CREATE POLICY vd_media_deny_all ON public.vd_media
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS vd_fp_deny_all ON public.vd_media_fingerprints;
CREATE POLICY vd_fp_deny_all ON public.vd_media_fingerprints
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

DROP POLICY IF EXISTS vd_dup_deny_all ON public.vd_duplicate_checks;
CREATE POLICY vd_dup_deny_all ON public.vd_duplicate_checks
  FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);

-- updated_at trigger (reuse function if exists)
CREATE OR REPLACE FUNCTION public.vd_set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS vd_media_updated_at ON public.vd_media;
CREATE TRIGGER vd_media_updated_at
  BEFORE UPDATE ON public.vd_media
  FOR EACH ROW EXECUTE FUNCTION public.vd_set_updated_at();

DROP TRIGGER IF EXISTS vd_media_fingerprints_updated_at ON public.vd_media_fingerprints;
CREATE TRIGGER vd_media_fingerprints_updated_at
  BEFORE UPDATE ON public.vd_media_fingerprints
  FOR EACH ROW EXECUTE FUNCTION public.vd_set_updated_at();
