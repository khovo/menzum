# Al-Madih Backend — API Documentation

Backend base URL (production): **`https://menzum.vercel.app`**

This document describes **every HTTP endpoint** the Al-Madih backend currently exposes, so a
mobile (Flutter) app can talk to the existing backend instead of building a new one.

> ⚠️ **READ THIS FIRST — the honest summary.**
> This backend was built **exclusively for a Telegram bot + Telegram Mini App**. As of today it has:
> - **No OTP / phone / email / password login, and no JWT/session tokens.** The only user
>   authentication is **Telegram Mini App `initData`** (an HMAC signature that *only the Telegram
>   app can generate*). A standalone Flutter app running outside Telegram **cannot currently
>   authenticate** to the user endpoints.
> - **No public audio URL / audio streaming endpoint.** Audio is never served as a file the app
>   can play. Tapping "play" makes the backend push the audio **into the user's Telegram chat**
>   via the bot. There is no way today to stream a track inside a non-Telegram app.
>
> So the backend is **not ready** for a standalone mobile app as-is. The endpoints below are
> fully documented, and [Section 9](#9-is-the-backend-ready-for-a-mobile-app) lists exactly what
> must change. Please read Sections 2 and 9 before estimating work.

---

## Table of contents

1. [Architecture in one minute](#1-architecture-in-one-minute)
2. [Authentication (how it works today)](#2-authentication-how-it-works-today)
3. [Quick reference — all endpoints](#3-quick-reference--all-endpoints)
4. [User endpoints (Mini App API)](#4-user-endpoints-mini-app-api)
5. [PDF endpoints](#5-pdf-endpoints)
6. [Media/asset endpoints (images, PDF bytes)](#6-mediaasset-endpoints-images-pdf-bytes)
7. [Admin endpoint](#7-admin-endpoint)
8. [Data models](#8-data-models)
9. [Is the backend ready for a mobile app?](#9-is-the-backend-ready-for-a-mobile-app)
10. [Recommended changes to support the Flutter app](#10-recommended-changes-to-support-the-flutter-app)

---

## 1. Architecture in one minute

- **Two Vercel projects share one MongoDB database (`MenzumaDB`):**
  - **Bot project** → `https://menzum.vercel.app` — this is the **API host**. It runs:
    - a Python Telegram webhook at `/` (not for the app), and
    - the Node.js JSON API under `/api/webapp/*` (this is what the app uses).
  - **Frontend project** → `https://almadih.vercel.app` — the Telegram Mini App (a Next.js web UI). It calls the bot project's API. The Flutter app would replace/parallel this frontend.
- **Audio & PDFs are stored on Telegram's servers**, not on Vercel. The database only stores a
  Telegram **`file_id`** per track/PDF. The backend resolves `file_id` → a temporary Telegram
  CDN URL on demand. **`file_id` is intentionally never returned to clients.**
- All `/api/webapp/*` endpoints already send permissive **CORS** headers (`Access-Control-Allow-Origin: *`), because the Mini App is on a different origin. So cross-origin calls from an app are not blocked. (CORS is irrelevant for native mobile anyway.)

---

## 2. Authentication (how it works today)

There are **two** auth schemes. Neither is a classic email/OTP/JWT flow.

### 2a. Telegram Mini App `initData` (all user endpoints)

Every user-facing endpoint (except the public image proxy) requires this header:

```
Authorization: tma <initData>
```

`<initData>` is the raw query-string that Telegram injects into a Mini App at runtime
(`window.Telegram.WebApp.initData`). The server (`api/webapp/_auth.js`) validates it by:

1. Parsing the query string and pulling out the `hash` field.
2. Recomputing `HMAC_SHA256(data_check_string, key=HMAC_SHA256("WebAppData", BOT_TOKEN))`.
3. Comparing the computed hash to the supplied `hash` (constant-time).
4. Rejecting if `auth_date` is older than **24 hours**.

On success the server trusts the embedded Telegram `user` object (id, first_name, …).

**Implications for a Flutter app:**
- This signature can only be produced by the official Telegram client when it opens a Mini App.
  A normal Flutter app has no way to generate a valid `initData`, so **it cannot call these
  endpoints directly**. (The only exceptions: running your UI inside a Telegram WebView, or
  implementing Telegram Login and a new server-side validator — see Section 10.)
- There is **no token to "get"**, no refresh token, no expiry beyond the 24h `auth_date`.
- The exception `auth.js` accepts `initData` in the request **body** instead of the header
  (because it runs before a session exists). All other endpoints use the header.

### 2b. Admin Bearer token (admin dashboard only)

The analytics endpoint uses a static shared secret:

```
Authorization: Bearer <ADMIN_TOKEN>
```

`ADMIN_TOKEN` is a server-side env var (a password the admin types into the dashboard). This is
**not** a per-user login and should not be shipped in the mobile app.

### What does NOT exist

❌ Send OTP · ❌ Verify OTP · ❌ Email/password register or login · ❌ JWT / access tokens /
refresh tokens · ❌ phone-number auth · ❌ any `/auth/login`, `/auth/otp`, `/register` route.

---

## 3. Quick reference — all endpoints

All under base `https://menzum.vercel.app`.

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/api/webapp/auth` | `initData` in **body** | Validate user, return profile |
| 2 | GET | `/api/webapp/featured` | `tma` header | Paged catalog (latest tracks) |
| 3 | GET | `/api/webapp/search` | `tma` header | Search tracks + PDFs |
| 4 | GET | `/api/webapp/library` | `tma` header | User favorites + listening stats |
| 5 | POST | `/api/webapp/play` | `tma` header | Deliver a track / toggle favorite |
| 6 | GET | `/api/webapp/pdfs` | `tma` header | Paged PDF list |
| 7 | POST | `/api/webapp/pdfs` | `tma` header | Favorite / deliver a PDF |
| 8 | GET | `/api/webapp/pdf-view` | `tma` header | Get a PDF URL / stream PDF bytes |
| 9 | GET | `/api/webapp/thumb` | **public** | 302-redirect to a track's cover image |
| 10 | GET | `/api/webapp/admin-stats` | `Bearer ADMIN_TOKEN` | Analytics (admin only) |
| 11 | POST | `/` and `/api/webhook` | Telegram only | Telegram bot webhook (not for the app) |

Common conventions:
- Success responses are JSON `{ "ok": true, ... }`. Errors are `{ "ok": false, "error": "..." }`.
- Pagination is **cursor-based**: pass `?cursor=<next_cursor>` from the previous response. Page size 20 (max 50 via `?limit=`).
- All IDs returned to the client are 24-char Mongo ObjectId hex strings.

---

## 4. User endpoints (Mini App API)

### 1) POST `/api/webapp/auth` — validate session & get profile

The app calls this once on startup. **This is the only endpoint that takes `initData` in the body.**

**Request**
```
POST https://menzum.vercel.app/api/webapp/auth
Content-Type: application/json
```
```json
{ "initData": "query_id=...&user=%7B...%7D&auth_date=...&hash=..." }
```

**Response 200**
```json
{
  "ok": true,
  "user": {
    "id": 123456789,
    "first_name": "Ahmed",
    "last_name": "",
    "username": "ahmed",
    "favorites_count": 12,
    "baraka_points": 0
  }
}
```

**Response 401** — invalid/expired `initData`
```json
{ "ok": false, "error": "Hash mismatch — invalid initData." }
```

---

### 2) GET `/api/webapp/featured` — catalog (latest tracks, paged)

Returns tracks newest-first. Use for the Home / "all menzuma" list with infinite scroll.

**Request**
```
GET https://menzum.vercel.app/api/webapp/featured?cursor=<optional>&limit=20
Authorization: tma <initData>
```
Query params: `cursor` (optional, the `next_cursor` from the previous page), `limit` (optional, default 20, max 50).

**Response 200**
```json
{
  "ok": true,
  "tracks": [
    { "id": "64a1b2c3d4e5f6a7b8c9d0e1", "name": "Husni Sultan - Ya Nabi", "is_favorite": false, "has_thumb": true },
    { "id": "64a1b2c3d4e5f6a7b8c9d0e2", "name": "Menzuma 2",            "is_favorite": true,  "has_thumb": false }
  ],
  "has_more": true,
  "next_cursor": "64a1b2c3d4e5f6a7b8c9d0e2"
}
```
- `is_favorite` — whether this track is in the calling user's favorites.
- `has_thumb` — whether a cover image exists (use endpoint #9 to display it).
- ⚠️ Note: there is **no `audio_url`** here. There is no field that lets the app play the track. See Section 9.

---

### 3) GET `/api/webapp/search` — search tracks + PDFs

Case-insensitive AND-regex search on track `display_name` / PDF `title`.

**Request**
```
GET https://menzum.vercel.app/api/webapp/search?q=husni&type=all&cursor=<optional>&limit=20
Authorization: tma <initData>
```
Query params:
- `q` — search term (empty `q` returns the latest tracks).
- `type` — `all` (default), `audio`, or `pdf`. In `all`, audio results come first, with up to 5 PDFs appended.
- `cursor`, `limit` — pagination (applies to audio results).

**Response 200**
```json
{
  "ok": true,
  "query": "husni",
  "tracks": [
    { "id": "64a1...e1", "name": "Husni Sultan - Ya Nabi", "is_favorite": false, "has_thumb": true, "type": "audio" },
    { "id": "64b2...f9", "name": "Husni biography (PDF)",   "is_favorite": false,                    "type": "pdf"  }
  ],
  "has_more": false,
  "next_cursor": null
}
```
(The array is named `tracks` for frontend compatibility but may contain both `type: "audio"` and `type: "pdf"` items.)

---

### 4) GET `/api/webapp/library` — favorites + listening stats

Everything needed for a "My Library" screen.

**Request**
```
GET https://menzum.vercel.app/api/webapp/library
Authorization: tma <initData>
```

**Response 200**
```json
{
  "ok": true,
  "stats": {
    "total_plays": 47,
    "total_favorites": 12,
    "most_played": [
      { "track_id": "64a1...e1", "name": "Husni Sultan - Ya Nabi", "play_count": 6 }
    ]
  },
  "favorites": [
    { "id": "64a1...e1", "name": "Husni Sultan - Ya Nabi", "is_favorite": true, "has_thumb": true }
  ],
  "pdf_favorites": [
    { "id": "64b2...f9", "name": "Diwan al-Burdah", "is_favorite": true, "type": "pdf" }
  ]
}
```

---

### 5) POST `/api/webapp/play` — deliver a track OR toggle favorite

This is the **core action** endpoint. ⚠️ Read carefully — `action: "play"` does **not** return
audio; it pushes the audio file into the user's **Telegram chat** with the bot.

**Request**
```
POST https://menzum.vercel.app/api/webapp/play
Authorization: tma <initData>
Content-Type: application/json
```
```json
{ "track_id": "64a1b2c3d4e5f6a7b8c9d0e1", "action": "play" }
```
`action` is `"play"` (default) or `"favorite"`.

**Response 200 — `action: "play"`** (the track was sent to the user's Telegram chat)
```json
{ "ok": true, "action": "play", "track_name": "Husni Sultan - Ya Nabi" }
```

**Response 200 — `action: "favorite"`** (favorite toggled)
```json
{ "ok": true, "action": "favorite", "is_favorite": true }
```

**Errors**
```json
{ "ok": false, "error": "Invalid track_id." }                                  // 400
{ "ok": false, "error": "Track not found." }                                   // 404
{ "ok": false, "error": "Please start the bot first: send /start to @Almadihbot" } // 502 (user never opened the bot)
```
Side effects of a successful `play`: increments `users.total_plays` and appends to a capped
(50-entry) `users.listen_history`. **For a real mobile app, `play` is not useful** — there is
no in-app audio. `favorite` works fine for any logged-in user.

---

## 5. PDF endpoints

### 6) GET `/api/webapp/pdfs` — list PDFs (paged)

**Request**
```
GET https://menzum.vercel.app/api/webapp/pdfs?cursor=<optional>&limit=20
Authorization: tma <initData>
```

**Response 200**
```json
{
  "ok": true,
  "pdfs": [
    { "id": "64b2...f9", "title": "Diwan al-Burdah", "file_name": "burdah.pdf", "is_favorite": false }
  ],
  "has_more": false,
  "next_cursor": null
}
```

### 7) POST `/api/webapp/pdfs` — favorite or deliver a PDF

**Request**
```
POST https://menzum.vercel.app/api/webapp/pdfs
Authorization: tma <initData>
Content-Type: application/json
```
```json
{ "action": "favorite", "pdf_id": "64b2c3d4e5f6a7b8c9d0e1f9" }
```
`action` is `"favorite"` (toggle) or `"deliver"` (send the PDF into the user's Telegram chat).

**Response 200**
```json
{ "ok": true, "action": "favorite", "is_favorite": true }
```
```json
{ "ok": true, "action": "deliver", "title": "Diwan al-Burdah" }
```
**Errors:** `400 Invalid pdf_id.` · `404 PDF not found.` · `502` (with a "send /start" hint when delivering and the user never opened the bot).

### 8) GET `/api/webapp/pdf-view` — get a PDF URL or stream its bytes

Unlike audio, PDFs **can** be viewed in-app via this endpoint.

**Mode A — get a temporary URL (JSON):**
```
GET https://menzum.vercel.app/api/webapp/pdf-view?id=64b2...f9
Authorization: tma <initData>
```
```json
{ "ok": true, "url": "https://api.telegram.org/file/bot<TOKEN>/documents/file_123.pdf" }
```
**Mode B — stream the bytes (for an in-app viewer with range support):**
```
GET https://menzum.vercel.app/api/webapp/pdf-view?id=64b2...f9&action=stream
Authorization: tma <initData>
Range: bytes=0-           (optional, supported → 206 Partial Content)
```
Returns the raw PDF (`Content-Type: application/pdf`), supports `Range`/`Content-Range` for progressive loading. `404` if the PDF or its Telegram file can't be resolved.

> 🔐 **Security note for the dev:** Mode A's returned `url` (and the redirect target of endpoint
> #9) contains the bot token in the path (`/bot<TOKEN>/...`). That's how Telegram's file API
> works, but it means the bot token is exposed to any client that receives these URLs. Prefer
> the **streaming** mode (B) for PDFs, and see Section 10 for audio.

---

## 6. Media/asset endpoints (images, PDF bytes)

### 9) GET `/api/webapp/thumb` — track cover image (public, no auth)

A zero-bandwidth image proxy: it 302-redirects to the track's cover on Telegram's CDN. Use it
directly as an `<img>`/`Image.network` source.

**Request**
```
GET https://menzum.vercel.app/api/webapp/thumb?id=<track_id>
```
- `id` — the **track's** 24-char id (same `id` returned by featured/search).
- **No auth required** (it only serves cover art).

**Response:** `302 Found` → `Location: https://api.telegram.org/file/bot<TOKEN>/photos/...jpg`
(cache ~50 min). Returns `404` if the track has no cover (so the UI should fall back to a
placeholder). Only request it when `has_thumb: true`.

---

## 7. Admin endpoint

### 10) GET `/api/webapp/admin-stats` — analytics (admin only)

**Do not ship `ADMIN_TOKEN` in the mobile app.** Documented for completeness.

**Request**
```
GET https://menzum.vercel.app/api/webapp/admin-stats
Authorization: Bearer <ADMIN_TOKEN>
```

**Response 200**
```json
{
  "ok": true,
  "stats": {
    "totalUsers": 1234,
    "totalFiles": 1150,
    "totalPlays": 56789,
    "activeUsers": 87,
    "userGrowth": [ { "date": "06-01", "users": 12 } ],
    "trendingTracks": [ { "name": "Husni Sultan…", "plays": 240 } ]
  }
}
```
`401 Invalid token.` on a bad/missing token.

---

## 8. Data models

**Track (`files` collection)** — returned fields only:
| field | type | notes |
|-------|------|-------|
| `id` | string | 24-char ObjectId |
| `name` | string | the `display_name` |
| `is_favorite` | bool | per calling user |
| `has_thumb` | bool | cover exists → use `/thumb?id=` |

> `file_id` (the Telegram handle for the actual audio) is stored server-side and **never returned**.

**PDF (`pdfs` collection):** `id`, `title`, `file_name`, `is_favorite`, `download_count` (server-side).

**User (`users` collection):** `_id` is the **Telegram user id (int)**; `first_name`,
`joined_at`, `last_active`, `favorites` (array of audio `file_id`), `pdf_favorites` (array of
PDF id strings), `total_plays`, `listen_history` (capped 50), `baraka_points`.

**Playlists (`playlists` collection):** exist in the DB and the bot, but **there is no HTTP API
endpoint for playlists** — they are created/shared only inside the Telegram bot. The app cannot
list or create playlists today (see Section 10).

---

## 9. Is the backend ready for a mobile app?

**Short answer: No — not for a standalone Flutter app. Two hard blockers, plus some gaps.**

| Concern | Status | Detail |
|--------|--------|--------|
| **CORS** | ✅ Ready | All `/api/webapp/*` endpoints send `Access-Control-Allow-Origin: *`. (Also irrelevant for native mobile.) |
| **Auth** | ❌ Blocker | Only Telegram `initData` (HMAC) — a standalone app cannot generate it. No OTP/email/password/JWT exists. |
| **Audio playback** | ❌ Blocker | No endpoint returns a playable audio URL/stream. `play` only pushes audio into the user's Telegram chat. The app literally cannot play a track today. |
| **Browse / search / favorites** | ⚠️ Works *if* authenticated | Endpoints 2–5 are solid; they just need a way for the app to authenticate. |
| **PDFs** | ✅ Mostly | `pdf-view?action=stream` already serves bytes with range support. |
| **Playlists** | ❌ Missing | No HTTP API; bot-only. |
| **Bot token exposure** | ⚠️ Risk | `pdf-view` (Mode A) and `thumb` hand the client a URL containing the bot token. |

So before the Flutter app can do anything beyond showing cover thumbnails (the only public
endpoint), the backend needs an **auth method usable outside Telegram** and an **audio delivery
method usable outside Telegram**.

---

## 10. Recommended changes to support the Flutter app

Listed in priority order. Items 1 and 2 are required; the rest are strongly recommended.

### 1. Add a real authentication flow (REQUIRED)
Pick one:
- **(Recommended) Telegram Login** — use Telegram's Login Widget / `tg://` deep link or the
  Telegram OAuth flow to obtain a signed payload, then add a server endpoint that validates it
  with the same HMAC approach already in `_auth.js` and issues your **own JWT**. Keeps the
  existing "users are Telegram users" model, no new identity system.
- **Phone OTP via Telegram Gateway / an SMS provider** — add `POST /api/webapp/otp/send` and
  `POST /api/webapp/otp/verify` that issue a JWT. This is the classic "send OTP / verify OTP /
  get token" flow you asked about; it does **not** exist yet and would be net-new work
  (OTP store, rate limiting, provider integration).
- Then add JWT middleware (a sibling of `withAuth`) so all user endpoints accept
  `Authorization: Bearer <jwt>` in addition to `tma <initData>`.

### 2. Add an audio delivery endpoint for the app (REQUIRED)
The pattern already exists for PDFs in `pdf-view.js` — clone it for audio:
- `GET /api/webapp/audio?id=<track_id>&action=stream` → resolve `file_id` server-side, fetch
  from Telegram's CDN, and **stream the bytes** back with `Content-Type: audio/mpeg` and
  `Range` support (so the player can seek). This keeps `file_id` and the bot token hidden from
  the client (unlike returning a raw Telegram URL).
- Add an `audio_url` (pointing at this endpoint) to the `featured`/`search`/`library` track
  objects so the app knows how to play each track.

### 3. Expose playlists over HTTP (recommended)
Add `GET /api/webapp/playlists`, `POST /api/webapp/playlists`, `GET /api/webapp/playlists/:id`
backed by the existing `playlists` collection, so the app has feature parity with the bot.

### 4. Add categories/genres (only if you want them)
There is **no category/genre system today** — tracks have only a `display_name`. If the app
needs categories, add a `category` field to `files` and a `GET /api/webapp/categories` endpoint.

### 5. Stop leaking the bot token in URLs (recommended)
Have `thumb` and `pdf-view` (Mode A) stream bytes (or sign a short-lived proxy URL) instead of
redirecting/returning `https://api.telegram.org/file/bot<TOKEN>/...`.

### 6. Operational notes
- These run as Vercel serverless functions with short timeouts; streaming large audio should be
  fine but test cold-start latency.
- No rate limiting exists on the user endpoints — add some before a public app launch.
- The same `MenzumaDB` is shared with the live bot, so new endpoints must keep the existing
  document shapes intact.

---

*Generated from the source in this repository (`api/webapp/*.js`, `api/index.py`). If the
backend changes, regenerate this doc so the mobile team stays in sync.*
