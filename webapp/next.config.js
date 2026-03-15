/** @type {import('next').NextConfig} */
const nextConfig = {
  // No basePath — this project IS the root. Deployed at https://almadih-app.vercel.app/
  // API calls go to the bot project via NEXT_PUBLIC_API_BASE env var.
  // In Vercel webapp project settings, set:
  //   NEXT_PUBLIC_API_BASE = https://menzum.vercel.app
  reactStrictMode: true,
};

module.exports = nextConfig;
