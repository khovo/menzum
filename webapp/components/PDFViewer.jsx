import { useState, useEffect, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

// ── Lazy Rendered Page Subcomponent ──
// Renders the canvas ONLY when it scrolls into view, saving immense amounts of RAM.
function PdfPageItem({ pageNum, pdfDoc, scale = 2.0 }) {
  const canvasRef = useRef(null);
  const [rendered, setRendered] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect(); // Trigger render once visible
        }
      },
      { rootMargin: '600px 0px' } // Pre-load pages when they are 600px away
    );
    if (canvasRef.current) observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || rendered || !pdfDoc) return;
    let renderTask;
    
    async function renderPage() {
      try {
        const page = await pdfDoc.getPage(pageNum);
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        
        // Disable alpha channel to save VRAM on mobile browsers
        const context = canvas.getContext('2d', { alpha: false }); 
        canvas.height = viewport.height;
        canvas.width = viewport.width;
        
        renderTask = page.render({ canvasContext: context, viewport });
        await renderTask.promise;
        setRendered(true);
        
        // Garbage collect PDF page to prevent cumulative memory bloat
        page.cleanup(); 
      } catch (err) {
        if (err.name !== 'RenderingCancelledException') {
          console.warn(`Error rendering page ${pageNum}:`, err);
        }
      }
    }
    renderPage();
    
    return () => {
      if (renderTask) renderTask.cancel();
    };
  }, [visible, rendered, pdfDoc, pageNum, scale]);

  return (
    <canvas 
      ref={canvasRef}
      id={`pdf-canvas-${pageNum}`} 
      className="pdf-page-canvas"
      style={{ 
        minHeight: rendered ? 'auto' : '600px', // Placeholder height prevents violent layout shifts
        backgroundColor: rendered ? 'transparent' : 'rgba(255,255,255,0.05)'
      }}
    />
  );
}

export default function PDFViewer({ pdf, authHeader, onClose, onFavorite, isFav }) {
  const [viewerUrl, setViewerUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [useIframeFallback, setUseIframeFallback] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [delivered, setDelivered] = useState(false);
  const [favLoading, setFavLoading] = useState(false);
  
  const [pdfDoc, setPdfDoc] = useState(null);
  const [numPages, setNumPages] = useState(0);
  
  const canvasContainerRef = useRef(null);

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
        // Fetch original JSON url solely for Google Docs fallback (if needed)
        fetch(`${API_BASE}/api/webapp/pdf-view?id=${pdf.id}`, { headers: authHeader() })
          .then(r => r.json())
          .then(d => { if (d.ok) setViewerUrl(d.url); })
          .catch(e => console.warn("Failed fetching fallback URL"));

        if (!window.pdfjsLib) {
          const script = document.createElement('script');
          script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.min.js';
          await new Promise((resolve) => {
            script.onload = resolve;
            document.body.appendChild(script);
          });
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';
        }

        // Trigger our new Progressive Streaming API Route
        const streamUrl = `${API_BASE}/api/webapp/pdf-view?id=${pdf.id}&action=stream`;

        const loadingTask = window.pdfjsLib.getDocument({
          url: streamUrl,
          httpHeaders: authHeader(),
          disableAutoFetch: true,  // MANDATORY: Forces Range-Requests. Doesn't download entire file at once.
          disableStream: false,
          cMapUrl: 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/cmaps/',
          cMapPacked: true,
        });

        const doc = await loadingTask.promise;
        
        if (cancelled) return;
        setPdfDoc(doc);
        setNumPages(doc.numPages);
        setUseIframeFallback(false);
        
        triggerHaptic('success');

      } catch (err) {
        console.warn("Native render failed, falling back to Iframe:", err);
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
        {!useIframeFallback && numPages > 0 && pdfDoc && (
          <div className="pdf-canvas-wrapper">
            {Array.from(new Array(numPages), (el, index) => (
              <PdfPageItem 
                key={`page_${index + 1}`} 
                pageNum={index + 1} 
                pdfDoc={pdfDoc}
                scale={window.devicePixelRatio || 2.0}
              />
            ))}
          </div>
        )}

        {/* GOOGLE DOCS IFRAME FALLBACK */}
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

