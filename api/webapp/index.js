/**
 * api/webapp/index.js
 * --------------------
 * SINGLE consolidated entry point for every /api/webapp/* endpoint.
 *
 * WHY THIS EXISTS: vercel.json's `builds` array uses an explicit glob
 * (`api/webapp/*.js`) — that's the legacy Vercel v2 build config, which
 * turns EVERY matched file into its own Serverless Function, including the
 * `_`-prefixed "shared module" files (_auth.js, _db.js, _rateLimit.js). The
 * automatic exclusion of `_`-prefixed files from function counting is a
 * zero-config/file-system-routing feature; it does not apply to an explicit
 * `builds` array. That's how this project silently crossed Hobby's 12
 * Serverless Function cap: 10 real endpoints + 3 shared files + api/index.py
 * = 14.
 *
 * This file merges all 10 endpoint handlers into ONE function. Every one of
 * them is required completely unchanged below — same file, same logic, same
 * auth wrapper, same response shape. vercel.json now routes every
 * /api/webapp/* request here with the real route name passed through as a
 * `__route` query param (see the routing rule); this file reads that param,
 * looks up the matching handler, deletes the param so it doesn't leak into
 * the handler's own req.query, and calls the handler exactly as Vercel would
 * have called it directly before. No endpoint's URL, method, request
 * shape, response shape, or auth behavior changes.
 */
const HANDLERS = {
  "admin-stats": require("./admin-stats"),
  "auth":        require("./auth"),
  "categories":  require("./categories"),
  "featured":    require("./featured"),
  "library":     require("./library"),
  "pdf-view":    require("./pdf-view"),
  "pdfs":        require("./pdfs"),
  "play":        require("./play"),
  "search":      require("./search"),
  "thumb":       require("./thumb"),
};

module.exports = async function handler(req, res) {
  const routeName = req.query && req.query.__route;
  const target = routeName && HANDLERS[routeName];

  if (!target) {
    return res.status(404).json({ ok: false, error: "Not found." });
  }

  // Don't leak our own routing plumbing into the handler's req.query — none
  // of them expect this key, and every one of them reads req.query directly
  // (never enumerates all keys), so this is purely defensive.
  delete req.query.__route;

  return target(req, res);
};
