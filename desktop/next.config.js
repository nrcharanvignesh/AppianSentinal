/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — Electron serves the built `out/` folder locally in prod.
  output: 'export',
  reactStrictMode: true,
  images: { unoptimized: true },
  // Assets are served from the app root by Electron's tiny static server, so
  // default absolute asset paths ("/_next/...") work.
};

module.exports = nextConfig;
