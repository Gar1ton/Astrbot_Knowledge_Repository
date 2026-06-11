import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // WSL2/Windows 路径规范化问题：强制本地编译以确保 React Client Manifest 路径一致
  transpilePackages: ["fumadocs-ui", "fumadocs-core"],
  ...(isDev ? {} : { output: "export" as const }),
  images: { unoptimized: true },
  // 开发模式下将 /api/* 反向代理到后端（production static export 会忽略此配置）
  ...(isDev
    ? {
        async rewrites() {
          const host = process.env.KR_API_HOST ?? "127.0.0.1";
          const port = process.env.KR_API_PORT ?? "6520";
          return [
            {
              source: "/api/:path*",
              destination: `http://${host}:${port}/api/:path*`,
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
