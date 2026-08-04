BEGIN;

CREATE TYPE ai.asset_deletion_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');

CREATE TABLE ai.user_profiles (
  user_id integer PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  display_name varchar(80) NOT NULL CHECK (char_length(btrim(display_name)) BETWEEN 1 AND 80),
  avatar_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai.asset_deletion_tasks (
  image_id uuid PRIMARY KEY REFERENCES ai.images(id) ON DELETE CASCADE,
  status ai.asset_deletion_status NOT NULL DEFAULT 'pending',
  available_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error text,
  locked_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ai_asset_deletion_due
  ON ai.asset_deletion_tasks (available_at, image_id)
  WHERE status IN ('pending', 'failed');

CREATE INDEX ix_ai_asset_deletion_stalled
  ON ai.asset_deletion_tasks (locked_at, image_id)
  WHERE status = 'running';

CREATE INDEX ix_ai_gallery_feed_v2
  ON ai.images (published_at DESC, id DESC)
  WHERE visibility = 'public' AND moderation_status = 'approved' AND deleted_at IS NULL;

CREATE INDEX ix_ai_images_creator_created_v2
  ON ai.images (creator_user_id, created_at DESC, id DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX ix_ai_favorites_user_created_v2
  ON ai.favorites (user_id, created_at DESC, image_id DESC);

CREATE INDEX ix_ai_likes_user_created_v2
  ON ai.likes (user_id, created_at DESC, image_id DESC);

CREATE FUNCTION ai.adjust_image_counter() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  target_image_id uuid;
  delta integer;
  counter_name text := TG_ARGV[0];
BEGIN
  IF TG_OP = 'INSERT' THEN
    target_image_id := NEW.image_id;
    delta := 1;
  ELSE
    target_image_id := OLD.image_id;
    delta := -1;
  END IF;

  IF counter_name = 'like_count' THEN
    UPDATE ai.images SET like_count = GREATEST(0, like_count + delta) WHERE id = target_image_id;
  ELSIF counter_name = 'favorite_count' THEN
    UPDATE ai.images SET favorite_count = GREATEST(0, favorite_count + delta) WHERE id = target_image_id;
  ELSIF counter_name = 'download_count' THEN
    UPDATE ai.images SET download_count = GREATEST(0, download_count + delta) WHERE id = target_image_id;
  ELSE
    RAISE EXCEPTION 'Unsupported image counter: %', counter_name;
  END IF;

  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_ai_likes_counter
  AFTER INSERT OR DELETE ON ai.likes
  FOR EACH ROW EXECUTE FUNCTION ai.adjust_image_counter('like_count');

CREATE TRIGGER trg_ai_favorites_counter
  AFTER INSERT OR DELETE ON ai.favorites
  FOR EACH ROW EXECUTE FUNCTION ai.adjust_image_counter('favorite_count');

CREATE TRIGGER trg_ai_downloads_counter
  AFTER INSERT OR DELETE ON ai.download_logs
  FOR EACH ROW EXECUTE FUNCTION ai.adjust_image_counter('download_count');

UPDATE ai.images image
SET
  like_count = (SELECT count(*) FROM ai.likes item WHERE item.image_id = image.id),
  favorite_count = (SELECT count(*) FROM ai.favorites item WHERE item.image_id = image.id),
  download_count = (SELECT count(*) FROM ai.download_logs item WHERE item.image_id = image.id);

CREATE TRIGGER trg_ai_user_profiles_updated BEFORE UPDATE ON ai.user_profiles
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_asset_deletion_tasks_updated BEFORE UPDATE ON ai.asset_deletion_tasks
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();

COMMIT;
