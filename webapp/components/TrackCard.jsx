/**
 * TrackCard.jsx
 * -------------
 * Renders a single Menzuma track.
 *
 * variant="featured"  → large card for horizontal featured scroll
 * variant="list"      → compact row for the full catalog list
 */

import { useState } from 'react';

/**
 * Rich deterministic cover art system.
 *
 * Each track gets a unique visual identity derived from its MongoDB ObjectId.
 * Uses 8 carefully curated color palettes — all warm/jewel-toned for Islamic
 * aesthetic coherence — rotated based on a hash of the track ID.
 * The result looks like a real music app cover grid, not a generic fallback.
 */
const COVER_PALETTES = [
  // [angle, color1, color2, accent]
  ['145deg', '#1a2744', '#0f3460', '#e8b84b'],   // navy → midnight blue, gold accent
  ['135deg', '#1f1035', '#2d1b5e', '#9b59b6'],   // deep purple → violet
  ['160deg', '#0d2137', '#0a4a5e', '#00c9ff'],   // dark ocean → teal
  ['130deg', '#1a1208', '#3d2000', '#e8a020'],   // deep brown → amber
  ['150deg', '#0a2218', '#0d3d2a', '#2ecc71'],   // forest dark → emerald
  ['140deg', '#1f0a0a', '#4a1010', '#e74c3c'],   // deep crimson → red
  ['155deg', '#0f0f2e', '#1a1a5e', '#4a90d9'],   // midnight → cobalt
  ['145deg', '#1a0f2e', '#2d1a5e', '#7c5cbf'],   // indigo → purple
];

function trackGradient(id = '') {
  const seed     = parseInt(id.slice(-8) || 'a0b0c0d0', 16);
  const palette  = COVER_PALETTES[seed % COVER_PALETTES.length];
  const [angle, c1, c2] = palette;
  // Add a subtle mid-stop derived from the track ID for variety within each palette
  const midL = 15 + (seed % 10);
  const midH = parseInt(id.slice(-4, -2) || 'a0', 16) % 360;
  return `linear-gradient(${angle}, ${c1} 0%, hsl(${midH},40%,${midL}%) 55%, ${c2} 100%)`;
}

function trackAccentColor(id = '') {
  const seed = parseInt(id.slice(-8) || 'a0b0c0d0', 16);
  return COVER_PALETTES[seed % COVER_PALETTES.length][3];
}

/** Tiny waveform SVG — used as the track "cover art" placeholder */
function WaveformIcon({ size = 18, color = 'currentColor' }) {
  const bars = [3, 6, 9, 7, 4, 8, 5, 3, 7, 5];
  const w    = bars.length * 3 - 1;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${w} 10`} fill="none">
      {bars.map((h, i) => (
        <rect
          key={i}
          x={i * 3}
          y={(10 - h) / 2}
          width={2}
          height={h}
          rx={1}
          fill={color}
          opacity={0.7 + (i % 3) * 0.1}
        />
      ))}
    </svg>
  );
}

/** Play triangle SVG */
function PlayIcon({ size = 14, color = '#080d1a' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill={color}>
      <path d="M2 1.5l9 4.5-9 4.5V1.5z" />
    </svg>
  );
}

/** Heart icon */
function HeartIcon({ size = 14, filled = false, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? color : 'none'} stroke={color} strokeWidth={2}>
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  );
}

/* ── Featured Card ─────────────────────────────────────────────────────────── */
function FeaturedCard({ track, onPlay, onFavorite, style, isFav: controlledFav }) {
  // Controlled mode: parent passes isFav → use it directly (synced global state).
  // Uncontrolled mode: parent omits isFav → manage locally (backwards compatible).
  const isControlled = controlledFav !== undefined;
  const [localFav, setLocalFav] = useState(track.is_favorite);
  const isFav = isControlled ? controlledFav : localFav;

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
      setLocalFav((v) => !v);   // optimistic (uncontrolled)
      const ok = await onFavorite(track);
      if (!ok) setLocalFav((v) => !v);
    } else {
      await onFavorite(track);  // parent handles optimistic update
    }
  };

  return (
    <div
      className="featured-card"
      style={style}
      onClick={handlePlay}
      role="button"
      aria-label={`Play ${track.name}`}
    >
      {/* Gradient background unique to this track */}
      <div
        className="featured-card-bg"
        style={{ background: trackGradient(track.id), position: 'absolute', inset: 0 }}
      />

      {/* Subtle waveform pattern in the background */}
      <div style={{
        position: 'absolute', inset: 0, display: 'flex',
        alignItems: 'center', justifyContent: 'center', opacity: 0.12,
      }}>
        <WaveformIcon size={80} color="#fff" />
      </div>

      <div className="featured-card-overlay" />

      {/* Favorite button */}
      <button
        className="featured-card-fav"
        onClick={handleFav}
        aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}
      >
        <HeartIcon size={13} filled={isFav} color={isFav ? '#e8b84b' : '#f0f4ff'} />
      </button>

      {/* Bottom: name + play button */}
      <div className="featured-card-body">
        <div className="featured-card-name">{track.name}</div>
        <button className="featured-card-play" onClick={handlePlay} aria-label="Play">
          {playing ? (
            <span style={{ fontSize: 10 }}>✓</span>
          ) : (
            <PlayIcon size={12} color="#080d1a" />
          )}
        </button>
      </div>
    </div>
  );
}

/* ── List Row ──────────────────────────────────────────────────────────────── */
function ListTrack({ track, onPlay, onFavorite, index, isFav: controlledFav }) {
  const isControlled = controlledFav !== undefined;
  const [localFav, setLocalFav] = useState(track.is_favorite);
  const isFav = isControlled ? controlledFav : localFav;

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

  return (
    <div
      className="track-item"
      style={{ animationDelay: `${index * 35}ms` }}
      onClick={handlePlay}
      role="button"
      aria-label={`Play ${track.name}`}
    >
      {/* Thumbnail */}
      <div
        className="track-thumb"
        style={{ background: trackGradient(track.id) }}
      >
        <WaveformIcon size={18} color="rgba(255,255,255,0.5)" />
        <div className="track-thumb-play-overlay">
          <PlayIcon size={12} color="#fff" />
        </div>
      </div>

      {/* Track info */}
      <div className="track-info">
        <div className="track-name">{track.name}</div>
        <div className="track-sub">@Almadihbot</div>
      </div>

      {/* Actions */}
      <div className="track-actions" onClick={(e) => e.stopPropagation()}>
        <button
          className={`btn-icon ${isFav ? 'is-fav' : ''}`}
          onClick={handleFav}
          aria-label={isFav ? 'Remove from favorites' : 'Add to favorites'}
        >
          <HeartIcon size={15} filled={isFav} color={isFav ? '#e8b84b' : 'currentColor'} />
        </button>
        <button className="btn-play" onClick={handlePlay} aria-label="Play">
          {playing ? (
            <span style={{ fontSize: 11, color: '#e8b84b' }}>✓</span>
          ) : (
            <PlayIcon size={11} color="#e8b84b" />
          )}
        </button>
      </div>
    </div>
  );
}

/* ── Public exports ────────────────────────────────────────────────────────── */
export { FeaturedCard, ListTrack, trackGradient };
