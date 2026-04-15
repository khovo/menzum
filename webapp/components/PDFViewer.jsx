import { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export default function PDFViewer({ pdf, authHeader, onClose, onFavorite, isFav }) {
  const [viewerUrl,  setViewerUrl]  = useState(null);
  const [loadErr,    setLoadErr]    = useState(false);
  const [fetching,   setFetching]   = useState(true);
  const [delivering, setDelivering] = useState(false);
  const [delivered,  setDelivered]  = useState(false);
  const [favLoading, setFavLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function getUrl() {
      setFetching(true);
      setLoadErr(false);
      try {
        const res  = await fetch(`${API_BASE}/api/webapp/pdf-view?id=${pdf.id}`, {
          headers: authHeader(),
        });
        const data = await res.json();
        if (!cancelled && data.ok) {
          const encoded = encodeURIComponent(data.url);
          setViewerUrl(`https://docs.google.com/viewer?url=${encoded}&embedded=true`);
        } else if (!cancelled) {
          setLoadErr(true);
        }
      } catch {
        if (!cancelled) setLoadErr(true);
      } finally {
        if (!cancelled) setFetching(false);
      }
    }
    getUrl();
    return () => { cancelled = true; };
  }, [pdf.id]);

  async function handleDeliver() {
    if (delivering || delivered) return;
    setDelivering(true);
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/pdfs`, {
        method:  'POST',
        headers: authHeader(),
        body:    JSON.stringify({ action: 'deliver', pdf_id: pdf.id }),
      });
      const data = await res.json();
      if (data.ok) setDelivered(true);
    } finally {
      setDelivering(false);
    }
  }

  async function handleFav() {
    if (favLoading) return;
    setFavLoading(true);
    await onFavorite(pdf);
    setFavLoading(false);
  }

  return (
    <div className="pdf-viewer-overlay" role="dialog" aria-modal="true">

      {/* Header */}
      <div className="pdf-viewer-header">
        <button className="pdf-viewer-close" onClick={onClose} aria-label="Close">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={2} strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
        <div className="pdf-viewer-title" title={pdf.title}>{pdf.title}</div>
        <button
          className={`pdf-viewer-fav ${isFav ? 'is-fav' : ''}`}
          onClick={handleFav}
          aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24"
            fill={isFav ? '#e8b84b' : 'none'} stroke={isFav ? '#e8b84b' : 'currentColor'} strokeWidth={2}>
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
      </div>

      {/* Viewer area */}
      <div className="pdf-viewer-body">
        {fetching && (
          <div className="pdf-viewer-loading">
            <div className="loading-dots" style={{ marginTop: 0 }}>
              <div className="loading-dot"/><div className="loading-dot"/><div className="loading-dot"/>
            </div>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>Loading PDF…</span>
          </div>
        )}
        {!fetching && loadErr && (
          <div className="pdf-viewer-loading">
            <span style={{ fontSize: 28 }}>📄</span>
            <span style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
              Could not load preview.<br/>Download to read in your chat.
            </span>
          </div>
        )}
        {!fetching && !loadErr && viewerUrl && (
          <iframe
            src={viewerUrl}
            className="pdf-viewer-iframe"
            title={pdf.title}
            allow="autoplay"
          />
        )}
      </div>

      {/* Download bar */}
      <div className="pdf-viewer-footer">
        <button
          className={`pdf-dl-btn ${delivered ? 'delivered' : ''}`}
          onClick={handleDeliver}
          disabled={delivering || delivered}
        >
          {delivered ? '✓ Sent to your chat' : delivering ? 'Sending…' : '📥 Download to Chat'}
        </button>
      </div>
    </div>
  );
}
