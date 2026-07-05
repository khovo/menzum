const { serializeLogoutCookie } = require("../../../lib/auth");

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  res.setHeader("Set-Cookie", serializeLogoutCookie());
  return res.status(200).json({ ok: true });
};

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
