import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The browser calls /api/*; Next forwards it to the backend. Start the backend with
  // `cd api && uv run uvicorn index:app --reload --port 8000` (index:app serves everything under /api).
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
