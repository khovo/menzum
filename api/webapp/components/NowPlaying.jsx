/**
 * NowPlaying.jsx
 * --------------
 * Slides up from the bottom when a track is dispatched to the user's chat.
 *
 * States:
 *   sending  → "🎵 Sending to your chat..."  (animated pulse)
 *   sent     → "✅ Check your Al-Madih chat!" (2s, then auto-dismiss)
 *   error    → "❌ <error message>"          (4s, then auto-dismiss)
 */

import { useEffect, useState } from 'react';

export default function NowPlaying({ track, status, error, onDismiss }) {
  const [exiting, setExiting] = useState(false);

  // Auto-dismiss after a delay depending on status
  useEffect(() => {
    if (status === 'sent' || status === 'error') {
      const delay = status === 'error' ? 4000 : 2200;
      const t = setTimeout(() => {
        setExiting(true);
        setTimeout(onDismiss, 280);   // wait for exit animation
      }, delay);
      return () => clearTimeout(t);
    }
  }, [status, onDismiss]);

  if (!track) return null;

  const label =
    status === 'sending'
      ? 'Sending to your chat...'
      : status === 'sent'
      ? 'Check your Al-Madih chat!'
      : error || 'Something went wrong.';

  const icon =
    status === 'sending' ? '🎵' :
    status === 'sent'    ? '✅' :
    '❌';

  const statusColor =
    status === 'error' ? '#ff8080' :
    status === 'sent'  ? '#5ee87a' :
    'var(--gold-primary)';

  return (
    <div className="now-playing-overlay" aria-live="polite">
      <div className={`now-playing-sheet ${exiting ? 'exit' : ''}`}>
        <div className="now-playing-icon">
          <span style={{ fontSize: 18 }}>{icon}</span>
        </div>

        <div className="now-playing-text">
          <div className="now-playing-status" style={{ color: statusColor }}>
            {label}
          </div>
          <div className="now-playing-name">{track.name}</div>
        </div>

        {/* Tap to dismiss early */}
        <button
          onClick={() => { setExiting(true); setTimeout(onDismiss, 280); }}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', fontSize: 18, padding: '4px',
            lineHeight: 1,
          }}
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}
