/**
 * lib/r2.js
 * ---------
 * Two separate Cloudflare R2 (S3-compatible) clients, per the project's
 * bucket split: audio content lives in one R2 account/bucket, PDFs in a
 * second, independently-credentialed one.
 */
const { S3Client, PutObjectCommand, DeleteObjectCommand } = require("@aws-sdk/client-s3");

// .trim() defensively — Vercel's dashboard env-var UI has previously
// appended trailing whitespace/newlines to values (already hit for
// ADMIN_TOKEN in api/webapp/admin-stats.js and ADMIN_PASSWORD_HASH in this
// same admin app), which would otherwise surface as an opaque
// SignatureDoesNotMatch from R2 instead of a clear config error here.
function env(name) {
  return (process.env[name] || "").trim();
}

const audioR2 = new S3Client({
  region: "auto",
  endpoint: env("R2_ENDPOINT_URL"),
  credentials: {
    accessKeyId: env("R2_ACCESS_KEY_ID"),
    secretAccessKey: env("R2_SECRET_ACCESS_KEY"),
  },
});

const pdfR2 = new S3Client({
  region: "auto",
  endpoint: env("R2_PDF_ENDPOINT_URL"),
  credentials: {
    accessKeyId: env("R2_PDF_ACCESS_KEY_ID"),
    secretAccessKey: env("R2_PDF_SECRET_ACCESS_KEY"),
  },
});

/**
 * Upload a buffer to R2 and return its public URL.
 * @param {"audio"|"pdf"} kind - which bucket/client to use
 */
async function uploadToR2(kind, key, buffer, contentType) {
  const isPdf = kind === "pdf";
  const client = isPdf ? pdfR2 : audioR2;
  const bucket = env(isPdf ? "R2_PDF_BUCKET_NAME" : "R2_BUCKET_NAME");
  const publicBase = env(isPdf ? "R2_PDF_PUBLIC_URL" : "R2_PUBLIC_URL");
  const accessKeyId = env(isPdf ? "R2_PDF_ACCESS_KEY_ID" : "R2_ACCESS_KEY_ID");
  const secretAccessKey = env(isPdf ? "R2_PDF_SECRET_ACCESS_KEY" : "R2_SECRET_ACCESS_KEY");
  const endpoint = env(isPdf ? "R2_PDF_ENDPOINT_URL" : "R2_ENDPOINT_URL");

  // The AWS SDK's own error for missing credentials ("Resolved credential
  // object is not valid") gives no hint which env var is the problem or
  // which of the two R2 credential sets is at fault — check explicitly and
  // name the exact vars so a misconfigured Vercel project env is a 5-second
  // fix instead of a stack-trace hunt.
  const missing = [];
  if (!accessKeyId) missing.push(isPdf ? "R2_PDF_ACCESS_KEY_ID" : "R2_ACCESS_KEY_ID");
  if (!secretAccessKey) missing.push(isPdf ? "R2_PDF_SECRET_ACCESS_KEY" : "R2_SECRET_ACCESS_KEY");
  if (!endpoint) missing.push(isPdf ? "R2_PDF_ENDPOINT_URL" : "R2_ENDPOINT_URL");
  if (!bucket) missing.push(isPdf ? "R2_PDF_BUCKET_NAME" : "R2_BUCKET_NAME");
  if (missing.length) {
    throw new Error(
      `R2 upload misconfigured: missing ${missing.join(", ")}. These must be set on the ` +
      `menzum-admin Vercel project specifically — it's a separate project from the bot's ` +
      `menzum project, so env vars set there don't carry over.`
    );
  }

  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: buffer,
      ContentType: contentType || "application/octet-stream",
    })
  );

  return `${publicBase.replace(/\/$/, "")}/${key}`;
}

/**
 * Recover the R2 object key from a public URL previously returned by
 * uploadToR2() — the object key is never stored separately, only the full
 * public URL (in files.r2_url / files.thumb_url / pdfs.r2_url), so deleting
 * an object means reversing the exact same publicBase + "/" + key join
 * uploadToR2() does above. Returns null if the URL doesn't start with the
 * expected public base for `kind` (e.g. it's not actually an R2 URL, or it's
 * from the other bucket) — callers must treat null as "can't delete this,
 * don't guess."
 */
function keyFromUrl(kind, url) {
  if (!url) return null;
  const isPdf = kind === "pdf";
  const publicBase = env(isPdf ? "R2_PDF_PUBLIC_URL" : "R2_PUBLIC_URL").replace(/\/$/, "");
  if (!publicBase || !url.startsWith(`${publicBase}/`)) return null;
  return url.slice(publicBase.length + 1);
}

/**
 * Permanently delete an R2 object by its public URL (as stored in Mongo).
 * Throws if the key can't be derived (see keyFromUrl) or the delete fails —
 * callers doing a "delete forever" flow should catch this per-object so one
 * failed R2 delete doesn't block removing the Mongo doc or the other object.
 */
async function deleteFromR2(kind, url) {
  const key = keyFromUrl(kind, url);
  if (!key) {
    throw new Error(`Could not resolve an R2 key from URL: ${url}`);
  }
  const isPdf = kind === "pdf";
  const client = isPdf ? pdfR2 : audioR2;
  const bucket = env(isPdf ? "R2_PDF_BUCKET_NAME" : "R2_BUCKET_NAME");
  await client.send(new DeleteObjectCommand({ Bucket: bucket, Key: key }));
}

module.exports = { audioR2, pdfR2, uploadToR2, deleteFromR2, keyFromUrl };
