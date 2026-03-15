/**
 * hooks/useTelegram.js
 * --------------------
 * Initialises the Telegram WebApp SDK and exposes everything the app needs.
 *
 * Graceful dev-mode fallback: when opened in a normal browser (not Telegram),
 * returns dummy data so the UI renders without crashing.
 */

import { useState, useEffect, useCallback } from 'react';

export function useTelegram() {
  const [webApp,   setWebApp]   = useState(null);
  const [initData, setInitData] = useState('');
  const [tgUser,   setTgUser]   = useState(null);
  const [isReady,  setIsReady]  = useState(false);

  useEffect(() => {
    const tg = typeof window !== 'undefined' ? window?.Telegram?.WebApp : null;

    if (tg) {
      // ── Production: running inside Telegram ─────────────────────────────
      tg.ready();                           // tell Telegram the app is loaded
      tg.expand();                          // request full-screen mode
      tg.setHeaderColor('#080d1a');         // match --bg-base
      tg.setBackgroundColor('#080d1a');

      // Disable the native Telegram close-confirmation (we handle our own UX)
      tg.enableClosingConfirmation?.();

      setWebApp(tg);
      setInitData(tg.initData || '');
      setTgUser(tg.initDataUnsafe?.user || null);
    } else {
      // ── Dev mode: running in a browser ──────────────────────────────────
      console.warn('[useTelegram] Not running inside Telegram. Using dev fallback.');
      setInitData('dev_mode');
      setTgUser({ id: 0, first_name: 'Developer', username: 'dev' });
    }

    setIsReady(true);
  }, []);

  // Convenience: show a native Telegram alert
  const showAlert = useCallback((message) => {
    if (webApp?.showAlert) {
      webApp.showAlert(message);
    } else {
      alert(message);
    }
  }, [webApp]);

  // Convenience: trigger haptic feedback on track play
  const hapticImpact = useCallback((style = 'medium') => {
    webApp?.HapticFeedback?.impactOccurred?.(style);
  }, [webApp]);

  return { webApp, initData, tgUser, isReady, showAlert, hapticImpact };
}
