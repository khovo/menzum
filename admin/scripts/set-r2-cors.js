/**
 * scripts/set-r2-cors.js
 * -----------------------
 * One-time (idempotent) setup for the presigned direct-to-R2 upload flow
 * (Bug 2 / H9 fix, see lib/uploadClient.js). Browsers preflight EVERY
 * cross-origin PUT regardless of headers; with no CORS policy configured on
 * an R2 bucket, that preflight has nothing to approve it with, so the
 * browser never sends the real upload and fetch()/XHR fails with a generic
 * "Failed to fetch" — there's no server response to read, because the
 * request never left the browser. Confirmed live: `r2_bucket_get` on both
 * `almadih-files` and `almadih-pdfs` shows no CORS configuration at all.
 *
 * This script sets an equivalent policy via R2's S3-compatible
 * PutBucketCors API — no dashboard access needed. Requires the SAME env
 * vars the admin panel itself uses (R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/
 * R2_ENDPOINT_URL/R2_BUCKET_NAME for audio, the R2_PDF_* equivalents for
 * PDFs) — pull them from the menzum-admin Vercel project first:
 *
 *   cd admin && vercel env pull .env.local && node scripts/set-r2-cors.js
 *
 * Re-run any time the admin panel's origin changes (e.g. a new custom
 * domain) — running it again just overwrites the policy with the current
 * ALLOWED_ORIGINS list below, it never appends.
 */
const fs = require("fs");
const path = require("path");

// Minimal inline .env.local loader (no dotenv dependency needed for a
// one-off script) — same KEY=VALUE parsing every other .env* file in this
// repo uses.
const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = val;
  }
}

const { getBucketCors, putBucketCors } = require("../lib/r2");

// The admin panel's known origins. Vercel preview deployments (one per
// branch/PR) get a random *.vercel.app subdomain each time — the leading
// wildcard covers those; add a specific origin here too if you ever put the
// admin panel behind a custom domain.
const ALLOWED_ORIGINS = [
  "https://menzum-admin.vercel.app",
  "https://menzum-admin-khalid5.vercel.app",
  "https://menzum-admin-git-main-khalid5.vercel.app",
  "https://*.vercel.app",
  "http://localhost:3002",
];

async function main() {
  for (const kind of ["audio", "pdf"]) {
    const before = await getBucketCors(kind);
    console.log(`[${kind}] CORS rules before:`, JSON.stringify(before));
    await putBucketCors(kind, ALLOWED_ORIGINS);
    const after = await getBucketCors(kind);
    console.log(`[${kind}] CORS rules after: `, JSON.stringify(after));
  }
  console.log("\nDone. Re-test a PDF/audio upload from the admin panel now.");
}

main().catch((err) => {
  console.error("set-r2-cors.js failed:", err.message);
  process.exit(1);
});
