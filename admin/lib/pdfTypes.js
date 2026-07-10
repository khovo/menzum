/**
 * lib/pdfTypes.js
 * ---------------
 * Extension -> canonical MIME type, shared by the multipart upload route
 * (pages/api/pdfs/index.js) and the presigned-upload route
 * (pages/api/pdfs/presign.js) so the two validate uploads identically.
 */
const ALLOWED_EXTENSIONS = {
  pdf: "application/pdf",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
  epub: "application/epub+zip",
};

module.exports = { ALLOWED_EXTENSIONS };
