/**
 * components/LyricsPlayer.jsx
 * ---------------------------
 * Synchronized lyrics display component.
 *
 * SYNC APPROACH:
 *   Audio is played via an HTML5 <audio> element pointed at /api/webapp/stream.
 *   The element fires `timeupdate` events (roughly every 250ms). On each event,
 *   findActiveLine() returns the index of the current lyric. The active line is
 *   highlighted and scrolled into view. This is timer-based sync tied to actual
 *   playback position — not a detached interval timer.
 *
 * AUDIO NOTE:
 *   <audio> has NO crossorigin attribute. Without it the browser loads audio as
 *   a no-cors opaque request — CORS headers are not checked, the audio plays,
 *   and the timeupdate event fires normally. We do not need Web Audio API access.
 *
 * PROPS:
 *   track            { id: string, name: string }
 *   lines            [{ time: number, text: string }]  from parseLrc()
 *   language         "ar" | "am" | "mixed"
 *   attributionName  string  — shown as "Transcribed by X" at bottom
 *   apiBase          string  — process.env.NEXT_PUBLIC_API_BASE
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { findActiveLine } from "../lib/lrcParser";

const SCROLL_MARGIN_MS = 100; // throttle scrollIntoView calls

function formatTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function PlayIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}

export default function LyricsPlayer({
  track,
  lines,
  language,
  attributionName,
  apiBase,
}) {
  const audioRef       = useRef(null);
  const scrollerRef    = useRef(null);
  const lineRefs       = useRef([]);
  const lastScrollRef  = useRef(0);

  const [isPlaying,    setIsPlaying]    = useState(false);
  const [currentTime,  setCurrentTime]  = useState(0);
  const [duration,     setDuration]     = useState(0);
  const [activeIndex,  setActiveIndex]  = useState(-1);
  const [audioError,   setAudioError]   = useState(false);
  const [isLoading,    setIsLoading]    = useState(true);

  const streamUrl = `${apiBase}/api/webapp/stream?track_id=${track.id}`;
  const isRtl     = language === "ar";

  // ── Audio event handlers ─────────────────────────────────────────────────

  const handleTimeUpdate = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const t = audio.currentTime;
    setCurrentTime(t);

    const idx = findActiveLine(lines, t);
    setActiveIndex(idx);

    // Scroll active line into view — throttled to avoid layout thrashing
    if (idx >= 0) {
      const now = Date.now();
      if (now - lastScrollRef.current > SCROLL_MARGIN_MS) {
        lastScrollRef.current = now;
        lineRefs.current[idx]?.scrollIntoView({
          behavior: "smooth",
          block:    "center",
        });
      }
    }
  }, [lines]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onPlay     = () => setIsPlaying(true);
    const onPause    = () => setIsPlaying(false);
    const onEnded    = () => setIsPlaying(false);
    const onLoaded   = () => { setDuration(audio.duration); setIsLoading(false); };
    const onError    = () => { setAudioError(true); setIsLoading(false); };
    const onWaiting  = () => setIsLoading(true);
    const onCanPlay  = () => setIsLoading(false);

    audio.addEventListener("play",             onPlay);
    audio.addEventListener("pause",            onPause);
    audio.addEventListener("ended",            onEnded);
    audio.addEventListener("loadedmetadata",   onLoaded);
    audio.addEventListener("error",            onError);
    audio.addEventListener("waiting",          onWaiting);
    audio.addEventListener("canplay",          onCanPlay);
    audio.addEventListener("timeupdate",       handleTimeUpdate);

    return () => {
      audio.removeEventListener("play",           onPlay);
      audio.removeEventListener("pause",          onPause);
      audio.removeEventListener("ended",          onEnded);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("error",          onError);
      audio.removeEventListener("waiting",        onWaiting);
      audio.removeEventListener("canplay",        onCanPlay);
      audio.removeEventListener("timeupdate",     handleTimeUpdate);
    };
  }, [handleTimeUpdate]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || audioError) return;
    if (audio.paused) {
      audio.play().catch(() => setAudioError(true));
    } else {
      audio.pause();
    }
  }, [audioError]);

  const handleSeek = useCallback((e) => {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    const rect  = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    audio.currentTime = ratio * duration;
  }, [duration]);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div style={styles.root}>
      {/* Hidden audio element — no crossorigin attribute intentionally */}
      <audio ref={audioRef} src={streamUrl} preload="metadata" />

      {/* ── Track name header ──────────────────────────────────────────── */}
      <div style={styles.trackHeader}>
        <p style={styles.trackName}>{track.name}</p>
      </div>

      {/* ── Lyrics scroll area ─────────────────────────────────────────── */}
      <div ref={scrollerRef} style={styles.lyricsScroll}>
        {lines.length === 0 ? (
          <p style={styles.emptyHint}>No lyric lines found.</p>
        ) : (
          lines.map((line, i) => {
            const isActive = i === activeIndex;
            const isPast   = i < activeIndex;
            return (
              <p
                key={i}
                ref={(el) => (lineRefs.current[i] = el)}
                dir={isRtl ? "rtl" : "ltr"}
                style={{
                  ...styles.lyricLine,
                  ...(isActive ? styles.lyricActive : {}),
                  ...(isPast   ? styles.lyricPast   : {}),
                }}
              >
                {line.text}
              </p>
            );
          })
        )}
        {/* Bottom padding so last line can scroll to center */}
        <div style={{ height: "40vh" }} />
      </div>

      {/* ── Controls bar ───────────────────────────────────────────────── */}
      <div style={styles.controls}>
        {/* Progress bar */}
        <div
          style={styles.progressTrack}
          onClick={handleSeek}
          role="slider"
          aria-label="Seek"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div style={{ ...styles.progressFill, width: `${progress}%` }} />
          <div style={{
            ...styles.progressThumb,
            left: `calc(${progress}% - 6px)`,
          }} />
        </div>

        {/* Time + play/pause + duration */}
        <div style={styles.controlRow}>
          <span style={styles.timeLabel}>{formatTime(currentTime)}</span>

          <button
            style={{
              ...styles.playBtn,
              opacity: audioError ? 0.4 : 1,
            }}
            onClick={togglePlay}
            disabled={audioError}
            aria-label={isPlaying ? "Pause" : "Play"}
          >
            {isLoading && !audioError
              ? <span style={styles.loadingDot} />
              : isPlaying
                ? <PauseIcon size={22} />
                : <PlayIcon  size={22} />
            }
          </button>

          <span style={styles.timeLabel}>{formatTime(duration)}</span>
        </div>

        {audioError && (
          <p style={styles.audioErrorMsg}>
            ⚠️ Could not load audio. Open in bot chat instead.
          </p>
        )}

        {/* Attribution */}
        {attributionName && (
          <p style={styles.attribution}>Transcribed by {attributionName}</p>
        )}
      </div>
    </div>
  );
}

// ── Inline styles — matches globals.css design tokens ───────────────────────

const styles = {
  root: {
    display:       "flex",
    flexDirection: "column",
    height:        "100%",
    background:    "#080d1a",
    overflow:      "hidden",
    position:      "relative",
  },
  trackHeader: {
    flexShrink:  0,
    padding:     "18px 24px 10px",
    borderBottom:"1px solid #1a2f4e",
  },
  trackName: {
    fontFamily:   "var(--font-display, 'Cinzel', serif)",
    fontSize:     "13px",
    fontWeight:   600,
    color:        "#e8b84b",
    letterSpacing:"0.04em",
    margin:       0,
    textAlign:    "center",
    overflow:     "hidden",
    textOverflow: "ellipsis",
    whiteSpace:   "nowrap",
  },
  lyricsScroll: {
    flex:          1,
    overflowY:     "auto",
    overflowX:     "hidden",
    padding:       "24px 28px 0",
    scrollbarWidth:"none",             // Firefox
    msOverflowStyle: "none",          // IE/Edge
    WebkitOverflowScrolling: "touch", // iOS momentum scroll
  },
  lyricLine: {
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontSize:     "17px",
    lineHeight:   1.7,
    color:        "#4a6a9a",
    margin:       "0 0 18px",
    transition:   "color 280ms ease, font-size 200ms ease, opacity 280ms ease",
    textAlign:    "center",
    cursor:       "default",
  },
  lyricActive: {
    color:      "#e8b84b",
    fontSize:   "19px",
    fontWeight: 600,
    opacity:    1,
    textShadow: "0 0 20px rgba(232,184,75,0.35)",
  },
  lyricPast: {
    color:   "#8aacdb",
    opacity: 0.65,
  },
  emptyHint: {
    textAlign: "center",
    color:     "#4a6a9a",
    marginTop: "40px",
    fontFamily:"var(--font-body, 'Nunito', sans-serif)",
  },
  controls: {
    flexShrink:   0,
    padding:      "16px 24px calc(16px + env(safe-area-inset-bottom, 0px))",
    background:   "linear-gradient(0deg, #0f1829 0%, transparent 100%)",
    backdropFilter: "blur(12px)",
  },
  progressTrack: {
    position:     "relative",
    height:       "4px",
    borderRadius: "2px",
    background:   "#1a2f4e",
    cursor:       "pointer",
    margin:       "0 0 14px",
  },
  progressFill: {
    position:     "absolute",
    top:          0,
    left:         0,
    height:       "100%",
    borderRadius: "2px",
    background:   "#e8b84b",
    transition:   "width 200ms linear",
    pointerEvents:"none",
  },
  progressThumb: {
    position:     "absolute",
    top:          "-4px",
    width:        "12px",
    height:       "12px",
    borderRadius: "50%",
    background:   "#e8b84b",
    boxShadow:    "0 0 6px rgba(232,184,75,0.5)",
    pointerEvents:"none",
    transition:   "left 200ms linear",
  },
  controlRow: {
    display:        "flex",
    alignItems:     "center",
    justifyContent: "space-between",
    gap:            "16px",
  },
  timeLabel: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "12px",
    color:      "#4a6a9a",
    minWidth:   "32px",
    textAlign:  "center",
  },
  playBtn: {
    width:           "52px",
    height:          "52px",
    borderRadius:    "50%",
    border:          "none",
    background:      "#e8b84b",
    color:           "#080d1a",
    display:         "flex",
    alignItems:      "center",
    justifyContent:  "center",
    cursor:          "pointer",
    boxShadow:       "0 0 18px rgba(232,184,75,0.35)",
    transition:      "transform 150ms ease, box-shadow 150ms ease",
    flexShrink:      0,
  },
  loadingDot: {
    display:       "block",
    width:         "10px",
    height:        "10px",
    borderRadius:  "50%",
    background:    "#080d1a",
    animation:     "pulse 1s ease-in-out infinite",
  },
  audioErrorMsg: {
    textAlign:  "center",
    fontSize:   "12px",
    color:      "#e74c3c",
    margin:     "8px 0 0",
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
  },
  attribution: {
    textAlign:    "center",
    fontSize:     "11px",
    color:        "#4a6a9a",
    margin:       "10px 0 0",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    letterSpacing:"0.03em",
  },
};
