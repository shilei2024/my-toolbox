BEGIN;

CREATE INDEX ix_ai_images_moderation_created
  ON ai.images (moderation_status, created_at DESC, id DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX ix_ai_audit_created
  ON ai.audit_logs (created_at DESC, id DESC);

COMMIT;
