import { useEffect, useState } from 'react';

export function useTelegram() {
  const [tg, setTg] = useState(null);

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
    } else {
      console.warn('[useTelegram] Not running inside Telegram. Using dev fallback.');
      setTg({
        initData: 'dev_mode',
        initDataUnsafe: {
          user: { id: 0, first_name: 'Developer', username: 'dev' }
        },
        close: () => console.log('[useTelegram] close() called in dev mode')
      });
    }
  }, []);

  return {
    tg,
    user: tg?.initDataUnsafe?.user,
    initData: tg?.initData,
    initDataUnsafe: tg?.initDataUnsafe,
    queryId: tg?.initDataUnsafe?.query_id,
    close: () => tg?.close(),
  };
}
