/**
 * ErrorState.jsx
 * --------------
 * Reusable branded error card used across all three views.
 *
 * Props:
 *   icon      string   emoji icon  (default "⚠️")
 *   title     string   bold headline
 *   message   string   body copy
 *   onRetry   fn|null  if provided, renders a "Try Again" button
 *   compact   bool     smaller padding for inline use (e.g. library section)
 */
export default function ErrorState({
  icon    = '⚠️',
  title   = 'Something went wrong',
  message = 'Please try again.',
  onRetry = null,
  compact = false,
}) {
  return (
    <div className={`error-state ${compact ? 'error-state--compact' : ''}`}>
      <div className="error-state-icon">{icon}</div>
      <div className="error-state-title">{title}</div>
      {message && (
        <div className="error-state-message">{message}</div>
      )}
      {onRetry && (
        <button className="retry-btn" onClick={onRetry}>
          <span className="retry-btn-icon">↺</span>
          Try Again
        </button>
      )}
    </div>
  );
}
