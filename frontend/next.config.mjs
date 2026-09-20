const apiInternalUrl = process.env.API_INTERNAL_URL || "http://api:8000";

const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/health", destination: `${apiInternalUrl}/health` },
      { source: "/ready", destination: `${apiInternalUrl}/ready` },
      { source: "/docs", destination: `${apiInternalUrl}/docs` },
      { source: "/openapi.json", destination: `${apiInternalUrl}/openapi.json` },
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
    ];
  },
};
export default nextConfig;
