import type { NextConfig } from "next";

const apiUrl = process.env.FLOWSENTRY_API_URL || "http://127.0.0.1:8712";

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  async rewrites() {
    // Proxy the FastAPI backend on the same origin so session cookies,
    // CSRF cookies and the SSE stream never face CORS issues.
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
