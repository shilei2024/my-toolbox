import type { Pool } from "pg";
import { GalleryError } from "./errors.ts";
import type { ViewerContext } from "./types.ts";

/** Recheck revocable Flask sessions before handling authenticated operations. */
export function accountSessionCheck(pool: Pick<Pool, "query">): (viewer: ViewerContext) => Promise<void> {
  return async (viewer) => {
    if (viewer.role === "guest") return;
    if (!viewer.sessionRef || !Number.isInteger(viewer.authEpoch)) throw rejected();
    const result = await pool.query(
      `SELECT u.is_admin FROM public.users u JOIN public.account_web_sessions s ON s.user_id=u.id
       WHERE u.id=$1 AND u.is_active_user=true AND u.auth_epoch=$2 AND s.auth_epoch=u.auth_epoch
         AND s.token_hash=$3 AND s.revoked_at IS NULL AND s.expires_at > (now() AT TIME ZONE 'UTC')`,
      [viewer.userId, viewer.authEpoch, viewer.sessionRef],
    );
    if (result.rows.length !== 1 || (viewer.role === "admin" && result.rows[0]?.is_admin !== true)) throw rejected();
  };
}
function rejected(): GalleryError { return new GalleryError("authentication_required", "Please sign in again", 401); }
