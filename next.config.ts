import type { NextConfig } from "next";

// Static export for AWS (S3 + CloudFront): build with NEXT_EXPORT=1 to emit
// the `out/` folder. Rewrites are not supported in a static export (see
// node_modules/next/dist/docs/01-app/02-guides/static-exports.md), so in that
// mode CloudFront routes /api/* to API Gateway instead.
const isStaticExport = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = isStaticExport
  ? {
      output: "export",
      // /dashboard -> /dashboard/index.html, which S3 website hosting can serve.
      trailingSlash: true,
      images: { unoptimized: true },
    }
  : {
      // Mirrors vercel.json's production rewrite so local `next dev` routes
      // /api/* the same way Vercel does. Run the backend locally with
      // `cd api && uvicorn index:app --reload --port 8000` (the wrapped
      // /api-mounted app, not `app.main:app` directly) so its routes are
      // reachable at the same /api/* paths this proxies to.
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: "http://localhost:8000/api/:path*",
          },
        ];
      },
    };

export default nextConfig;
