-- Link media to auth users + public read for published content
ALTER TABLE public.vd_media
  ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.vd_media
  ADD COLUMN IF NOT EXISTS caption text;

ALTER TABLE public.vd_media
  ADD COLUMN IF NOT EXISTS thumb_url text;

ALTER TABLE public.vd_media
  ADD COLUMN IF NOT EXISTS public_url text;

CREATE INDEX IF NOT EXISTS vd_media_user_idx ON public.vd_media (user_id);

-- Profiles for social display
CREATE TABLE IF NOT EXISTS public.vd_profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username text UNIQUE,
  display_name text,
  bio text,
  avatar_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.vd_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vd_profiles_public_read ON public.vd_profiles;
CREATE POLICY vd_profiles_public_read ON public.vd_profiles
  FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS vd_profiles_own_write ON public.vd_profiles;
CREATE POLICY vd_profiles_own_write ON public.vd_profiles
  FOR ALL TO authenticated
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Soften vd_media RLS: public can read ready media; owners can manage own
DROP POLICY IF EXISTS vd_media_deny_all ON public.vd_media;

DROP POLICY IF EXISTS vd_media_public_read ON public.vd_media;
CREATE POLICY vd_media_public_read ON public.vd_media
  FOR SELECT TO anon, authenticated
  USING (status IN ('ready', 'duplicate') OR user_id = auth.uid());

DROP POLICY IF EXISTS vd_media_owner_insert ON public.vd_media;
CREATE POLICY vd_media_owner_insert ON public.vd_media
  FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS vd_media_owner_update ON public.vd_media;
CREATE POLICY vd_media_owner_update ON public.vd_media
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS vd_media_owner_delete ON public.vd_media;
CREATE POLICY vd_media_owner_delete ON public.vd_media
  FOR DELETE TO authenticated
  USING (auth.uid() = user_id);

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.vd_handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.vd_profiles (id, username, display_name)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'username', split_part(NEW.email, '@', 1)),
    COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1))
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS vd_on_auth_user_created ON auth.users;
CREATE TRIGGER vd_on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.vd_handle_new_user();
