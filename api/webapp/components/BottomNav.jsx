/**
 * BottomNav.jsx
 * -------------
 * Two-tab navigation bar fixed to the bottom of the screen.
 * Respects iOS safe-area-inset-bottom via CSS env() variables in globals.css.
 */

function HomeIcon({ active }) {
  const c = active ? '#e8b84b' : '#4a6a9a';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path
        d="M3 12L12 3l9 9"
        stroke={c} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d="M9 21V12h6v9"
        stroke={c} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d="M5 10v11h14V10"
        stroke={c} strokeWidth={active ? 2.2 : 1.8} strokeLinecap="round" strokeLinejoin="round"
        fill={active ? 'rgba(232,184,75,0.1)' : 'none'}
      />
    </svg>
  );
}

function SearchIcon({ active }) {
  const c = active ? '#e8b84b' : '#4a6a9a';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle
        cx="11" cy="11" r="7"
        stroke={c} strokeWidth={active ? 2.2 : 1.8}
        fill={active ? 'rgba(232,184,75,0.1)' : 'none'}
      />
      <path
        d="M21 21l-4.35-4.35"
        stroke={c} strokeWidth={2} strokeLinecap="round"
      />
    </svg>
  );
}

export default function BottomNav({ view, onViewChange }) {
  return (
    <nav className="bottom-nav" aria-label="Main navigation">
      <div className="nav-items">

        <button
          className={`nav-item ${view === 'home' ? 'active' : ''}`}
          onClick={() => onViewChange('home')}
          aria-label="Home"
          aria-current={view === 'home' ? 'page' : undefined}
        >
          <HomeIcon active={view === 'home'} />
          <span>Home</span>
          <div className="nav-indicator" />
        </button>

        <button
          className={`nav-item ${view === 'search' ? 'active' : ''}`}
          onClick={() => onViewChange('search')}
          aria-label="Search"
          aria-current={view === 'search' ? 'page' : undefined}
        >
          <SearchIcon active={view === 'search'} />
          <span>Search</span>
          <div className="nav-indicator" />
        </button>

      </div>
    </nav>
  );
}
