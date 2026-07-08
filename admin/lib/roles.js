/**
 * lib/roles.js
 * ------------
 * Role + page-level permission matrix for the admin panel's multi-admin
 * accounts. Deliberately dependency-free (no mongodb import) so it's safe to
 * import from client components too — same reasoning as lib/categories.js
 * vs. lib/categoryHelpers.js.
 *
 * Scope note: permissions here gate page/nav visibility and a handful of
 * sensitive API routes (admin account management, notification sending).
 * They do NOT yet do fine-grained in-page action gating (e.g. disabling the
 * "Delete" button for a Moderator on the Audio page) — that's a possible
 * follow-up, not part of this pass.
 */

const ROLES = {
  SUPER_ADMIN: "super_admin",
  CONTENT_MANAGER: "content_manager",
  MODERATOR: "moderator",
  ANALYST: "analyst",
};

const ROLE_LABELS = {
  [ROLES.SUPER_ADMIN]: "Super Admin",
  [ROLES.CONTENT_MANAGER]: "Content Manager",
  [ROLES.MODERATOR]: "Moderator",
  [ROLES.ANALYST]: "Analyst",
};

// One entry per gated page/route.
const PERMISSIONS = {
  DASHBOARD: "dashboard",
  AUDIO: "audio",
  PDFS: "pdfs",
  PLAYLISTS: "playlists",
  USERS: "users",
  CATEGORIES: "categories",
  NOTIFICATIONS: "notifications",
  ANALYTICS: "analytics",
  ADMINS: "admins",
};

const ROLE_PERMISSIONS = {
  [ROLES.SUPER_ADMIN]: Object.values(PERMISSIONS),
  [ROLES.CONTENT_MANAGER]: [
    PERMISSIONS.DASHBOARD,
    PERMISSIONS.AUDIO,
    PERMISSIONS.PDFS,
    PERMISSIONS.PLAYLISTS,
    PERMISSIONS.CATEGORIES,
    PERMISSIONS.ANALYTICS,
  ],
  [ROLES.MODERATOR]: [
    PERMISSIONS.DASHBOARD,
    PERMISSIONS.AUDIO,
    PERMISSIONS.PDFS,
    PERMISSIONS.USERS,
  ],
  [ROLES.ANALYST]: [
    PERMISSIONS.DASHBOARD,
    PERMISSIONS.ANALYTICS,
    PERMISSIONS.USERS,
  ],
};

function hasPermission(role, permission) {
  return (ROLE_PERMISSIONS[role] || []).includes(permission);
}

module.exports = { ROLES, ROLE_LABELS, PERMISSIONS, ROLE_PERMISSIONS, hasPermission };
