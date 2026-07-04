import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  compress: true,

  images: {
    formats: ["image/avif", "image/webp"],
    deviceSizes: [640, 750, 1080, 1920],
    minimumCacheTTL: 86400,
  },

  poweredByHeader: false,

  experimental: {
    optimizeCss: false,
  },
};

export default nextConfig;
