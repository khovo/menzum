/**
 * lib/parseForm.js
 * ----------------
 * Parses a multipart/form-data request (file uploads) with formidable.
 * Callers must set `export const config = { api: { bodyParser: false } }`
 * in their API route — Next.js's default JSON body parser must be disabled
 * for multipart requests to reach formidable un-consumed.
 */
const formidable = require("formidable");

async function parseForm(req, { maxFileSize = 200 * 1024 * 1024 } = {}) {
  const form = formidable({ multiples: false, maxFileSize });
  return new Promise((resolve, reject) => {
    form.parse(req, (err, fields, files) => {
      if (err) return reject(err);
      resolve({ fields, files });
    });
  });
}

/** formidable v3 wraps every field value in an array — unwrap to plain strings. */
function flat(fields) {
  const out = {};
  for (const [k, v] of Object.entries(fields || {})) {
    out[k] = Array.isArray(v) ? v[0] : v;
  }
  return out;
}

function flatFile(files, name) {
  const f = files && files[name];
  return Array.isArray(f) ? f[0] : f || null;
}

/**
 * Manually read + JSON.parse a request body on routes that set
 * `config.api.bodyParser = false` for multipart PUT/POST support — Next.js's
 * automatic body parser doesn't run on those routes for ANY method, so a
 * same-route JSON request (e.g. a PATCH toggle) needs to parse itself.
 */
function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => { data += chunk; });
    req.on("end", () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (err) {
        reject(new Error("Invalid JSON body."));
      }
    });
    req.on("error", reject);
  });
}

module.exports = { parseForm, flat, flatFile, readJsonBody };
