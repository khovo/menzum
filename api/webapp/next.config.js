/** @type {import('next').NextConfig} */
const nextConfig = {
  // NO basePath here. Vercel's routing layer in vercel.json strips /webapp
  // from incoming requests before they reach Next.js, so Next.js always sees
  // paths starting from /. Using basePath here AND a route in vercel.json
  // produces a circular rewrite: /webapp → /webapp → 404.

  reactStrictMode: true,
};

module.exports = nextConfig;
