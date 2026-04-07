/**
 * pages/submit-lyrics.js
 * ----------------------
 * Lyrics submission form.
 *
 * ROUTE: /submit-lyrics?track_id=<24-char-id>&name=<url-encoded-track-name>
 *
 * FLOW:
 *   1. User pastes an LRC string into the textarea
 *   2. Selects the language (Arabic / Amharic / Mixed)
 *   3. Taps Submit → POST /api/webapp/lyrics
 *   4. On 201 → success screen
 *   5. On 409 → "already pending" message (blocks duplicate submissions)
 *   6. On error → retry prompt
 *
 * LRC FORMAT GUIDANCE is shown inline so users know what to paste.
 * No gamification, no points, no badges — just the form.
 */

import { useState }    from "react";
import { useRouter }   from "next/router";
import Head            from "next/head";
import { useTelegram } from "../hooks/useTelegram";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

const LANGUAGES = [
  { value: "am",    label: "Amharic (አማርኛ)" },
  { value: "ar",    label: "Arabic (عربي)" },
  { value: "mixed", label: "Mixed" },
];

function BackIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5M12 5l-7 7 7 7" />
    </svg>
  );
}

function CrescentIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
        fill="#e8b84b" stroke="#e8b84b" strokeWidth="1" />
    </svg>
  );
}

// ── Success screen ───────────────────────────────────────────────────────────
function SuccessScreen({ onBack }) {
  return (
    <div style={s.centered}>
      <div style={s.successIcon}>✅</div>
      <p style={s.successTitle}>Submitted!</p>
      <p style={s.successBody}>
        Your lyrics are pending admin review. You will receive a Telegram
        message once they are approved or rejected.
      </p>
      <button onClick={onBack} style={s.ctaBtn}>
        Back to App
      </button>
    </div>
  );
}

// ── Main form ────────────────────────────────────────────────────────────────
export default function SubmitLyricsPage() {
  const router               = useRouter();
  const { initData, isReady } = useTelegram();

  const { track_id, name: queryName } = router.query;
  const trackName = queryName ? decodeURIComponent(queryName) : "";

  const [lrcContent,   setLrcContent]   = useState("");
  const [language,     setLanguage]     = useState("am");
  const [submitting,   setSubmitting]   = useState(false);
  const [submitState,  setSubmitState]  = useState("idle"); // "idle"|"success"|"error"|"duplicate"
  const [errorMsg,     setErrorMsg]     = useState("");

  const goBack = () => {
    if (window.history.length > 1) router.back();
    else router.push("/");
  };

  const handleSubmit = async () => {
    if (!lrcContent.trim()) {
      setErrorMsg("Please paste an LRC string before submitting.");
      return;
    }
    if (!lrcContent.trim().startsWith("[")) {
      setErrorMsg("LRC content must start with a time tag like [00:00.00].");
      return;
    }
    if (!track_id) {
      setErrorMsg("Missing track ID. Please go back and try again.");
      return;
    }
    if (!isReady) return;

    setSubmitting(true);
    setErrorMsg("");

    try {
      const res = await fetch(`${API_BASE}/api/webapp/lyrics`, {
        method:  "POST",
        headers: {
          "Content-Type":  "application/json",
          "Authorization": `tma ${initData}`,
        },
        body: JSON.stringify({
          track_id,
          content:  lrcContent.trim(),
          language,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.status === 201) {
        setSubmitState("success");
        return;
      }
      if (res.status === 409) {
        setSubmitState("duplicate");
        return;
      }
      if (res.status === 401) {
        setErrorMsg("Session expired. Please close and reopen the Mini App.");
        return;
      }
      setErrorMsg(data.error || "Submission failed. Please try again.");

    } catch {
      setErrorMsg("Network error. Please check your connection and retry.");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Success state ─────────────────────────────────────────────────────────
  if (submitState === "success") {
    return (
      <>
        <Head><title>Al-Madih — Submitted</title></Head>
        <div style={s.shell}>
          <div style={s.topBar}>
            <div style={s.topCenter}><CrescentIcon /><span style={s.topTitle}>Al-Madih</span></div>
          </div>
          <SuccessScreen onBack={() => router.push("/")} />
        </div>
      </>
    );
  }

  // ── Duplicate state ───────────────────────────────────────────────────────
  if (submitState === "duplicate") {
    return (
      <>
        <Head><title>Al-Madih — Already Submitted</title></Head>
        <div style={s.shell}>
          <div style={s.topBar}>
            <button onClick={goBack} style={s.backBtn}><BackIcon /></button>
            <div style={s.topCenter}><CrescentIcon /><span style={s.topTitle}>Al-Madih</span></div>
            <div style={{ width: 36 }} />
          </div>
          <div style={s.centered}>
            <div style={{ fontSize: 36 }}>⏳</div>
            <p style={s.successTitle}>Already submitted</p>
            <p style={s.successBody}>
              You have a pending submission for this track. You will be notified
              once it is reviewed.
            </p>
            <button onClick={goBack} style={s.ctaBtn}>Go back</button>
          </div>
        </div>
      </>
    );
  }

  // ── Form ──────────────────────────────────────────────────────────────────
  return (
    <>
      <Head>
        <title>Al-Madih — Submit Lyrics</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </Head>

      <div style={s.shell}>
        {/* Top bar */}
        <div style={s.topBar}>
          <button onClick={goBack} style={s.backBtn} aria-label="Go back">
            <BackIcon />
          </button>
          <div style={s.topCenter}>
            <CrescentIcon />
            <span style={s.topTitle}>Submit Lyrics</span>
          </div>
          <div style={{ width: 36 }} />
        </div>

        {/* Scrollable form body */}
        <div style={s.scrollBody}>

          {/* Track name */}
          {trackName && (
            <div style={s.trackBadge}>
              <span style={s.trackBadgeLabel}>Track</span>
              <span style={s.trackBadgeName}>{trackName}</span>
            </div>
          )}

          {/* LRC format guidance */}
          <div style={s.guideBox}>
            <p style={s.guideTitle}>LRC Format Guide</p>
            <p style={s.guideText}>
              Each line must start with a timestamp in this format:
            </p>
            <pre style={s.guidePre}>{`[00:00.00] First line of lyrics
[00:05.50] Second line
[00:12.20] Third line`}</pre>
            <p style={s.guideText}>
              You can generate LRC files using apps like{" "}
              <span style={{ color: "#e8b84b" }}>LRC Editor</span> or{" "}
              <span style={{ color: "#e8b84b" }}>Musixmatch</span>.
            </p>
          </div>

          {/* Language selector */}
          <div style={s.fieldGroup}>
            <label style={s.label} htmlFor="lang-select">Language</label>
            <div style={s.selectWrapper}>
              <select
                id="lang-select"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                style={s.select}
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
              <span style={s.selectArrow}>▾</span>
            </div>
          </div>

          {/* LRC textarea */}
          <div style={s.fieldGroup}>
            <label style={s.label} htmlFor="lrc-input">LRC Content</label>
            <textarea
              id="lrc-input"
              value={lrcContent}
              onChange={(e) => { setLrcContent(e.target.value); setErrorMsg(""); }}
              placeholder={"[00:00.00] Bismillah\n[00:05.50] Second line\n..."}
              style={s.textarea}
              spellCheck={false}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
            />
            <p style={s.charCount}>{lrcContent.length} characters</p>
          </div>

          {/* Error message */}
          {errorMsg && (
            <div style={s.errorBox}>
              <span>⚠️</span> {errorMsg}
            </div>
          )}

          {/* Submit button */}
          <button
            onClick={handleSubmit}
            disabled={submitting || !lrcContent.trim()}
            style={{
              ...s.submitBtn,
              opacity: (submitting || !lrcContent.trim()) ? 0.5 : 1,
            }}
          >
            {submitting ? "Submitting…" : "Submit for Review"}
          </button>

          <p style={s.disclaimer}>
            Submitted lyrics will be reviewed by an admin before going live.
            Your display name will appear as attribution.
          </p>

          <div style={{ height: "env(safe-area-inset-bottom, 24px)" }} />
        </div>
      </div>
    </>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const s = {
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
    fontSize:     "13px",
    fontWeight:   600,
    color:        "#f0f4ff",
    letterSpacing:"0.06em",
  },
  scrollBody: {
    flex:      1,
    overflowY: "auto",
    overflowX: "hidden",
    padding:   "20px 20px 0",
    WebkitOverflowScrolling: "touch",
  },
  trackBadge: {
    display:      "flex",
    flexDirection:"column",
    gap:          "2px",
    background:   "#111f36",
    borderRadius: "12px",
    padding:      "12px 16px",
    marginBottom: "16px",
    border:       "1px solid #1a2f4e",
  },
  trackBadgeLabel: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "10px",
    fontWeight: 600,
    color:      "#4a6a9a",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
  },
  trackBadgeName: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "14px",
    fontWeight: 600,
    color:      "#f0f4ff",
  },
  guideBox: {
    background:   "#0f1829",
    borderRadius: "12px",
    padding:      "14px 16px",
    marginBottom: "20px",
    border:       "1px solid #1a2f4e",
  },
  guideTitle: {
    fontFamily: "var(--font-display, 'Cinzel', serif)",
    fontSize:   "12px",
    fontWeight: 600,
    color:      "#e8b84b",
    margin:     "0 0 8px",
    letterSpacing: "0.04em",
  },
  guideText: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "12px",
    color:      "#8aacdb",
    margin:     "0 0 6px",
    lineHeight: 1.5,
  },
  guidePre: {
    fontFamily:  "monospace",
    fontSize:    "11px",
    color:       "#f0f4ff",
    background:  "#080d1a",
    borderRadius:"8px",
    padding:     "10px 12px",
    margin:      "8px 0",
    overflowX:   "auto",
    lineHeight:  1.6,
    whiteSpace:  "pre",
  },
  fieldGroup: {
    marginBottom: "16px",
  },
  label: {
    display:      "block",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontSize:     "12px",
    fontWeight:   600,
    color:        "#8aacdb",
    marginBottom: "6px",
    textTransform:"uppercase",
    letterSpacing:"0.06em",
  },
  selectWrapper: {
    position:     "relative",
    display:      "block",
  },
  select: {
    width:        "100%",
    padding:      "12px 40px 12px 16px",
    background:   "#111f36",
    border:       "1px solid #1a2f4e",
    borderRadius: "12px",
    color:        "#f0f4ff",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontSize:     "14px",
    appearance:   "none",
    WebkitAppearance: "none",
    cursor:       "pointer",
    outline:      "none",
  },
  selectArrow: {
    position:      "absolute",
    right:         "14px",
    top:           "50%",
    transform:     "translateY(-50%)",
    color:         "#4a6a9a",
    pointerEvents: "none",
    fontSize:      "14px",
  },
  textarea: {
    width:        "100%",
    minHeight:    "180px",
    padding:      "14px 16px",
    background:   "#111f36",
    border:       "1px solid #1a2f4e",
    borderRadius: "12px",
    color:        "#f0f4ff",
    fontFamily:   "monospace",
    fontSize:     "12px",
    lineHeight:   1.6,
    resize:       "vertical",
    outline:      "none",
    boxSizing:    "border-box",
  },
  charCount: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "11px",
    color:      "#4a6a9a",
    margin:     "4px 0 0",
    textAlign:  "right",
  },
  errorBox: {
    background:   "rgba(231,76,60,0.1)",
    border:       "1px solid rgba(231,76,60,0.3)",
    borderRadius: "10px",
    padding:      "12px 14px",
    marginBottom: "12px",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontSize:     "13px",
    color:        "#e74c3c",
    display:      "flex",
    gap:          "8px",
    alignItems:   "flex-start",
  },
  submitBtn: {
    width:        "100%",
    padding:      "15px",
    borderRadius: "14px",
    border:       "none",
    background:   "#e8b84b",
    color:        "#080d1a",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontWeight:   700,
    fontSize:     "15px",
    cursor:       "pointer",
    letterSpacing:"0.02em",
    marginBottom: "14px",
    transition:   "opacity 150ms ease",
  },
  disclaimer: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "11px",
    color:      "#4a6a9a",
    textAlign:  "center",
    lineHeight: 1.5,
    margin:     "0 0 16px",
  },
  centered: {
    flex:           1,
    display:        "flex",
    flexDirection:  "column",
    alignItems:     "center",
    justifyContent: "center",
    padding:        "40px 32px",
    gap:            "12px",
    textAlign:      "center",
  },
  successIcon: {
    fontSize: "40px",
  },
  successTitle: {
    fontFamily: "var(--font-display, 'Cinzel', serif)",
    fontSize:   "18px",
    color:      "#f0f4ff",
    margin:     0,
  },
  successBody: {
    fontFamily: "var(--font-body, 'Nunito', sans-serif)",
    fontSize:   "14px",
    color:      "#8aacdb",
    margin:     0,
    maxWidth:   "280px",
    lineHeight: 1.5,
  },
  ctaBtn: {
    marginTop:    "12px",
    padding:      "13px 32px",
    borderRadius: "24px",
    border:       "none",
    background:   "#e8b84b",
    color:        "#080d1a",
    fontFamily:   "var(--font-body, 'Nunito', sans-serif)",
    fontWeight:   700,
    fontSize:     "14px",
    cursor:       "pointer",
  },
};
