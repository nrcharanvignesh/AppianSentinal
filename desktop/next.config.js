/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  devIndicators: false,
  images: { unoptimized: true },
  generateBuildId: async () => 'appian-sentinel-desktop',
};

module.exports = nextConfig;
