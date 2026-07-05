/**
 * lib/requireAdmin.js
 * -------------------
 * Server-side page guard for getServerSideProps. Redirects to /login when the
 * session cookie is missing/invalid, so protected pages never render (even
 * briefly) for an unauthenticated visitor — unlike a client-only check.
 *
 * Usage in a page:
 *   export async function getServerSideProps(ctx) {
 *     const guard = requireAdmin(ctx);
 *     if (guard) return guard;
 *     return { props: {} };
 *   }
 */
const { getAdminFromCookieHeader } = require("./auth");

function requireAdmin(context) {
  const admin = getAdminFromCookieHeader(context.req.headers.cookie);
  if (!admin) {
    return { redirect: { destination: "/login", permanent: false } };
  }
  return null;
}

module.exports = { requireAdmin };
