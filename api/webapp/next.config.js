/** @type {import('next').NextConfig} */
const nextConfig = {
  // All pages served under /webapp — Telegram WebApp URL is https://yourapp.vercel.app/webapp
  basePath: '/webapp',

  // Allow the Mini App to be iframed by Telegram
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'ALLOWALL' },
          {
            key: 'Content-Security-Policy',
            value: "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org",
          },
        ],
      },
    ];
  },

  reactStrictMode: true,
};

module.exports = nextConfig;
