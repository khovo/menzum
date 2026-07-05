/**
 * lib/categories.js
 * -----------------
 * The 5 fixed category slugs used across the whole project (bot + Mini App +
 * this panel): eshq, abret, katbare, raya, neshida. Default display names are
 * editable — overrides are stored in the `categories` collection
 * ({_id: slug, display_name}) and merged over these defaults.
 *
 * NOTE: elsewhere in the codebase "neshida" is detected live via a title
 * regex (/ነሺዳ|neshida/i), not a stored field — it was never a `genre` enum
 * value on file docs. This admin panel additionally allows tagging
 * genre="neshida" directly at upload time (for the category dropdown /
 * per-category counts here). Both mechanisms can coexist without conflict,
 * but a track's regex-based neshida match and its stored genre tag aren't
 * automatically kept in sync.
 */
const CATEGORY_SLUGS = ["neshida", "eshq", "abret", "katbare", "raya"];

const DEFAULT_LABELS = {
  neshida: "Neshida",
  eshq: "Eshq",
  abret: "Abret",
  katbare: "Katbare",
  raya: "Raya",
};

module.exports = { CATEGORY_SLUGS, DEFAULT_LABELS };
