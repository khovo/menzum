/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  basePath: '/webapp', // ይሄ በጣም ወሳኝ ነው!
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'ALLOW-FROM https://web.telegram.org/',
          },
          {
            key: 'Content-Security-Policy',
            value: "frame-ancestors 'self' https://web.telegram.org/ https://oauth.telegram.org/;",
          }
        ],
      },
    ]
  },
}

module.exports = nextConfig
