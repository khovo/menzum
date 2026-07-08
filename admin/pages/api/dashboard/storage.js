/**
 * GET /api/dashboard/storage
 * Real R2 bucket usage (via S3 ListObjectsV2, paginated) for both the audio
 * and PDF buckets, plus MongoDB's own dbStats. This is the accurate
 * counterpart to dashboard/stats.js's storageUsedBytes, which only sums
 * size_bytes recorded at upload time through this panel (misses anything
 * migrated from Telegram without a recorded size).
 *
 * Listing every object can be slow on a large bucket — capped at MAX_PAGES
 * (1000 objects/page) so this stays within a serverless function's timeout;
 * past the cap the numbers are a lower bound and `truncated: true` is
 * returned so the UI can say so rather than silently under-reporting.
 */
const { ListObjectsV2Command } = require("@aws-sdk/client-s3");
const { audioR2, pdfR2 } = require("../../../lib/r2");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

const MAX_PAGES = 10; // ~10,000 objects per bucket

// Cloudflare R2 and MongoDB Atlas free-tier caps, used as sensible defaults
// for a usage percentage when no explicit limit is configured.
const DEFAULT_R2_LIMIT_BYTES = 10 * 1024 * 1024 * 1024; // 10 GB
const DEFAULT_MONGO_LIMIT_BYTES = 512 * 1024 * 1024; // 512 MB

function env(name) {
  return (process.env[name] || "").trim();
}

async function summarizeBucket(client, bucketName) {
  if (!bucketName) return { bytes: 0, objectCount: 0, truncated: false, configured: false };

  let bytes = 0;
  let objectCount = 0;
  let continuationToken;
  let pages = 0;
  let truncated = false;

  do {
    // eslint-disable-next-line no-await-in-loop
    const listRes = await client.send(new ListObjectsV2Command({
      Bucket: bucketName,
      ContinuationToken: continuationToken,
    }));
    for (const obj of listRes.Contents || []) {
      bytes += obj.Size || 0;
      objectCount += 1;
    }
    continuationToken = listRes.IsTruncated ? listRes.NextContinuationToken : undefined;
    pages += 1;
    if (continuationToken && pages >= MAX_PAGES) {
      truncated = true;
      break;
    }
  } while (continuationToken);

  return { bytes, objectCount, truncated, configured: true };
}

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const [audio, pdf, { db }] = await Promise.all([
      summarizeBucket(audioR2, env("R2_BUCKET_NAME")),
      summarizeBucket(pdfR2, env("R2_PDF_BUCKET_NAME")),
      connectToDatabase(),
    ]);

    const mongoStats = await db.command({ dbStats: 1 });

    const r2LimitBytes = Number(env("R2_STORAGE_LIMIT_BYTES")) || DEFAULT_R2_LIMIT_BYTES;
    const mongoLimitBytes = Number(env("MONGO_STORAGE_LIMIT_BYTES")) || DEFAULT_MONGO_LIMIT_BYTES;
    const r2TotalBytes = audio.bytes + pdf.bytes;
    const mongoDataBytes = mongoStats.dataSize || 0;

    return res.status(200).json({
      ok: true,
      r2: {
        audio,
        pdf,
        totalBytes: r2TotalBytes,
        limitBytes: r2LimitBytes,
        usedPercent: Math.min(100, (r2TotalBytes / r2LimitBytes) * 100),
      },
      mongo: {
        dataSizeBytes: mongoDataBytes,
        storageSizeBytes: mongoStats.storageSize || 0,
        indexSizeBytes: mongoStats.indexSize || 0,
        collections: mongoStats.collections || 0,
        limitBytes: mongoLimitBytes,
        usedPercent: Math.min(100, (mongoDataBytes / mongoLimitBytes) * 100),
      },
    });
  } catch (err) {
    console.error("api/dashboard/storage.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
