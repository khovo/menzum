/**
 * TrackCard.jsx
 * -------------
 * Renders a single Menzuma track.
 *
 * variant="featured"  → large card for horizontal featured scroll
 * variant="list"      → compact row for the full catalog list
 *
 * PHASE B — Cover Images:
 *   Tracks with thumb_file_id show their Telegram thumbnail via the
 *   /api/webapp/thumb proxy. Tracks without show a deterministic gradient.
 *
 * V4 — Lyrics Button (always visible):
 *   track.has_lyrics === true  →  "📖 Lyrics"   navigates to /lyrics
 *   track.has_lyrics === false →  "+ Lyrics"  navigates to /submit-lyrics
 *   The button is always rendered so users can always reach the submission
 *   form even when the lyrics database is empty.
 */

import { useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

const COVER_PALETTES = [
  ['145deg', '#1a2744', '#0f3460', '#e8b84b'],
  ['135deg', '#1f1035', '#2d1b5e', '#9b59b6'],
  ['160deg', '#0d2137', '#0a4a5e', '#00c9ff'],
  ['130deg', '#1a1208', '#3d2000', '#e8a020'],
  ['150deg', '#0a2218', '#0d3d2a', '#2ecc71'],
  ['140deg', '#1f0a0a', '#4a1010', '#e74c3c'],
  ['155deg', '#0f0f2e', '#1a1a5e', '#4a90d9'],
  ['145deg', '#1a0f2e', '#2d1a5e', '#7c5cbf'],
];

function trackGradient(id = '') {
  const seed    = parseInt(id.slice(-8) || 'a0b0c0d0', 16);
  const palette = COVER_PALETTES[seed % COVER_PALETTES.length];
  const [angle, c1, c2] = palette;
  const midL = 15 + (seed % 10);
  const midH = parseInt(id.slice(-4, -2) || 'a0', 16) % 360;
  return 'linear-gradient(' + angle + ', ' + c1 + ' 0%, hsl(' + midH + ',40%,' + midL + '%) 55%, ' + c2 + ' 100%)';
}

function trackAccentColor(id = '') {
  const seed = parseInt(id.slice(-8) || 'a0b0c0d0', 16);
  return COVER_PALETTES[seed % COVER_PALETTES.length][3];
}

/**
 * CoverImage — gradient always rendered as background, img layered on top.
 * If image loads: covers gradient. If image errors: gradient shows through.
 * If has_thumb is false: no img at all — zero wasted network request.
 */
function CoverImage({ track, fill = false, children }) {
  const [imgFailed, setImgFailed] = useState(false);
  const gradient = trackGradient(track.id);
  const thumbUrl = track.has_thumb && !imgFailed
    ? API_BASE + '/api/webapp/thumb?id=' + track.id
    : null;

  const baseStyle = fill
    ? { position: 'absolute', inset: 0 }
    : { position: 'relative', width: '100%', height: '100%' };

  return (
    <div style={{ ...baseStyle, background: gradient, overflow: 'hidden' }}>
      {thumbUrl && (
        <img
          src={thumbUrl}
          alt=""
          aria-hidden="true"
          onError={() => setImgFailed(true)}
          draggable={false}
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%',
            objectFit: 'cover',
            opacity: 1,
            transition: 'opacity 300ms ease',
          }}
        />
      )}
      {children}
    </div>
  );
}

function WaveformIcon({ size = 18, color = 'currentColor' }) {
  const bars = [3, 6, 9, 7, 4, 8, 5, 3, 7, 5];
  const w    = bars.length * 3 - 1;
  return (
    <svg width={size} height={size} viewBox={'0 0 ' + w + ' 10'} fill="none">
      {bars.map((h, i) => (
        <rect key={i} x={i * 3} y={(10 - h) / 2} width={2} height={h} rx={1}
          fill={color} opacity={0.7 + (i % 3) * 0.1} />
      ))}
    </svg>
  );
}

function PlayIcon({ size = 14, color = '#080d1a' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill={color}>
      <path d="M2 1.5l9 4.5-9 4.5V1.5z" />
    </svg>
  );
}

function HeartIcon({ size = 14, filled = false, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
      fill={filled ? color : 'none'} stroke={color} strokeWidth={2}>
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  );
}

/**
 * Navigate to the lyrics player page (approved lyrics exist).
 * Uses window.location — avoids importing next/router into this component.
 */
function openLyricsPage(track) {
  const nameParam = track.name ? '&name=' + encodeURIComponent(track.name) : '';
  window.location.href = '/lyrics?track_id=' + track.id + nameParam;
}

/**
 * Navigate to the lyrics submission form (no approved lyrics yet).
 */
function openSubmitPage(track) {
  const nameParam = track.name ? '&name=' + encodeURIComponent(track.name) : '';
  window.location.href = '/submit-lyrics?track_id=' + track.id + nameParam;
}

/**
 * Unified handler: routes to player if lyrics exist, submission form if not.
 */
function handleLyricsClick(e, track) {
  e.stopPropagation();
  if (track.has_lyrics) {
    openLyricsPage(track);
  } else {
    openSubmitPage(track);
  }
}

function FeaturedCard({ track, onPlay, onFavorite, style, isFav: controlledFav }) {
  const isControlled = controlledFav !== undefined;
  const [localFav, setLocalFav] = useState(track.is_favorite);
  const isFav    = isControlled ? controlledFav : localFav;
  const [playing, setPlaying] = useState(false);

  const handlePlay = async (e) => {
    e.stopPropagation();
    if (playing) return;
    setPlaying(true);
    await onPlay(track);
    setTimeout(() => setPlaying(false), 2000);
  };

  const handleFav = async (e) => {
    e.stopPropagation();
    if (!isControlled) {
      setLocalFav((v) => !v);
      const ok = await onFavorite(track);
      if (!ok) setLocalFav((v) => !v);
    } else {
      await onFavorite(track);
    }
  };

  // Label and aria-label change based on whether lyrics exist
  const lyricsLabel    = track.has_lyrics ? 'View lyrics' : 'Add lyrics';
  const lyricsEmoji    = track.has_lyrics ? '📖' : '➕';
  const lyricsText     = track.has_lyrics ? 'Lyrics' : 'Add Lyrics';
  // Muted border when no lyrics yet; gold when lyrics exist
  const lyricsBorder   = track.has_lyrics
    ? '1px solid rgba(232,184,75,0.45)'
    : '1px solid rgba(255,255,255,0.15)';
  const lyricsColor    = track.has_lyrics ? '#e8b84b' : 'rgba(240,244,255,0.6)';

  return (
    <div className="featured-card" style={style} onClick={handlePlay}
      role="button" aria-label={'Play ' + track.name}>

      <CoverImage track={track} fill>
        {!track.has_thumb && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center', opacity: 0.12,
          }}>
            <WaveformIcon size={80} color="#fff" />
          </div>
        )}
      </CoverImage>

      <div className="featured-card-overlay" />

      {/* Lyrics badge — top-left, always visible */}
      <button
        onClick={(e) => handleLyricsClick(e, track)}
        aria-label={lyricsLabel}
        style={{
          position:       'absolute',
          top:            8,
          left:           8,
          background:     'rgba(8,13,26,0.72)',
          border:         lyricsBorder,
          borderRadius:   '6px',
          padding:        '3px 7px',
          cursor:         'pointer',
          display:        'flex',
          alignItems:     'center',
          gap:            '3px',
          backdropFilter: 'blur(4px)',
        }}
      >
        <span style={{ fontSize: 10 }}>{lyricsEmoji}</span>
        <span style={{
          fontFamily:    "var(--font-body, 'Nunito', sans-serif)",
          fontSize:      9,
          fontWeight:    700,
          color:         lyricsColor,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
        }}>
          {lyricsText}
        </span>
      </button>

      <button className="featured-card-fav" onClick={handleFav}
        aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}>
        <HeartIcon size={13} filled={isFav} color={isFav ? '#e8b84b' : '#f0f4ff'} />
      </button>

      <div className="featured-card-body">
        <div className="featured-card-name">{track.name}</div>
        <button className="featured-card-play" onClick={handlePlay} aria-label="Play">
          {playing ? <span style={{ fontSize: 10 }}>✓</span> : <PlayIcon size={12} color="#080d1a" />}
        </button>
      </div>
    </div>
  );
}

function ListTrack({ track, onPlay, onFavorite, index, isFav: controlledFav }) {
  const isControlled = controlledFav !== undefined;
  const [localFav, setLocalFav] = useState(track.is_favorite);
  const isFav    = isControlled ? controlledFav : localFav;
  const [playing, setPlaying] = useState(false);

  const handlePlay = async () => {
    if (playing) return;
    setPlaying(true);
    await onPlay(track);
    setTimeout(() => setPlaying(false), 2000);
  };

  const handleFav = async (e) => {
    e.stopPropagation();
    if (!isControlled) {
      setLocalFav((v) => !v);
      const ok = await onFavorite(track);
      if (!ok) setLocalFav((v) => !v);
    } else {
      await onFavorite(track);
    }
  };

  const lyricsEmoji = track.has_lyrics ? '📖' : '➕';
  const lyricsTitle = track.has_lyrics ? 'View lyrics' : 'Add lyrics';
  const lyricsColor = track.has_lyrics ? '#e8b84b' : 'var(--text-muted, #4a6a9a)';

  return (
    <div className="track-item" style={{ animationDelay: (index * 35) + 'ms' }}
      onClick={handlePlay} role="button" aria-label={'Play ' + track.name}>

      <div className="track-thumb">
        <CoverImage track={track}>
          {!track.has_thumb && (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <WaveformIcon size={18} color="rgba(255,255,255,0.5)" />
            </div>
          )}
          <div className="track-thumb-play-overlay">
            <PlayIcon size={12} color="#fff" />
          </div>
        </CoverImage>
      </div>

      <div className="track-info">
        <div className="track-name">{track.name}</div>
        <div className="track-sub">@Almadihbot</div>
      </div>

      <div className="track-actions" onClick={(e) => e.stopPropagation()}>
        {/* Lyrics button — always rendered; emoji and destination vary by has_lyrics */}
        <button
          className="btn-icon"
          onClick={(e) => handleLyricsClick(e, track)}
          aria-label={lyricsTitle}
          title={lyricsTitle}
          style={{ color: lyricsColor }}
        >
          <span style={{ fontSize: 15 }}>{lyricsEmoji}</span>
        </button>

        <button className={'btn-icon ' + (isFav ? 'is-fav' : '')} onClick={handleFav}
          aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}>
          <HeartIcon size={15} filled={isFav} color={isFav ? '#e8b84b' : 'currentColor'} />
        </button>

        <button className="btn-play" onClick={handlePlay} aria-label="Play">
          {playing
            ? <span style={{ fontSize: 11, color: '#e8b84b' }}>✓</span>
            : <PlayIcon size={11} color="#e8b84b" />}
        </button>
      </div>
    </div>
  );
}

export { FeaturedCard, ListTrack, trackGradient };
