import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Mirrors vercel.json's production rewrite so local `next dev` routes
  // /api/* the same way Vercel does. Run the backend locally with
  // `cd api && uvicorn index:app --reload --port 8000` (the wrapped
  // /api-mounted app, not `app.main:app` directly) so its routes are
  // reachable at the same /api/* paths this proxies to.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        // compose.yaml sets API_PROXY_DEST=http://api:8000/:path* (the container serves unprefixed routes).
        destination: process.env.API_PROXY_DEST ?? "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
