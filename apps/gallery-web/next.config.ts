import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep authenticated data out of Cache Components; revisit only after the
  // pending Next security patch is available and the caching model is reviewed.
  cacheComponents: false,
  // The shared Flask session is issued on 127.0.0.1 during local end-to-end
  // development, so Gallery must be reachable on that hostname as well.
  allowedDevOrigins: ["127.0.0.1"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
