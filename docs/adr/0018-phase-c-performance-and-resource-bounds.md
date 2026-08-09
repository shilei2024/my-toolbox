# ADR-0018: Phase C Performance, Request Ordering, and Resource Bounds

Status: accepted (2026-08-09)

## Why

Public Gallery interactions invalidated every cached feed page, client polling
could reschedule after unmount, and concurrent Gallery searches could render an
older response last. Anonymous Gallery requests also performed an unnecessary
cross-service session introspection. PDF tools had only an upload-byte limit,
which did not cap page-level CPU and memory work.

## Decision

- Guest artwork detail caches are keyed by slug with a short-lived image-id to
  slug index. Likes, favorites, and downloads invalidate only that detail;
  deletion and moderation continue to invalidate the public feed.
- Gallery Explorer aborts superseded requests and accepts only the newest
  response. Generation Workbench polling checks component liveness before
  reading, writing, or scheduling another timer.
- The Next.js BFF returns an anonymous viewer immediately when the configured
  Flask session cookie is absent. Requests carrying the cookie still use signed
  server-to-server introspection.
- SEO keyset pages increase from 1,000 to a bounded 5,000 entries. Keyset
  cursors are inherently dependent, so this safely reduces round trips instead
  of introducing incorrect offset pagination or speculative parallel scans.
- PDF tools enforce configurable `MAX_PDF_FILES` (10) and `MAX_PDF_PAGES`
  (200) in addition to the app-wide upload-byte limit.

## Alternatives Considered

1. Clear all Feed cache entries after every interaction. It is simple but
   creates avoidable cache churn under normal engagement traffic.
2. Parallelize keyset sitemap pages. A later signed cursor is unavailable until
   the prior page completes; offset pagination would degrade database work and
   risks gaps during publication. Larger bounded batches are safer.
3. Trust upload-size limits for PDF work. A small, deeply complex document can
   still consume disproportionate parsing, rendering, and conversion resources.

## Future Impact

The request-sequence and abort pattern should be reused in any client-side
search or pagination module. New CPU-intensive document tools must use the
shared PDF limit helper or define equivalent resource limits before release.

## Performance

Interaction traffic no longer invalidates unrelated public Feed cache keys.
Missing-session requests avoid one Flask network call. Sitemap fetching requires
at most ten 5,000-entry keyset requests for the 50,000-entry cap.

## Cost

The changes use existing Redis, PostgreSQL, and browser APIs. No new service or
storage is required.

## Security

Cookie detection reads only the cookie name, not its signed value. BFF
introspection remains fail-closed whenever a session cookie exists. PDF limits
reduce denial-of-service exposure without weakening file type validation.

## Rollback Plan

All limits are environment-configurable. If legitimate documents exceed the
defaults, raise the specific cap after measuring memory and conversion time in
staging; do not disable limits globally. Client cancellation and cache changes
are backward-compatible and require no database migration.
