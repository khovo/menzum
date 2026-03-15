/**
 * Library.jsx
 * -----------
 * Personal Library screen — two sections:
 *
 *   📊 Stats Row    — total plays + total favorites as glowing stat cards,
 *                     plus up to 3 "Most Played" tracks
 *
 *   ❤️ Favorites    — full scrollable list of the user's hearted tracks,
 *                     identical ListTrack component as Home/Search
 *
 * Props:
 *   stats        { total_plays, total_favorites, most_played[] }
 *   favorites    TrackCard[]
 *   loading      boolean
 *   onPlay       (track) => Promise<void>
 *   onFavorite   (track) => Promise<bool>
 *   onUnfavorite (track) => void   — removes track from local list immediately
 */

import { useState, useCallback } from 'react';
import { ListTrack } from './TrackCard';

// ── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ value, label, icon, delay = 0 }) {
  return (
    <div
      className="stat-card"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="stat-icon">{icon}</div>
      <div className="stat-value">{value?.toLocaleString() ?? 0}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

// ── Most Played Row ───────────────────────────────────────────────────────────
function MostPlayedItem({ track, rank, onPlay }) {
  const [playing, setPlaying] = useState(false);

  const rankColors = ['#e8b84b', '#8aacdb', '#6b8cb0'];
  const rankBg     = ['rgba(232,184,75,0.12)', 'rgba(138,172,219,0.08)', 'rgba(107,140,176,0.06)'];

  return (
    <div
      className="most-played-item"
      style={{ background: rankBg[rank] }}
      onClick={async () => {
        if (playing) return;
        setPlaying(true);
        await onPlay(track);
        setTimeout(() => setPlaying(false), 2000);
      }}
      role="button"
    >
      <div className="most-played-rank" style={{ color: rankColors[rank] }}>
        #{rank + 1}
      </div>
      <div className="most-played-info">
        <div className="most-played-name">{track.name}</div>
        <div className="most-played-count">
          {track.play_count} {track.play_count === 1 ? 'play' : 'plays'}
        </div>
      </div>
      <div className="most-played-play" style={{ color: rankColors[rank] }}>
        {playing ? '✓' : '▶'}
      </div>
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────
function EmptyFavorites() {
  return (
    <div className="library-empty">
      <div className="library-empty-icon">🌙</div>
      <div className="library-empty-title">No Favorites Yet</div>
      <div className="library-empty-sub">
        Tap ❤️ on any track in Home or Search to save it here.
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────
function LibrarySkeleton() {
  return (
    <div>
      {/* Stats skeleton */}
      <div style={{ display: 'flex', gap: 12, padding: '8px 20px 20px' }}>
        <div className="skeleton" style={{ flex: 1, height: 90, borderRadius: 16 }} />
        <div className="skeleton" style={{ flex: 1, height: 90, borderRadius: 16 }} />
      </div>
      {/* List skeleton */}
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton skeleton-track"
          style={{ animationDelay: `${i * 80}ms` }} />
      ))}
    </div>
  );
}

// ── Main Library Component ────────────────────────────────────────────────────
export default function Library({ stats, favorites: initialFavorites, loading, onPlay, onFavorite }) {
  // Local copy of favorites so we can reflect un-fav immediately without refetch
  const [favorites, setFavorites] = useState(initialFavorites ?? []);

  // Sync when parent data arrives (first load)
  if (initialFavorites && initialFavorites !== favorites && favorites.length === 0 && initialFavorites.length > 0) {
    setFavorites(initialFavorites);
  }

  const handleFavorite = useCallback(async (track) => {
    // Optimistically remove from list — tapping ❤️ on a favorited track un-favs it
    setFavorites((prev) => prev.filter((t) => t.id !== track.id));
    const ok = await onFavorite(track);
    if (!ok) {
      // Revert if the API call failed
      setFavorites((prev) => [track, ...prev]);
    }
    return ok;
  }, [onFavorite]);

  if (loading) return <LibrarySkeleton />;

  const hasMostPlayed = stats?.most_played?.length > 0;
  const hasFavorites  = favorites.length > 0;

  return (
    <div className="view-enter">

      {/* ── Stats Row ──────────────────────────────────────────────────────── */}
      <div className="section-header" style={{ paddingBottom: 8 }}>
        <div className="section-title">📊 Your Stats</div>
      </div>

      <div className="stats-row">
        <StatCard
          value={stats?.total_plays ?? 0}
          label="Total Plays"
          icon="🎵"
          delay={0}
        />
        <StatCard
          value={stats?.total_favorites ?? 0}
          label="Favorites"
          icon="❤️"
          delay={60}
        />
      </div>

      {/* ── Most Played ────────────────────────────────────────────────────── */}
      {hasMostPlayed && (
        <>
          <div className="section-header" style={{ marginTop: 8 }}>
            <div className="section-title">🔥 Most Played</div>
            <div className="section-count">Top {stats.most_played.length}</div>
          </div>
          <div className="most-played-list">
            {stats.most_played.map((track, i) => (
              <MostPlayedItem
                key={track.track_id}
                track={track}
                rank={i}
                onPlay={onPlay}
              />
            ))}
          </div>
        </>
      )}

      {/* ── Favorites List ─────────────────────────────────────────────────── */}
      <div className="section-header" style={{ marginTop: 12 }}>
        <div className="section-title">❤️ My Favorites</div>
        <div className="section-count">
          {favorites.length > 0 ? `${favorites.length} saved` : ''}
        </div>
      </div>

      {!hasFavorites ? (
        <EmptyFavorites />
      ) : (
        <div className="track-list">
          {favorites.map((track, i) => (
            <ListTrack
              key={track.id}
              track={track}
              onPlay={onPlay}
              onFavorite={handleFavorite}
              index={i}
            />
          ))}
        </div>
      )}

    </div>
  );
}
