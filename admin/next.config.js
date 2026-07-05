/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone admin app — deployed as its own Vercel project, own domain.
  // No basePath; this project IS the root of its deployment.
  reactStrictMode: true,
};

module.exports = nextConfig;
