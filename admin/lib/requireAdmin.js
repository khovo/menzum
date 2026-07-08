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
 *
 * Pass { permission } (a lib/roles.js PERMISSIONS value) to also require the
 * session's role to have that permission — a role without it is bounced to
 * the dashboard instead of rendering the page:
 *   const guard = requireAdmin(ctx, { permission: PERMISSIONS.ADMINS });
 */
const { getAdminFromCookieHeader } = require("./auth");
const { hasPermission } = require("./roles");

function requireAdmin(context, options = {}) {
  const { permission } = options;
  const admin = getAdminFromCookieHeader(context.req.headers.cookie);
  if (!admin) {
    return { redirect: { destination: "/login", permanent: false } };
  }
  if (permission && !hasPermission(admin.role, permission)) {
    return { redirect: { destination: "/", permanent: false } };
  }
  return null;
}

module.exports = { requireAdmin };
