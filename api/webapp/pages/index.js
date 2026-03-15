/**
 * pages/index.js
 * --------------
 * The single-page Mini App entry point.
 *
 * Manages two views (Home / Search) via React state — no file-based routing
 * needed since this is a SPA living inside a Telegram WebApp panel.
 *
 * Boot sequence:
 *   1. useTelegram() initialises Telegram.WebApp, returns initData
 *   2. POST /api/webapp/auth  →  user profile (first_name, favorites_count)
 *   3. GET  /api/webapp/featured  →  20 tracks with is_favorite flags
 *   4. Render Home screen with staggered entrance animations
 *
 * Search flow:
 *   - User switches to Search tab (view = 'search')
 *   - Input is autofocused
 *   - Keystrokes fire GET /api/webapp/search?q=... debounced by 300ms
 *   - Results replace the list in-place
 *
 * Play flow:
 *   - User taps ▶ on any track (featured or list)
 *   - POST /api/webapp/play  { track_id, action: "play" }
 *   - NowPlaying sheet slides up, shows status, auto-dismisses
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import { useTelegram } from '../hooks/useTelegram';
import { FeaturedCard, ListTrack } from '../components/TrackCard';
import BottomNav from '../components/BottomNav';
import NowPlaying from '../components/NowPlaying';

// ── API base URL — same origin as the Mini App (Vercel) ─────────────────────
// In dev, Next runs on :3001 and API on :5000, so we allow an override.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

// ── Crescent Moon SVG for the header logo ───────────────────────────────────
function CrescentIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path
        d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
        fill="#e8b84b"
        stroke="#e8b84b"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Skeleton loaders ─────────────────────────────────────────────────────────
function SkeletonFeatured() {
  return (
    <div className="featured-scroll">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="skeleton skeleton-featured"
          style={{ animationDelay: `${i * 120}ms` }} />
      ))}
    </div>
  );
}

function SkeletonList() {
  return (
    <div>
      {[...Array(6)].map((_, i) => (
        <div key={i} className="skeleton skeleton-track"
          style={{ animationDelay: `${i * 80}ms` }} />
      ))}
    </div>
  );
}

// ── Main Page Component ──────────────────────────────────────────────────────
export default function Home() {
  const { initData, tgUser, isReady, hapticImpact } = useTelegram();

  // ── State ──────────────────────────────────────────────────────────────────
  const [user,    setUser]    = useState(null);     // from /api/webapp/auth
  const [tracks,  setTracks]  = useState([]);        // from /api/webapp/featured
  const [loading, setLoading] = useState(true);
  const [authErr, setAuthErr] = useState(null);

  const [view,    setView]    = useState('home');    // 'home' | 'search'
  const [query,   setQuery]   = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const [nowPlaying, setNowPlaying] = useState(null);   // { track, status, error }

  const searchInputRef = useRef(null);
  const debounceRef    = useRef(null);

  // ── Auth header helper ─────────────────────────────────────────────────────
  const authHeader = useCallback(() => ({
    'Authorization': `tma ${initData}`,
    'Content-Type':  'application/json',
  }), [initData]);

  // ── Boot: authenticate then load featured tracks ───────────────────────────
  useEffect(() => {
    if (!isReady) return;

    async function boot() {
      setLoading(true);
      try {
        // Step 1: authenticate
        const authRes = await fetch(`${API_BASE}/api/webapp/auth`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ initData }),
        });
        const authData = await authRes.json();

        if (!authData.ok) {
          // Dev mode: the API returns 401 for empty initData — use tgUser fallback
          if (initData === 'dev_mode' && tgUser) {
            setUser({ first_name: tgUser.first_name, favorites_count: 0 });
          } else {
            setAuthErr(authData.error || 'Authentication failed.');
            setLoading(false);
            return;
          }
        } else {
          setUser(authData.user);
        }

        // Step 2: load featured tracks
        const featRes  = await fetch(`${API_BASE}/api/webapp/featured`, {
          headers: authHeader(),
        });
        const featData = await featRes.json();

        if (featData.ok) {
          setTracks(featData.tracks || []);
        } else {
          setAuthErr('Failed to load tracks.');
        }
      } catch (err) {
        console.error('Boot error:', err);
        setAuthErr('Connection error. Please try again.');
      } finally {
        setLoading(false);
      }
    }

    boot();
  }, [isReady, initData, tgUser, authHeader]);

  // ── Search: debounced query ────────────────────────────────────────────────
  useEffect(() => {
    if (view !== 'search') return;

    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (!query.trim()) {
        setResults([]);
        return;
      }
      setSearching(true);
      try {
        const res  = await fetch(
          `${API_BASE}/api/webapp/search?q=${encodeURIComponent(query)}`,
          { headers: authHeader() }
        );
        const data = await res.json();
        setResults(data.ok ? (data.tracks || []) : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => clearTimeout(debounceRef.current);
  }, [query, view, authHeader]);

  // ── Autofocus search input when switching to search view ──────────────────
  useEffect(() => {
    if (view === 'search') {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [view]);

  // ── Handle view switch ─────────────────────────────────────────────────────
  function handleViewChange(v) {
    setView(v);
    if (v === 'home') {
      setQuery('');
      setResults([]);
    }
  }

  // ── Play a track ───────────────────────────────────────────────────────────
  const handlePlay = useCallback(async (track) => {
    hapticImpact('medium');
    setNowPlaying({ track, status: 'sending', error: null });

    try {
      const res  = await fetch(`${API_BASE}/api/webapp/play`, {
        method:  'POST',
        headers: authHeader(),
        body:    JSON.stringify({ track_id: track.id, action: 'play' }),
      });
      const data = await res.json();

      if (data.ok) {
        setNowPlaying((p) => ({ ...p, status: 'sent' }));
        hapticImpact('light');
      } else {
        setNowPlaying((p) => ({ ...p, status: 'error', error: data.error }));
        hapticImpact('heavy');
      }
    } catch {
      setNowPlaying((p) => ({ ...p, status: 'error', error: 'Connection error.' }));
    }
  }, [authHeader, hapticImpact]);

  // ── Toggle favorite ────────────────────────────────────────────────────────
  const handleFavorite = useCallback(async (track) => {
    hapticImpact('light');
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/play`, {
        method:  'POST',
        headers: authHeader(),
        body:    JSON.stringify({ track_id: track.id, action: 'favorite' }),
      });
      const data = await res.json();
      return data.ok;
    } catch {
      return false;
    }
  }, [authHeader, hapticImpact]);

  // ── Loading screen ─────────────────────────────────────────────────────────
  if (!isReady || loading) {
    return (
      <>
        <Head><title>Al-Madih</title></Head>
        <div className="loading-screen">
          <div style={{ fontSize: 32, marginBottom: 4 }}>🌙</div>
          <div className="loading-logo">AL-MADIH</div>
          <div className="loading-dots">
            <div className="loading-dot" />
            <div className="loading-dot" />
            <div className="loading-dot" />
          </div>
        </div>
      </>
    );
  }

  // ── Error screen ───────────────────────────────────────────────────────────
  if (authErr) {
    return (
      <>
        <Head><title>Al-Madih</title></Head>
        <div className="loading-screen">
          <div style={{ fontSize: 36 }}>⚠️</div>
          <div style={{
            color: 'var(--text-secondary)', fontSize: 14, textAlign: 'center',
            padding: '0 32px', lineHeight: 1.6,
          }}>
            {authErr}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Please open this via @Almadihbot
          </div>
        </div>
      </>
    );
  }

  // Split tracks: top 5 go to featured horizontal scroll, rest to catalog list
  const featuredTracks = tracks.slice(0, 5);
  const catalogTracks  = tracks.slice(5);

  // ── Main render ────────────────────────────────────────────────────────────
  return (
    <>
      <Head>
        <title>Al-Madih</title>
      </Head>

      <div className="app-shell">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <header className="header">
          <div className="header-brand">
            <div className="header-logo">
              <CrescentIcon />
            </div>
            <div>
              <div className="header-title">AL-MADIH</div>
              {user && (
                <div className="header-greeting">
                  مرحباً، {user.first_name}
                </div>
              )}
            </div>
          </div>

          {user && (
            <div className="header-user">
              <div className="user-avatar">
                {(user.first_name?.[0] || 'U').toUpperCase()}
              </div>
            </div>
          )}
        </header>

        {/* ── Scroll area ─────────────────────────────────────────────────── */}
        <main className="scroll-container">

          {/* ════════════════════════════════════════════ HOME VIEW */}
          {view === 'home' && (
            <div className="view-enter">

              {/* Featured section */}
              <div className="section-header">
                <div className="section-title">
                  ✨ Featured
                </div>
                <div className="section-count">{featuredTracks.length} tracks</div>
              </div>

              {featuredTracks.length === 0 ? (
                <SkeletonFeatured />
              ) : (
                <div className="featured-scroll">
                  {featuredTracks.map((track, i) => (
                    <FeaturedCard
                      key={track.id}
                      track={track}
                      onPlay={handlePlay}
                      onFavorite={handleFavorite}
                      style={{ animationDelay: `${i * 60}ms` }}
                    />
                  ))}
                </div>
              )}

              {/* Catalog section */}
              <div className="section-header" style={{ marginTop: 8 }}>
                <div className="section-title">
                  📂 Catalog
                </div>
                <div className="section-count">
                  {tracks.length > 0 ? `${tracks.length} total` : ''}
                </div>
              </div>

              {catalogTracks.length === 0 && tracks.length === 0 ? (
                <SkeletonList />
              ) : (
                <div className="track-list">
                  {catalogTracks.map((track, i) => (
                    <ListTrack
                      key={track.id}
                      track={track}
                      onPlay={handlePlay}
                      onFavorite={handleFavorite}
                      index={i}
                    />
                  ))}
                </div>
              )}

            </div>
          )}

          {/* ════════════════════════════════════════════ SEARCH VIEW */}
          {view === 'search' && (
            <div className="view-enter">

              <div className="search-container">
                <div className="search-input-wrap">
                  {/* Search icon */}
                  <div className="search-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                      <circle cx="11" cy="11" r="7" />
                      <path d="M21 21l-4.35-4.35" />
                    </svg>
                  </div>

                  <input
                    ref={searchInputRef}
                    className="search-input"
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="ابحث عن منظومة..."
                    autoComplete="off"
                    autoCorrect="off"
                    spellCheck={false}
                    aria-label="Search for a Menzuma"
                  />

                  {query && (
                    <button
                      className="search-clear"
                      onClick={() => { setQuery(''); setResults([]); }}
                      aria-label="Clear search"
                    >
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                        <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"/>
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {/* Empty state */}
              {!query && !searching && (
                <div className="search-empty">
                  <div className="search-empty-icon">🌙</div>
                  <p>Start typing to search<br />over 1,000+ Menzumas</p>
                </div>
              )}

              {/* Searching indicator */}
              {searching && (
                <div style={{ padding: '20px 20px 0', display: 'flex', gap: 6 }}>
                  {[0,1,2].map(i => (
                    <div key={i} className="loading-dot"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              )}

              {/* No results */}
              {query && !searching && results.length === 0 && (
                <div className="no-results">
                  <strong>😔 አልተገኘም</strong>
                  Try a different search term
                </div>
              )}

              {/* Search results */}
              {results.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div className="section-header">
                    <div className="section-title">Results</div>
                    <div className="section-count">{results.length} found</div>
                  </div>
                  <div className="track-list">
                    {results.map((track, i) => (
                      <ListTrack
                        key={track.id}
                        track={track}
                        onPlay={handlePlay}
                        onFavorite={handleFavorite}
                        index={i}
                      />
                    ))}
                  </div>
                </div>
              )}

            </div>
          )}

        </main>

        {/* ── Bottom Navigation ────────────────────────────────────────────── */}
        <BottomNav view={view} onViewChange={handleViewChange} />

        {/* ── NowPlaying Sheet ─────────────────────────────────────────────── */}
        {nowPlaying && (
          <NowPlaying
            track={nowPlaying.track}
            status={nowPlaying.status}
            error={nowPlaying.error}
            onDismiss={() => setNowPlaying(null)}
          />
        )}

      </div>
    </>
  );
}
