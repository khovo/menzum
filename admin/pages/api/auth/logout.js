const { serializeLogoutCookie } = require("../../../lib/auth");

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  res.setHeader("Set-Cookie", serializeLogoutCookie());
  return res.status(200).json({ ok: true });
};
