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
 * Deterministic gradient background from a track ID.
 * Uses the last 6 hex chars of the MongoDB ObjectId as a seed.
 * Produces unique, harmonious dark gradients in the blue-teal-indigo range.
 */
function trackGradient(id = '') {
  const seed = parseInt(id.slice(-6) || 'a0b0c0', 16);
  const h1   = (seed % 100) + 190;   // 190–290: blue → violet
  const h2   = h1 + 25;
  const s1   = 45 + (seed % 20);
  const s2   = 60 + (seed % 25);
  return `linear-gradient(145deg, hsl(${h1},${s1}%,18%) 0%, hsl(${h2},${s2}%,12%) 100%)`;
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
function FeaturedCard({ track, onPlay, onFavorite, style }) {
  const [isFav, setIsFav] = useState(track.is_favorite);
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
    setIsFav((v) => !v);   // optimistic
    const ok = await onFavorite(track);
    if (!ok) setIsFav((v) => !v); // revert on error
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
function ListTrack({ track, onPlay, onFavorite, index }) {
  const [isFav, setIsFav] = useState(track.is_favorite);
  const [playing, setPlaying] = useState(false);

  const handlePlay = async () => {
    if (playing) return;
    setPlaying(true);
    await onPlay(track);
    setTimeout(() => setPlaying(false), 2000);
  };

  const handleFav = async (e) => {
    e.stopPropagation();
    setIsFav((v) => !v);
    const ok = await onFavorite(track);
    if (!ok) setIsFav((v) => !v);
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
