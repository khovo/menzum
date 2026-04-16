import { useState, useEffect, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export default function PDFViewer({ pdf, authHeader, onClose, onFavorite, isFav }) {
  const [viewerUrl, setViewerUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [useIframeFallback, setUseIframeFallback] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [delivered, setDelivered] = useState(false);
  const [favLoading, setFavLoading] = useState(false);
  const [numPages, setNumPages] = useState(0);
  
  const canvasContainerRef = useRef(null);

  // ── Telegram Haptic Feedback Helper ──
  const triggerHaptic = (style = 'light') => {
    if (typeof window !== 'undefined' && window.Telegram?.WebApp?.HapticFeedback) {
      window.Telegram.WebApp.HapticFeedback.impactOccurred(style);
    }
  };

  useEffect(() => {
    let cancelled = false;

    async function loadPDF() {
      setLoading(true);
      try {
        // 1. Fetch the PDF URL from your backend
        const res = await fetch(`${API_BASE}/api/webapp/pdf-view?id=${pdf.id}`, {
          headers: authHeader(),
        });
        const data = await res.json();
        
        if (cancelled || !data.ok) throw new Error("Failed to get URL");

        const rawUrl = data.url;
        setViewerUrl(rawUrl);

        // 2. Dynamically load PDF.js (CDN) for native rendering
        if (!window.pdfjsLib) {
          const script = document.createElement('script');
          script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.min.js';
          await new Promise((resolve) => {
            script.onload = resolve;
            document.body.appendChild(script);
          });
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';
        }

        // 3. Try to render the PDF natively onto Canvases
        const loadingTask = window.pdfjsLib.getDocument(rawUrl);
        const pdfDoc = await loadingTask.promise;
        
        if (cancelled) return;
        setNumPages(pdfDoc.numPages);
        setUseIframeFallback(false);

        // Render pages sequentially
        for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
          if (cancelled) break;
          const page = await pdfDoc.getPage(pageNum);
          const viewport = page.getViewport({ scale: window.devicePixelRatio || 2.0 }); // High-Res Rendering
          
          const canvas = document.getElementById(`pdf-canvas-${pageNum}`);
          if (canvas) {
            const context = canvas.getContext('2d');
            canvas.height = viewport.height;
            canvas.width = viewport.width;
            
            await page.render({ canvasContext: context, viewport: viewport }).promise;
          }
        }
        
        triggerHaptic('success');

      } catch (err) {
        console.warn("Native render failed (likely CORS), falling back to Iframe:", err);
        if (!cancelled) setUseIframeFallback(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadPDF();
    return () => { cancelled = true; };
  }, [pdf.id]);

  async function handleDeliver() {
    if (delivering || delivered) return;
    triggerHaptic('medium');
    setDelivering(true);
    try {
      const res = await fetch(`${API_BASE}/api/webapp/pdfs`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({ action: 'deliver', pdf_id: pdf.id }),
      });
      const data = await res.json();
      if (data.ok) {
        setDelivered(true);
        triggerHaptic('success');
      }
    } finally {
      setDelivering(false);
    }
  }

  async function handleFav() {
    if (favLoading) return;
    triggerHaptic('light');
    setFavLoading(true);
    await onFavorite(pdf);
    setFavLoading(false);
  }

  const handleClose = () => {
    triggerHaptic('light');
    onClose();
  };

  return (
    <div className="pdf-ultra-overlay animate-slide-up-fade" role="dialog" aria-modal="true">
      
      {/* ── Smart Eye-Care Filter ── */}
      <div className="pdf-eye-care-filter" />

      {/* ── Neo-Glassmorphism Header ── */}
      <div className="pdf-glass-header">
        <button className="pdf-action-btn" onClick={handleClose} aria-label="Close">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
        
        <div className="pdf-header-title">
          <span className="pdf-title-text" title={pdf.title}>{pdf.title}</span>
          <span className="pdf-subtitle-text">{numPages > 0 ? `${numPages} Pages` : 'Loading...'}</span>
        </div>

        <button
          className={`pdf-action-btn ${isFav ? 'active-fav' : ''}`}
          onClick={handleFav}
          aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}
        >
          <svg width="22" height="22" viewBox="0 0 24 24"
            fill={isFav ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={2}>
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
      </div>

      {/* ── Viewer Body (Native Pinch-to-Zoom or Iframe) ── */}
      <div className="pdf-body-container" ref={canvasContainerRef}>
        
        {loading && (
          <div className="pdf-ultra-loading">
            <div className="glow-spinner"></div>
            <span>Opening Document...</span>
          </div>
        )}

        {/* NATIVE CANVAS RENDERER (Supports Native OS Pinch-to-Zoom smoothly) */}
        {!useIframeFallback && numPages > 0 && (
          <div className="pdf-canvas-wrapper">
            {Array.from(new Array(numPages), (el, index) => (
              <canvas 
                key={`page_${index + 1}`} 
                id={`pdf-canvas-${index + 1}`} 
                className="pdf-page-canvas"
              />
            ))}
          </div>
        )}

        {/* GOOGLE DOCS IFRAME FALLBACK (If Telegram CORS blocks direct fetch) */}
        {!loading && useIframeFallback && viewerUrl && (
          <iframe
            src={`https://docs.google.com/viewer?url=${encodeURIComponent(viewerUrl)}&embedded=true`}
            className="pdf-iframe-fallback"
            title={pdf.title}
          />
        )}
      </div>

      {/* ── Floating Action Button (Download to Chat) ── */}
      <div className="pdf-fab-container">
        <button
          className={`pdf-fab-btn ${delivered ? 'delivered' : ''}`}
          onClick={handleDeliver}
          disabled={delivering || delivered}
        >
          <span className="pdf-fab-icon">
            {delivered ? '✨' : delivering ? '⏳' : '📥'}
          </span>
          <span className="pdf-fab-text">
            {delivered ? 'Sent to Chat' : delivering ? 'Sending...' : 'Download to Chat'}
          </span>
        </button>
      </div>

    </div>
  );
}
