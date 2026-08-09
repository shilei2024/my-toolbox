import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the Vercel deployment compatible while also emitting the minimal
  // Node runtime used by the Tencent Cloud production container.
  output: "standalone",
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
