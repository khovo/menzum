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
import Library from '../components/Library';
import ErrorState from '../components/ErrorState';

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

  // ── Central favorites registry ────────────────────────────────────────────
  // Single source of truth for ALL views. A Set of track IDs (MongoDB ObjectId
  // strings). Every FeaturedCard, ListTrack, and Library row reads from here.
  // handleFavorite updates it optimistically — no stale state across tabs.
  const [favoritedIds, setFavoritedIds] = useState(() => new Set());

  const [view,     setView]    = useState('home');    // 'home' | 'search' | 'library'
  const [prevView, setPrevView] = useState(null);   // for directional transition
  const [query,    setQuery]   = useState('');
  const [results,  setResults] = useState([]);
  const [searching,  setSearching]  = useState(false);
  const [searchError, setSearchError] = useState(null);

  // ── Offline / connectivity ───────────────────────────────────────────────
  const [isOffline, setIsOffline] = useState(
    typeof navigator !== 'undefined' ? !navigator.onLine : false
  );

  // ── Pull-to-refresh (Home) ───────────────────────────────────────────────
  const [pulling,       setPulling]      = useState(false);
  const [pullDistance,  setPullDistance] = useState(0);
  const [refreshing,    setRefreshing]   = useState(false);
  const pullStartY = useRef(null);
  const PULL_THRESHOLD = 65;

  // ── Error states per-view ───────────────────────────────────────────────
  const [homeError,    setHomeError]    = useState(null);
  const [libraryError, setLibraryError] = useState(null);

  const [nowPlaying, setNowPlaying] = useState(null);   // { track, status, error }

  // ── Library state ───────────────────────────────────────────────────────
  const [libraryStats,     setLibraryStats]     = useState(null);
  const [libraryFavorites, setLibraryFavorites] = useState([]);
  const [libraryLoading,   setLibraryLoading]   = useState(false);
  const [libraryLoaded,    setLibraryLoaded]     = useState(false);

  const searchInputRef  = useRef(null);
  const debounceRef     = useRef(null);
  const sentinelRef     = useRef(null);   // Intersection Observer target for infinite scroll
  const observerRef     = useRef(null);   // holds the IntersectionObserver instance

  // ── Catalog infinite scroll state ─────────────────────────────────────────
  const [catalogCursor,    setCatalogCursor]    = useState(null);
  const [catalogHasMore,   setCatalogHasMore]   = useState(true);
  const [catalogLoading,   setCatalogLoading]   = useState(false);

  // ── Search pagination state ────────────────────────────────────────────────
  const [searchCursor,   setSearchCursor]   = useState(null);
  const [searchHasMore,  setSearchHasMore]  = useState(false);
  const [searchPageLoad, setSearchPageLoad] = useState(false);

  // ── Auth header helper ─────────────────────────────────────────────────────
  const authHeader = useCallback(() => ({
    'Authorization': `tma ${initData}`,
    'Content-Type':  'application/json',
  }), [initData]);

  // ── Offline detection ────────────────────────────────────────────────────
  useEffect(() => {
    function goOnline()  { setIsOffline(false); }
    function goOffline() { setIsOffline(true);  }
    window.addEventListener('online',  goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online',  goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, []);

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
          const loaded = featData.tracks || [];
          setTracks(loaded);
          // Seed catalog pagination cursor
          setCatalogCursor(featData.next_cursor ?? null);
          setCatalogHasMore(featData.has_more ?? false);
          // Seed the central favorites registry from the API's is_favorite flags
          setFavoritedIds(new Set(
            loaded.filter((t) => t.is_favorite).map((t) => t.id)
          ));
          setHomeError(null);
        } else {
          setHomeError('Failed to load tracks from the server.');
        }
      } catch (err) {
        console.error('Boot error:', err);
        // Only set authErr for auth failures — network errors show inline retry
        if (!user) {
          setAuthErr('Connection error. Please open via @Almadihbot.');
        } else {
          setHomeError('Connection error. Check your internet and try again.');
        }
      } finally {
        setLoading(false);
      }
    }

    boot();
  }, [isReady, initData, tgUser, authHeader]);

  // ── Catalog: load next page (called by IntersectionObserver) ─────────────
  const loadMoreCatalog = useCallback(async () => {
    if (catalogLoading || !catalogHasMore || !catalogCursor || isOffline) return;
    setCatalogLoading(true);
    try {
      const res  = await fetch(
        `${API_BASE}/api/webapp/featured?cursor=${catalogCursor}`,
        { headers: authHeader() }
      );
      const data = await res.json();
      if (data.ok) {
        const newTracks = data.tracks || [];
        setTracks((prev) => [...prev, ...newTracks]);
        setCatalogCursor(data.next_cursor ?? null);
        setCatalogHasMore(data.has_more ?? false);
        // Merge any newly-favorited tracks into the registry
        setFavoritedIds((prev) => {
          const next = new Set(prev);
          newTracks.filter((t) => t.is_favorite).forEach((t) => next.add(t.id));
          return next;
        });
      }
    } catch {
      // Silent fail — user can scroll up and back down to retry
    } finally {
      setCatalogLoading(false);
    }
  }, [catalogLoading, catalogHasMore, catalogCursor, isOffline, authHeader]);

  // ── Pull-to-refresh + retry: re-runs boot logic for Home ──────────────────
  const refreshHome = useCallback(async () => {
    if (refreshing || isOffline) return;
    setRefreshing(true);
    setHomeError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/featured`, { headers: authHeader() });
      const data = await res.json();
      if (data.ok) {
        setTracks(data.tracks || []);
        setCatalogCursor(data.next_cursor ?? null);
        setCatalogHasMore(data.has_more ?? false);
      } else {
        setHomeError('Failed to refresh. Try again.');
      }
    } catch {
      setHomeError('No connection. Pull down to retry.');
    } finally {
      setRefreshing(false);
    }
  }, [refreshing, isOffline, authHeader]);

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
      setSearchError(null);
      // Reset pagination on every new query
      setSearchCursor(null);
      setSearchHasMore(false);
      try {
        const res  = await fetch(
          `${API_BASE}/api/webapp/search?q=${encodeURIComponent(query)}`,
          { headers: authHeader() }
        );
        const data = await res.json();
        if (data.ok) {
          setResults(data.tracks || []);
          setSearchCursor(data.next_cursor ?? null);
          setSearchHasMore(data.has_more ?? false);
        } else {
          setResults([]);
          setSearchError('Search failed. Tap to retry.');
        }
      } catch {
        setResults([]);
        setSearchError('No connection. Tap to retry.');
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => clearTimeout(debounceRef.current);
  }, [query, view, authHeader]);

  // ── Intersection Observer: triggers loadMoreCatalog when sentinel is visible ─
  useEffect(() => {
    if (!sentinelRef.current) return;
    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMoreCatalog();
        }
      },
      { rootMargin: '200px' }   // start loading 200px before user reaches the bottom
    );
    observerRef.current.observe(sentinelRef.current);
    return () => observerRef.current?.disconnect();
  }, [loadMoreCatalog]);

  // ── Autofocus search input when switching to search view ──────────────────
  useEffect(() => {
    if (view === 'search') {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [view]);

  // ── Load library data (lazy — only fetches on first visit) ──────────────
  const loadLibrary = useCallback(async () => {
    if (libraryLoaded) return;  // already fetched this session
    setLibraryLoading(true);
    setLibraryError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/library`, {
        headers: authHeader(),
      });
      const data = await res.json();
      if (data.ok) {
        setLibraryStats(data.stats);
        const libFavs = data.favorites ?? [];
        setLibraryFavorites(libFavs);
        // Merge library favorites into the central registry
        setFavoritedIds((prev) => {
          const merged = new Set(prev);
          libFavs.forEach((t) => merged.add(t.id));
          return merged;
        });
        setLibraryLoaded(true);
        setLibraryError(null);
      } else {
        setLibraryError('Could not load your library.');
      }
    } catch {
      setLibraryError('No connection. Tap retry to try again.');
    } finally {
      setLibraryLoading(false);
    }
  }, [libraryLoaded, authHeader]);

  // ── Handle view switch ─────────────────────────────────────────────────────
  const VIEW_ORDER = { home: 0, search: 1, library: 2 };
  function handleViewChange(v) {
    if (v === view) return;
    setPrevView(view);
    setView(v);
    if (v === 'home') {
      setQuery('');
      setResults([]);
      setSearchError(null);
    }
    if (v === 'library') {
      // Reset so a retry re-fetches fresh
      if (libraryError) setLibraryLoaded(false);
      loadLibrary();
    }
  }

  // Compute CSS class for directional slide transition
  function viewTransitionClass(v) {
    if (!prevView || prevView === v) return 'view-enter';
    const curr = VIEW_ORDER[v]       ?? 0;
    const prev = VIEW_ORDER[prevView] ?? 0;
    return curr > prev ? 'view-slide-left' : 'view-slide-right';
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
    const wasLiked = favoritedIds.has(track.id);

    // 1. Optimistic update — flip immediately so ALL views update instantly
    setFavoritedIds((prev) => {
      const next = new Set(prev);
      if (wasLiked) next.delete(track.id);
      else          next.add(track.id);
      return next;
    });

    // 2. Also update libraryFavorites list for the Library view
    if (wasLiked) {
      setLibraryFavorites((prev) => prev.filter((t) => t.id !== track.id));
    } else {
      // Add to library list so it appears immediately without a refetch
      setLibraryFavorites((prev) => {
        if (prev.find((t) => t.id === track.id)) return prev;
        return [{ id: track.id, name: track.name ?? track.display_name, is_favorite: true }, ...prev];
      });
    }

    // 3. Persist to DB
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/play`, {
        method:  'POST',
        headers: authHeader(),
        body:    JSON.stringify({ track_id: track.id, action: 'favorite' }),
      });
      const data = await res.json();
      if (!data.ok) {
        // Revert both optimistic changes on failure
        setFavoritedIds((prev) => {
          const next = new Set(prev);
          if (wasLiked) next.add(track.id);
          else          next.delete(track.id);
          return next;
        });
        if (wasLiked) {
          setLibraryFavorites((prev) => [
            { id: track.id, name: track.name ?? track.display_name, is_favorite: true },
            ...prev,
          ]);
        } else {
          setLibraryFavorites((prev) => prev.filter((t) => t.id !== track.id));
        }
        return false;
      }
      return true;
    } catch {
      // Revert on network error
      setFavoritedIds((prev) => {
        const next = new Set(prev);
        if (wasLiked) next.add(track.id);
        else          next.delete(track.id);
        return next;
      });
      return false;
    }
  }, [authHeader, hapticImpact, favoritedIds]);

  // ── Search: load more results ────────────────────────────────────────────
  const loadMoreSearch = useCallback(async () => {
    if (searchPageLoad || !searchHasMore || !searchCursor || isOffline) return;
    setSearchPageLoad(true);
    try {
      const res  = await fetch(
        `${API_BASE}/api/webapp/search?q=${encodeURIComponent(query)}&cursor=${searchCursor}`,
        { headers: authHeader() }
      );
      const data = await res.json();
      if (data.ok) {
        const newTracks = data.tracks || [];
        setResults((prev) => [...prev, ...newTracks]);
        setSearchCursor(data.next_cursor ?? null);
        setSearchHasMore(data.has_more ?? false);
        setFavoritedIds((prev) => {
          const next = new Set(prev);
          newTracks.filter((t) => t.is_favorite).forEach((t) => next.add(t.id));
          return next;
        });
      }
    } catch {
      // Silent fail — button remains visible for retry
    } finally {
      setSearchPageLoad(false);
    }
  }, [searchPageLoad, searchHasMore, searchCursor, isOffline, authHeader, query]);

  // ── Pull-to-refresh touch handlers (Home view) ───────────────────────────
  const handleTouchStart = useCallback((e) => {
    if (view !== 'home') return;
    const scrollEl = e.currentTarget;
    if (scrollEl.scrollTop === 0) {
      pullStartY.current = e.touches[0].clientY;
    }
  }, [view]);

  const handleTouchMove = useCallback((e) => {
    if (pullStartY.current === null) return;
    const dist = e.touches[0].clientY - pullStartY.current;
    if (dist > 0 && dist < 120) {
      setPulling(true);
      setPullDistance(dist);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (pulling && pullDistance >= PULL_THRESHOLD) {
      refreshHome();
    }
    pullStartY.current = null;
    setPulling(false);
    setPullDistance(0);
  }, [pulling, pullDistance, refreshHome]);

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
        {/* ── Offline Banner ───────────────────────────────────────────────── */}
        {isOffline && (
          <div className="offline-banner" role="alert">
            <span>📡</span> No internet connection
          </div>
        )}

        <main
          className="scroll-container"
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          {/* ── Pull-to-refresh indicator ────────────────────────────────── */}
          {(pulling || refreshing) && (
            <div
              className="pull-indicator"
              style={{
                opacity:   Math.min(pullDistance / PULL_THRESHOLD, 1),
                transform: `translateY(${Math.min(pullDistance * 0.4, 24)}px) rotate(${refreshing ? 0 : pullDistance * 2}deg)`,
              }}
            >
              <div className={`pull-spinner ${refreshing ? 'pull-spinner--spinning' : ''}`}>
                ↺
              </div>
            </div>
          )}

          {/* ════════════════════════════════════════════ HOME VIEW */}
          {view === 'home' && (
            <div className={viewTransitionClass('home')}>

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
                      isFav={favoritedIds.has(track.id)}
                      style={{ animationDelay: `${i * 60}ms` }}
                    />
                  ))}
                </div>
              )}

              {/* Inline error for home refresh failures */}
              {homeError && !loading && (
                <div style={{ padding: '0 16px 8px' }}>
                  <ErrorState
                    icon="📡"
                    title="Couldn't load tracks"
                    message={homeError}
                    onRetry={refreshHome}
                    compact
                  />
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
                      isFav={favoritedIds.has(track.id)}
                      index={i}
                    />
                  ))}
                </div>
              )}

              {/* ── Infinite scroll sentinel + loading state ──────────────── */}
              {/* The IntersectionObserver watches this div. When it enters    */}
              {/* the viewport (200px before bottom), loadMoreCatalog() fires. */}
              <div ref={sentinelRef} style={{ height: 1 }} />
              {catalogLoading && (
                <div className="load-more-spinner">
                  <div className="loading-dot" />
                  <div className="loading-dot" />
                  <div className="loading-dot" />
                </div>
              )}
              {!catalogHasMore && tracks.length > 0 && (
                <div className="catalog-end-msg">
                  ✦ All {tracks.length} Menzumas loaded
                </div>
              )}

            </div>
          )}

          {/* ════════════════════════════════════════════ SEARCH VIEW */}
          {view === 'search' && (
            <div className={viewTransitionClass('search')}>

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

              {/* Search error */}
              {searchError && !searching && (
                <div style={{ padding: '20px 16px 0' }}>
                  <ErrorState
                    icon="🔍"
                    title="Search failed"
                    message={searchError}
                    onRetry={() => {
                      setSearchError(null);
                      setQuery((q) => q); // re-trigger debounce effect
                    }}
                    compact
                  />
                </div>
              )}

              {/* Search results */}
              {results.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div className="section-header">
                    <div className="section-title">Results</div>
                    <div className="section-count">
                      {results.length}{searchHasMore ? '+' : ''} found
                    </div>
                  </div>
                  <div className="track-list">
                    {results.map((track, i) => (
                      <ListTrack
                        key={track.id}
                        track={track}
                        onPlay={handlePlay}
                        onFavorite={handleFavorite}
                        isFav={favoritedIds.has(track.id)}
                        index={i}
                      />
                    ))}
                  </div>

                  {/* Load more button — explicit for search (better UX than auto-scroll) */}
                  {searchHasMore && (
                    <div className="load-more-row">
                      <button
                        className="load-more-btn"
                        onClick={loadMoreSearch}
                        disabled={searchPageLoad}
                      >
                        {searchPageLoad ? (
                          <span className="load-more-btn-inner">
                            <div className="loading-dot" />
                            <div className="loading-dot" />
                            <div className="loading-dot" />
                          </span>
                        ) : (
                          <span>Load more results ↓</span>
                        )}
                      </button>
                    </div>
                  )}
                </div>
              )}

            </div>
          )}

          {/* ════════════════════════════════════════════ LIBRARY VIEW */}
          {view === 'library' && (
            <div className={viewTransitionClass('library')}>
              <Library
                stats={libraryStats}
                favorites={libraryFavorites}
                loading={libraryLoading}
                error={libraryError}
                onRetry={() => { setLibraryLoaded(false); loadLibrary(); }}
                onPlay={handlePlay}
                onFavorite={handleFavorite}
              />
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
