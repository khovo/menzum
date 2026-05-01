import { useState, useEffect } from 'react';

export function useTelegram() {
  const [tg, setTg] = useState(null);
  const [user, setUser] = useState(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.Telegram && window.Telegram.WebApp) {
      const webApp = window.Telegram.WebApp;

      webApp.ready();

      try {
        webApp.expand();
      } catch (error) {
        console.warn('[useTelegram] Failed to expand WebApp:', error);
      }

      try {
        webApp.setHeaderColor('#080d1a');
        webApp.setBackgroundColor('#080d1a');
        if (webApp.enableClosingConfirmation) {
          webApp.enableClosingConfirmation();
        }
      } catch (error) {
        console.warn('[useTelegram] Failed to apply UI styles:', error);
      }

      setTg(webApp);
      setUser(webApp.initDataUnsafe?.user || null);
    } else {
      console.warn('[useTelegram] Not running inside Telegram. Using dev fallback.');
      setUser({ id: 0, first_name: 'Developer', username: 'dev' });
    }

    setIsReady(true);
  }, []);

  const close = () => {
    if (tg) {
      tg.close();
    }
  };

  const queryId = tg?.initDataUnsafe?.query_id || null;

  return { tg, user, isReady, queryId, close };
}
