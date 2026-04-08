/**
 * pages/lyrics.js
 * ---------------
 * Full-screen lyrics player page.
 *
 * ROUTE: /lyrics?track_id=<24-char-mongo-id>&name=<url-encoded-track-name>
 *
 * NOTE ON lrcParser:
 *   parseLrc is inlined here. This eliminates the build error
 *   "Module not found: Can't resolve '../lib/lrcParser'" that occurs
 *   when the webapp/lib/ directory has not been created in the repo.
 *
 * FLOW:
 *   1. useTelegram() provides initData for the auth header
 *   2. GET /api/webapp/lyrics?track_id= returns the approved lyrics doc
 *   3. parseLrc(doc.content) returns sorted [{time, text}] array
 *   4. LyricsPlayer renders the synchronized display
 */

import { useState, useEffect } from "react";
import { useRouter }           from "next/router";
import Head                    from "next/head";
import { useTelegram }         from "../hooks/useTelegram";
import LyricsPlayer            from "../components/LyricsPlayer";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

// ── Inlined from webapp/lib/lrcParser.js ─────────────────────────────────────

function parseLrc(lrcString) {
  if (!lrcString || typeof lrcString !== "string") return [];

  const TIME_TAG_RE = /\[(\d{2}):(\d{2})\.(\d{2,3})\]/g;
  const result = [];

  for (const rawLine of lrcString.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;

    const text = line.replace(/\[(\d{2}):(\d{2})\.(\d{2,3})\]/g, "").trim();
    if (!text) continue;

    TIME_TAG_RE.lastIndex = 0;
    let match;

    while ((match = TIME_TAG_RE.exec(line)) !== null) {
      const minutes  = parseInt(match[1], 10);
      const seconds  = parseInt(match[2], 10);
      const fraction = match[3].length === 2
        ? parseInt(match[3], 10) / 100
        : parseInt(match[3], 10) / 1000;
      result.push({ time: minutes * 60 + seconds + fraction, text });
    }
  }

  return result.sort((a, b) => a.time - b.time);
}

// ─────────────────────────────────────────────────────────────────────────────

function CrescentIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path
        d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
        fill="#e8b84b"
        stroke="#e8b84b"
        strokeWidth="1"
      />
    </svg>
  );
}

function BackIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5M12 5l-7 7 7 7" />
    </svg>
  );
}

function LoadingSkeleton() {
  return (
    <div style={sk.root}>
      {[...Array(8)].map((_, i) => (
        <div key={i} style={{
          ...sk.line,
          width: `${50 + (i % 3) * 15}%`,
          animationDelay: `${i * 80}ms`,
        }} />
      ))}
    </div>
  );
}

const sk = {
  root: {
    padding:       "32px 28px",
    display:       "flex",
    flexDirection: "column",
    gap:           "18px",
    alignItems:    "center",
  },
  line: {
    height:         "16px",
    borderRadius:   "8px",
    background:     "linear-gradient(90deg, #1a2f4e 25%, #162035 50%, #1a2f4e 75%)",
    backgroundSize: "200% 100%",
    animation:      "shimmer 1.4s infinite",
  },
};

export default function LyricsPage() {
  const router              = useRouter();
  const { initData, isReady } = useTelegram();

  const { track_id, name: queryName } = router.query;

  const [lyricsData,   setLyricsData]   = useState(null);
  const [lines,        setLines]         = useState([]);
  const [loadingState, setLoadingState]  = useState("loading"); // "loading"|"ok"|"not_found"|"error"

  useEffect(() => {
    if (!isReady || !track_id) return;

    async function fetchLyrics() {
      setLoadingState("loading");
      try {
        const res = await fetch(
          `${API_BASE}/api/webapp/lyrics?track_id=${track_id}`,
          { headers: { Authorization: `tma ${initData}` } }
        );
        if (res.status === 404) { setLoadingState("not_found"); return; }
        if (!res.ok)            { setLoadingState("error");     return; }
        const data = await res.json();
        if (!data.ok)           { setLoadingState("error");     return; }

        setLyricsData(data);
        setLines(parseLrc(data.content));
        setLoadingState("ok");
      } catch {
        setLoadingState("error");
      }
    }

    fetchLyrics();
  }, [track_id, initData, isReady]);

  const displayName = lyricsData?.track_name
    || (queryName ? decodeURIComponent(queryName) : "");
  const track = { id: track_id || "", name: displayName };

  const goBack = () => {
    if (window.history.length > 1) router.back();
    else router.push("/");
  };

  const goSubmit = () => {
    const nameParam = displayName ? `&name=${encodeURIComponent(displayName)}` : "";
    router.push(`/submit-lyrics?track_id=${track_id}${nameParam}`);
  };

  return (
    <>
      <Head>
        <title>Al-Madih — Lyrics</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </Head>

      <div style={page.shell}>
        {/* Top bar */}
        <div style={page.topBar}>
          <button onClick={goBack} style={page.backBtn} aria-label="Go back">
            <BackIcon />
          </button>

          <div style={page.topCenter}>
            <CrescentIcon />
            <span style={page.topTitle}>Al-Madih</span>
          </div>

          {track_id && (
            <button onClick={goSubmit} style={page.submitBtn} aria-label="Submit lyrics">
              📝
            </button>
          )}
        </div>

        {/* Content */}
        <div style={page.content}>
          {loadingState === "loading" && <LoadingSkeleton />}

          {loadingState === "ok" && lyricsData && (
            <LyricsPlayer
              track={track}
              lines={lines}
              language={lyricsData.language}
              attributionName={lyricsData.attribution_name}
              apiBase={API_BASE}
            />
          )}

          {loadingState === "not_found" && (
            <div style={page.centeredState}>
              <p style={page.stateEmoji}>📖</p>
              <p style={page.stateTitle}>No lyrics yet</p>
              <p style={page.stateBody}>
                Be the first to transcribe this Menzuma.
              </p>
              {track_id && (
                <button onClick={goSubmit} style={page.ctaBtn}>
                  Submit Lyrics
                </button>
              )}
            </div>
          )}

          {loadingState === "error" && (
            <div style={page.centeredState}>
              <p style={page.stateEmoji}>⚠️</p>
              <p style={page.stateTitle}>Could not load lyrics</p>
              <p style={page.stateBody}>Please try again.</p>
              <button
                onClick={() => setLoadingState("loading")}
                style={page.ctaBtn}
              >
                Retry
              </button>
            </div>
          )}
        </div>
      </div>

      <style jsx global>{`
        @keyframes shimmer {
          0%   { background-position:  200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
      `}</style>
    </>
  );
}

const page = {
  shell: {
    display:       "flex",
    flexDirection: "column",
    height:        "100dvh",
    background:    "#080d1a",
    overflow:      "hidden",
  },
  topBar: {
    flexShrink:     0,
    height:         "56px",
    display:        "flex",
    alignItems:     "center",
    justifyContent: "space-between",
    padding:        "0 16px",
    paddingTop:     "env(safe-area-inset-top, 0px)",
    borderBottom:   "1px solid #1a2f4e",
    background:     "#0f1829",
  },
  backBtn: {
    background:   "none",
    border:       "none",
    color:        "#8aacdb",
    cursor:       "pointer",
    padding:      "8px",
    borderRadius: "8px",
    display:      "flex",
    alignItems:   "center",
    lineHeight:   1,
  },
  topCenter: {
    display:    "flex",
    alignItems: "center",
    gap:        "6px",
  },
  topTitle: {
    fontFamily:   "var(--font-display, 'Cinzel', serif)",
    fontSize:     "14px",
    fontWeight:   600,
    color:        "#f0f4ff",
    letterSpacing:"0.06em",
  },
  submitBtn: {
    background:   "none",
    border:       "none",
    fontSize:     "18px",
    cursor:       "pointer",
    padding:      "8px",
    borderRadius: "8px",
    lineHeight:   1,
  },
  content: {
    flex:          1,
    overflow:      "hidden",
    display:       "flex",
    flexDirection: "column",
  },
  centeredState: {
    flex:           1,
    display:        "flex",
    flexDirection:  "column",
    alignItems:     "center",
    justifyContent: "center",
    padding:        "40px 32px",
    gap:            "12px",
    textAlign:      "center",
  },
  stateEmoji: {
    fontSize: "40px",
    margin:   0,
  },
  stateTitle: {
    fontFamily: "var(--font-display, 'Cinzel', serif)",
    fontSize:   "17px",
    color:      "#f0f4ff",
    margin:     0,
  },
  stateBody: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "14px",
    color:      "#8aacdb",
    margin:     0,
    maxWidth:   "260px",
    lineHeight: 1.5,
  },
  ctaBtn: {
    marginTop:    "8px",
    padding:      "12px 28px",
    borderRadius: "24px",
    border:       "none",
    background:   "#e8b84b",
    color:        "#080d1a",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontWeight:   700,
    fontSize:     "14px",
    cursor:       "pointer",
    letterSpacing:"0.02em",
  },
};
