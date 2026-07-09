/**
 * api/webapp/_rateLimit.js
 * ------------------------
 * Minimal in-memory rate limiter — best-effort, per warm serverless instance
 * only. Vercel runs many concurrent instances and this doesn't coordinate
 * across them, so it's not a hard global guarantee — but it's enough to
 * blunt a naive scraping/DoS loop against the endpoints that stream real
 * file bytes through the shared BOT_TOKEN (play.js, pdf-view.js), without
 * adding a paid Redis/KV dependency.
 *
 * The leading underscore tells Vercel not to treat this as a route.
 */

const buckets = new Map(); // key -> { count, resetAt }
const MAX_TRACKED_KEYS = 5000; // crude memory bound if many distinct IPs hit this

/** True if `key` has exceeded `max` requests within the current `windowMs` window. */
function isRateLimited(key, { max, windowMs }) {
  const now = Date.now();
  let bucket = buckets.get(key);
  if (!bucket || now > bucket.resetAt) {
    if (buckets.size > MAX_TRACKED_KEYS) buckets.clear();
    bucket = { count: 0, resetAt: now + windowMs };
    buckets.set(key, bucket);
  }
  bucket.count += 1;
  return bucket.count > max;
}

/** Best-effort caller IP from Vercel's forwarded-for header. */
function clientIp(req) {
  const fwd = req.headers["x-forwarded-for"];
  if (fwd) return fwd.split(",")[0].trim();
  return req.socket?.remoteAddress || "unknown";
}

module.exports = { isRateLimited, clientIp };
