# ADR 0022: Gallery mainland access via Tencent self-hosting

## Status

Superseded by ADR-0023 (2026-08-09) — Gallery stays on Vercel; Tencent self-hosting is withdrawn.

## Why

The Gallery production hostname previously resolved directly to Vercel. The deployment can be healthy outside
mainland China while users in mainland China cannot reliably open it. Gallery needs a domestic, operator-controlled
entrypoint without changing its public URL, shared Cookie domain, BFF HMAC contract, or Generation Service API.

## Decision

Build Gallery Web with Next.js `output: "standalone"`, run it as a least-privilege Docker container on the existing
Tencent Cloud host, and route `gallery.mindfulpenpal.com` through the existing Caddy instance. The Gallery container
uses the same public HTTPS origins for Flask introspection and Generation API calls; Docker host mappings keep those
trusted calls on the server/Caddy path. Vercel remains available as a rollback deployment but no longer owns the
production Gallery DNS record.

## Alternatives Considered

1. **Leave the hostname on Vercel.** Lowest immediate effort, but does not address the observed mainland reachability
   failure.
2. **Tencent Caddy reverse-proxies Vercel.** Quick but retains the Vercel runtime dependency and adds a cross-border
   request for every Gallery response.
3. **Move all sites immediately from Vercel.** Could address wider mainland availability concerns but is a materially
   larger migration than the Gallery incident and is not required for this repair.

## Future Impact

The container pattern is reusable for other Next.js BFF modules and preserves provider-neutral service boundaries.
The main site's separate deployment remains a distinct availability risk and should be assessed independently.

## Performance

Browser-to-Gallery requests terminate in Tencent Cloud. Gallery-to-Generation API and session introspection remain
inside the server's trusted routing path, removing the former browser-to-Vercel dependency and avoiding an external
round trip for these calls. The Gallery runtime is capped at 512 MB and has a health check.

## Cost

This reuses the existing CVM and Caddy container; incremental cost is CPU/RAM and normal server egress only. It avoids
adding a separate international relay or CDN solely for Gallery HTML/BFF traffic. COS public-delivery costs remain
governed by the COS/CDN configuration and are not changed by this decision.

## Security

The public hostname retains HTTPS, CSP and standard browser security headers. The container is non-root, read-only
except for bounded tmpfs caches, not directly published, and is only reachable through Caddy. Internal Gallery calls
retain the existing HMAC context and Flask introspection secret; credentials remain solely in the root-owned server
environment file.

## Rollback Plan

Restore the `gallery` DNS CNAME to the documented Vercel target, wait for its short TTL, and stop only the `gallery`
container. Do not delete Caddy data, Docker volumes, database data, Redis data, or COS objects. The Vercel deployment
remains the known-good fallback while the server image/configuration is corrected.
