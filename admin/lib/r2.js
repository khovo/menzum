/**
 * lib/r2.js
 * ---------
 * Two separate Cloudflare R2 (S3-compatible) clients, per the project's
 * bucket split: audio content lives in one R2 account/bucket, PDFs in a
 * second, independently-credentialed one.
 */
const { S3Client, PutObjectCommand } = require("@aws-sdk/client-s3");

const audioR2 = new S3Client({
  region: "auto",
  endpoint: process.env.R2_ENDPOINT_URL,
  credentials: {
    accessKeyId: process.env.R2_ACCESS_KEY_ID,
    secretAccessKey: process.env.R2_SECRET_ACCESS_KEY,
  },
});

const pdfR2 = new S3Client({
  region: "auto",
  endpoint: process.env.R2_PDF_ENDPOINT_URL,
  credentials: {
    accessKeyId: process.env.R2_PDF_ACCESS_KEY_ID,
    secretAccessKey: process.env.R2_PDF_SECRET_ACCESS_KEY,
  },
});

/**
 * Upload a buffer to R2 and return its public URL.
 * @param {"audio"|"pdf"} kind - which bucket/client to use
 */
async function uploadToR2(kind, key, buffer, contentType) {
  const client = kind === "pdf" ? pdfR2 : audioR2;
  const bucket = kind === "pdf" ? process.env.R2_PDF_BUCKET_NAME : process.env.R2_BUCKET_NAME;
  const publicBase = kind === "pdf" ? process.env.R2_PDF_PUBLIC_URL : process.env.R2_PUBLIC_URL;

  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: buffer,
      ContentType: contentType || "application/octet-stream",
    })
  );

  return `${(publicBase || "").replace(/\/$/, "")}/${key}`;
}

module.exports = { audioR2, pdfR2, uploadToR2 };
