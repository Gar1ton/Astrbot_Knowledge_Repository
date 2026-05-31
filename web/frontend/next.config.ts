import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";
const API_PORT = process.env.KR_API_PORT || "6520";
const API_HOST = process.env.KR_API_HOST || "127.0.0.1";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(isDev ? {} : { output: "export" as const }),
  images: { unoptimized: true },
  async rewrites() {
    if (!isDev) return [];
    return [
      {
        source: "/api/:path*",
        destination: `http://${API_HOST}:${API_PORT}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
