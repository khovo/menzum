import { Html, Head, Main, NextScript } from 'next/document';

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Telegram Mini App SDK — must load before the React app initialises */}
        <script src="https://telegram.org/js/telegram-web-app.js" />

        {/* Meta */}
        <meta name="description" content="Al-Madih — Menzuma & Nasheed Library" />
        <meta name="theme-color" content="#080d1a" />

        {/* Prevent phone-number detection on iOS */}
        <meta name="format-detection" content="telephone=no" />

        {/*
          viewport: width=device-width keeps the layout from zooming on input
          focus in older iOS WebViews.  The Telegram WebApp container handles
          safe-area insets, but we expose them via CSS env() vars in globals.css.
        */}
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"
        />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
