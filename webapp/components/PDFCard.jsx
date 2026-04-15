import { useState } from 'react';

export default function PDFCard({ pdf, isFav, onRead, onDeliver, onFavorite, index = 0 }) {
  const [delivering, setDelivering] = useState(false);
  const [delivered,  setDelivered]  = useState(false);

  async function handleDeliver(e) {
    e.stopPropagation();
    if (delivering || delivered) return;
    setDelivering(true);
    await onDeliver(pdf);
    setDelivering(false);
    setDelivered(true);
    setTimeout(() => setDelivered(false), 3000);
  }

  return (
    <div
      className="track-item pdf-card-item"
      style={{ animationDelay: `${index * 35}ms` }}
      onClick={() => onRead(pdf)}
      role="button"
      aria-label={`Read ${pdf.title}`}
    >
      {/* PDF icon thumb */}
      <div className="track-thumb pdf-card-thumb">
        <svg width="20" height="22" viewBox="0 0 20 22" fill="none">
          <path d="M12 1H3a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7z"
            stroke="var(--gold-primary)" strokeWidth={1.5} fill="rgba(232,184,75,0.08)"/>
          <path d="M12 1v6h6" stroke="var(--gold-primary)" strokeWidth={1.5} strokeLinejoin="round"/>
          <path d="M6 13h8M6 17h5" stroke="var(--gold-muted)" strokeWidth={1.2} strokeLinecap="round"/>
        </svg>
      </div>

      {/* Info */}
      <div className="track-info">
        <div className="track-name">{pdf.title}</div>
        <div className="track-sub">📄 PDF</div>
      </div>

      {/* Actions */}
      <div className="track-actions" onClick={(e) => e.stopPropagation()}>
        <button
          className={`btn-icon ${isFav ? 'is-fav' : ''}`}
          onClick={(e) => { e.stopPropagation(); onFavorite(pdf); }}
          aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}
        >
          <svg width="15" height="15" viewBox="0 0 24 24"
            fill={isFav ? '#e8b84b' : 'none'} stroke={isFav ? '#e8b84b' : 'currentColor'} strokeWidth={2}>
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
        <button
          className="btn-play pdf-read-btn"
          onClick={(e) => { e.stopPropagation(); onRead(pdf); }}
          aria-label="Read"
          title="Read in-app"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
            stroke="var(--gold-primary)" strokeWidth={2} strokeLinecap="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </button>
        <button
          className={`btn-play ${delivered ? 'pdf-delivered' : ''}`}
          onClick={handleDeliver}
          disabled={delivering}
          aria-label="Download to chat"
          title="Send to your chat"
          style={{ marginLeft: 2 }}
        >
          {delivered ? (
            <span style={{ fontSize: 10, color: '#5ee87a' }}>✓</span>
          ) : delivering ? (
            <span style={{ fontSize: 9, color: 'var(--gold-primary)' }}>…</span>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
              stroke="var(--gold-primary)" strokeWidth={2} strokeLinecap="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
