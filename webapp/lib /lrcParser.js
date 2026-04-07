/**
 * lib/lrcParser.js
 * ----------------
 * Pure utility function: LRC string → sorted array of { time, text } objects.
 *
 * SUPPORTED FORMAT:
 *   [mm:ss.xx]  text line        ← 2-digit centiseconds (most common)
 *   [mm:ss.xxx] text line        ← 3-digit milliseconds (also common)
 *
 * A single LRC line can carry multiple timestamps (for repeated phrases):
 *   [00:10.00][01:25.50] Bismillah
 *   This is expanded into two separate { time, text } entries.
 *
 * Metadata tags (artist, title, album) are silently discarded:
 *   [ar:Artist Name]
 *   [ti:Track Title]
 *
 * RETURNS: array sorted ascending by time (seconds as float).
 * Empty or whitespace-only text lines are skipped.
 *
 * @param {string} lrcString  Raw LRC content from the database
 * @returns {{ time: number, text: string }[]}
 */
export function parseLrc(lrcString) {
  if (!lrcString || typeof lrcString !== "string") return [];

  // Matches [mm:ss.xx] or [mm:ss.xxx] — NOT metadata tags like [ar:...]
  const TIME_TAG_RE = /\[(\d{2}):(\d{2})\.(\d{2,3})\]/g;

  const result = [];

  for (const rawLine of lrcString.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;

    // Strip all time tags to isolate the lyric text
    const text = line.replace(TIME_TAG_RE, "").trim();
    if (!text) continue; // blank line or metadata-only line

    // Reset regex lastIndex before iterating over the same line
    TIME_TAG_RE.lastIndex = 0;

    let match;
    let foundAnyTag = false;

    while ((match = TIME_TAG_RE.exec(line)) !== null) {
      foundAnyTag = true;
      const minutes  = parseInt(match[1], 10);
      const seconds  = parseInt(match[2], 10);
      // Normalise 2-digit (centiseconds) and 3-digit (milliseconds) to seconds
      const fraction = match[3].length === 2
        ? parseInt(match[3], 10) / 100
        : parseInt(match[3], 10) / 1000;

      const time = minutes * 60 + seconds + fraction;
      result.push({ time, text });
    }

    // If a text line has no time tag at all, skip it (it's a comment/metadata)
    void foundAnyTag;
  }

  // Sort ascending by time so binary search and linear scan both work correctly
  return result.sort((a, b) => a.time - b.time);
}

/**
 * findActiveLine
 * --------------
 * Given a sorted lines array and the audio's currentTime (seconds),
 * returns the index of the line that should be highlighted.
 *
 * Uses a linear scan from the end — O(n) but n is typically < 200 lines,
 * and the result is cached between timeupdate events by the caller.
 *
 * Returns -1 if playback hasn't reached the first line yet.
 *
 * @param {{ time: number, text: string }[]} lines  Sorted output of parseLrc()
 * @param {number} currentTime  Audio element's currentTime in seconds
 * @returns {number}  Index of the active line, or -1
 */
export function findActiveLine(lines, currentTime) {
  if (!lines.length || currentTime < 0) return -1;

  let active = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].time <= currentTime) {
      active = i;
    } else {
      break;
    }
  }
  return active;
}
